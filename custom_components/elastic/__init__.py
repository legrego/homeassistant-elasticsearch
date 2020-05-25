"""
Support for sending event data to an Elasticsearch cluster
"""
import os
import logging
import base64
import binascii
import json
import socket
from queue import Queue
from datetime import (datetime)
import asyncio
import math
from urllib.parse import quote
import voluptuous as vol
from pytz import utc
from homeassistant.core import callback
from homeassistant.const import (
    CONF_URL, CONF_USERNAME, CONF_PASSWORD, CONF_ALIAS, EVENT_STATE_CHANGED,
    CONF_EXCLUDE, CONF_DOMAINS, CONF_ENTITIES, CONF_VERIFY_SSL
)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import (
    state as state_helper,
    discovery
)

DOMAIN = 'elastic'
DATA_ELASTICSEARCH = 'elastic'

CONF_PUBLISH_ENABLED = 'publish_enabled'
CONF_HEALTH_SENSOR_ENABLED = 'health_sensor_enabled'
CONF_INDEX_FORMAT = 'index_format'
CONF_PUBLISH_FREQUENCY = 'publish_frequency'
CONF_ONLY_PUBLISH_CHANGED = 'only_publish_changed'
CONF_ILM_ENABLED = 'ilm_enabled'
CONF_ILM_POLICY_NAME = 'ilm_policy_name'
CONF_ILM_MAX_SIZE = 'ilm_max_size'
CONF_ILM_DELETE_AFTER = 'ilm_delete_after'
CONF_SSL_CA_PATH = 'ssl_ca_path'
CONF_CLOUD_ID = 'cloud_id'

CONF_TAGS = 'tags'

ELASTIC_COMPONENTS = [
    'sensor'
]

_LOGGER = logging.getLogger(__name__)

ONE_MINUTE = 60
ONE_HOUR = 60 * 60

VERSION_SUFFIX = "-v4_1"
INDEX_TEMPLATE_NAME = "hass-index-template" + VERSION_SUFFIX

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.All(
        vol.Schema({
            vol.Exclusive(CONF_URL, 'url or cloud_id'): cv.url,
            vol.Exclusive(CONF_CLOUD_ID, 'url or cloud_id'): cv.string,
            vol.Optional(CONF_USERNAME): cv.string,
            vol.Optional(CONF_PASSWORD): cv.string,
            vol.Optional(CONF_PUBLISH_ENABLED, default=True): cv.boolean,
            vol.Optional(CONF_HEALTH_SENSOR_ENABLED, default=True): cv.boolean,
            vol.Optional(CONF_PASSWORD): cv.string,
            vol.Optional(CONF_INDEX_FORMAT, default='hass-events'): cv.string,
            vol.Optional(CONF_ALIAS, default='active-hass-index'): cv.string,
            vol.Optional(CONF_PUBLISH_FREQUENCY, default=ONE_MINUTE): cv.positive_int,
            vol.Optional(CONF_ONLY_PUBLISH_CHANGED, default=False): cv.boolean,
            vol.Optional(CONF_ILM_ENABLED, default=True): cv.boolean,
            vol.Optional(CONF_ILM_POLICY_NAME, default="home-assistant"): cv.string,
            vol.Optional(CONF_ILM_MAX_SIZE, default='30gb'): cv.string,
            vol.Optional(CONF_ILM_DELETE_AFTER, default='365d'): cv.string,
            vol.Optional(CONF_VERIFY_SSL): cv.boolean,
            vol.Optional(CONF_SSL_CA_PATH): cv.string,
            vol.Optional(CONF_TAGS, default=['hass']): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional(CONF_EXCLUDE, default={}): vol.Schema({
                vol.Optional(CONF_DOMAINS, default=[]): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional(CONF_ENTITIES, default=[]): cv.entity_ids
            })
        }),
        cv.has_at_least_one_key(CONF_URL, CONF_CLOUD_ID),
    )
}, extra=vol.ALLOW_EXTRA)


async def async_setup(hass, config):
    """Setup the Elasticsearch component."""
    conf = config[DATA_ELASTICSEARCH]

    hass.data[DOMAIN] = {}

    _LOGGER.debug("Creating ES gateway")
    gateway = ElasticsearchGateway(hass, conf)
    await gateway.async_init()
    hass.data[DOMAIN]['gateway'] = gateway

    hass.data[DOMAIN][CONF_PUBLISH_ENABLED] = conf.get(CONF_PUBLISH_ENABLED)
    hass.data[DOMAIN][CONF_HEALTH_SENSOR_ENABLED] = conf.get(
        CONF_HEALTH_SENSOR_ENABLED)

    if conf.get(CONF_PUBLISH_ENABLED):
        _LOGGER.debug("Creating ES index manager")
        index_manager = IndexManager(hass, conf, gateway)
        await index_manager.async_setup()
        hass.data[DOMAIN]['index_manager'] = index_manager

        _LOGGER.debug("Creating document publisher")
        system_info = await hass.helpers.system_info.async_get_system_info()
        publisher = DocumentPublisher(conf, gateway, index_manager, hass, system_info)
        hass.data[DOMAIN]['publisher'] = publisher

        _LOGGER.debug("Creating service handler")
        service_handler = ServiceHandler(publisher)

        def elastic_event_listener(event):
            """Listen for new messages on the bus and queue them for send."""
            state = event.data.get('new_state')
            if state is None:
                return

            publisher.enqueue_state({"state": state, "event": event})

            return

        hass.bus.async_listen(EVENT_STATE_CHANGED, elastic_event_listener)

        hass.services.async_register(
            DOMAIN, 'publish_events', service_handler.publish_events)

    for component in ELASTIC_COMPONENTS:
        discovery.load_platform(hass, component, DOMAIN, {}, config)

    _LOGGER.info("Elastic component fully initialized")
    return True


class ServiceHandler:  # pylint: disable=unused-variable
    """Handles calls to exposed services"""

    def __init__(self, publisher):
        """Initializes the service handler"""
        self._publisher = publisher

    def publish_events(self, service):
        """Publishes all queued events to Elasticsearch"""
        self._publisher.async_do_publish()


class ElasticsearchVersion:  # pylint: disable=unused-variable
    """Maintains information about the verion of Elasticsearch"""
    def __init__(self, hass, client):
        self._client = client
        self._hass = hass
        self.version_number_str = None
        self.major = None
        self.minor = None
        self.build_flavor = None


    async def async_init(self):
        """I/O bound init"""
        version = (await self._client.info())["version"]
        version_number_parts = version["number"].split(".")
        self.version_number_str = version["number"]
        self.major = int(version_number_parts[0])
        self.minor = int(version_number_parts[1])
        self.build_flavor = version["build_flavor"]

    def is_supported_version(self):
        """Determines if this version of ES is supported by this component"""
        return self.major == 7 or (
            self.major == 6 and self.minor >= 7
        )

    def is_oss_distribution(self):
        """Determines if this is the OSS distribution"""
        return self.build_flavor == 'oss'

    def is_default_distribution(self):
        """Determines if this is the default distribution"""
        return self.build_flavor == 'default'

    def to_string(self):
        """Returns a string representation of the current ES version"""
        return self.version_number_str

class ElasticsearchGateway:  # pylint: disable=unused-variable
    """Encapsulates Elasticsearch operations"""

    def __init__(self, hass, config):
        """Initialize the gateway"""
        self._hass = hass
        self._url = config.get(CONF_URL)
        self._username = config.get(CONF_USERNAME)
        self._password = config.get(CONF_PASSWORD)
        self._cloud_id = config.get(CONF_CLOUD_ID)
        self._verify_certs = config.get(CONF_VERIFY_SSL)
        self._ca_certs = config.get(CONF_SSL_CA_PATH)

        if self._cloud_id:
            self._url = decode_cloud_id(self._cloud_id)

        _LOGGER.debug("Creating Elasticsearch client for %s", self._url)
        self.client = self._create_es_client()
        self.sync_client = self._create_es_client(sync=True)
        self.es_version = ElasticsearchVersion(self._hass, self.client)


    async def async_init(self):
        """I/O bound init"""

        await self.es_version.async_init()

        if not self.es_version.is_supported_version():
            _LOGGER.warning(
                "UNSUPPORTED VERSION OF ELASTICSEARCH DETECTED: %s. \
                This may function in unexpected ways, or fail entirely!",
                self.es_version.to_string()
            )

    def get_client(self):
        """Returns the underlying ES Client"""
        return self.client

    def get_sync_client(self):
        """Returns the underlying ES Client"""
        return self.sync_client

    def _create_es_client(self, sync=False):
        """Constructs an instance of the Elasticsearch client"""
        from elasticsearch_async import AsyncElasticsearch
        from elasticsearch import Elasticsearch

        use_basic_auth = self._username is not None and self._password is not None

        serializer = get_serializer()

        if use_basic_auth:
            auth = (self._username, self._password)
            return Elasticsearch(
                [self._url],
                http_auth=auth,
                serializer=serializer,
                verify_certs=self._verify_certs,
                ca_certs=self._ca_certs
            ) if sync else AsyncElasticsearch(
                [self._url],
                http_auth=auth,
                serializer=serializer,
                verify_certs=self._verify_certs,
                ca_certs=self._ca_certs
            )

        return Elasticsearch(
            [self._url],
            serializer=serializer,
            verify_certs=self._verify_certs,
            ca_certs=self._ca_certs
        ) if sync else AsyncElasticsearch(
            [self._url],
            serializer=serializer,
            verify_certs=self._verify_certs,
            ca_certs=self._ca_certs
        )

class IndexManager: # pylint: disable=unused-variable
    """ Index management facilities """

    def __init__(self, hass, config, gateway):
        """ Initializes index management """

        self.index_alias = config.get(CONF_ALIAS) + VERSION_SUFFIX

        self._hass = hass

        self._gateway = gateway

        self._ilm_policy_name = config.get(CONF_ILM_POLICY_NAME)

        self._index_format = config.get(CONF_INDEX_FORMAT) + VERSION_SUFFIX

        self._config = config

        self._using_ilm = True

    async def async_setup(self):
        """ Performs setup for index management. """
        version = self._gateway.es_version
        self._using_ilm = (
            version.is_default_distribution()
            and version.is_supported_version()
            and self._config.get(CONF_ILM_ENABLED)
        )

        await self._create_index_template()

        if not self._gateway.es_version.is_default_distribution():
            _LOGGER.info("\
                You are not running the default distribution of Elasticsearch, \
                so features such as Index Lifecycle Management are not available. \
                Download the default distribution from https://elastic.co/downloads \
            ")
        if self._using_ilm:
            await self._create_ilm_policy(self._config)

    async def _create_index_template(self):
        """
        Initializes the Elasticsearch cluster with an index template, initial index, and alias.
        """
        import elasticsearch

        client = self._gateway.get_client()

        es_version = self._gateway.es_version

        with open(os.path.join(os.path.dirname(__file__), 'index_mapping.json')) as json_file:
            mapping = json.load(json_file)

        if not await client.indices.exists_template(name=INDEX_TEMPLATE_NAME):
            _LOGGER.debug("Creating index template")

            mappings_body = mapping
            if es_version.major == 6:
                mappings_body = {
                    "doc": mapping
                }

            index_template = {
                "index_patterns": [self._index_format + "*"],
                "settings": {
                    "number_of_shards": 1,
                    "codec": "best_compression",
                    "mapping": {
                        "total_fields": {
                            "limit": "10000"
                        }
                    }
                },
                "mappings": mappings_body,
                "aliases": {
                    "all-hass-events": {}
                }
            }
            if self._using_ilm:
                index_template["settings"]["index.lifecycle.name"] = self._ilm_policy_name
                index_template["settings"]["index.lifecycle.rollover_alias"] = self.index_alias

            try:
                await client.indices.put_template(
                    name=INDEX_TEMPLATE_NAME,
                    body=index_template
                )
            except elasticsearch.ElasticsearchException as err:
                _LOGGER.exception("Error creating index template: %s", err)

        if not await client.indices.exists_alias(name=self.index_alias):
            _LOGGER.debug("Creating initial index and alias")
            try:
                await client.indices.create(index=self._index_format + "-000001", body={
                    "aliases": {
                        self.index_alias: {
                            "is_write_index": True
                        }
                    }
                })
            except elasticsearch.ElasticsearchException as err:
                _LOGGER.exception(
                    "Error creating initial index/alias: %s", err)
        elif self._using_ilm:
            _LOGGER.debug("Ensuring ILM Policy is attached to existing index")
            try:
                await client.indices.put_settings(index=self.index_alias, preserve_existing=True, body={
                    "index.lifecycle.name": self._ilm_policy_name,
                    "index.lifecycle.rollover_alias": self.index_alias
                })
            except elasticsearch.ElasticsearchException as err:
                _LOGGER.exception(
                    "Error updating index ILM settings: %s", err)

    async def _create_ilm_policy(self, config):
        """
        Creates the index lifecycle management policy.
        """
        import elasticsearch

        client = self._gateway.get_client()

        # The ES Client does not currently support the ILM APIs,
        # so we craft this one by hand
        encoded_policy_name = quote(
            self._ilm_policy_name.encode("utf-8"), safe='')

        url = '/_ilm/policy/{}'.format(encoded_policy_name)

        try:
            existing_policy = await client.transport.perform_request('GET', url)
        except elasticsearch.TransportError as err:
            if err.status_code == 404:
                existing_policy = None
            else:
                _LOGGER.exception("Error checking for existing ILM policy: %s", err)
                raise err

        ilm_hot_conditions = {
            "max_size": config.get(CONF_ILM_MAX_SIZE)
        }

        policy = {
            "policy": {
                "phases": {
                    "hot": {
                        "min_age": "0ms",
                        "actions": {
                            "rollover": ilm_hot_conditions
                        }
                    },
                    "delete": {
                        "min_age": config.get(CONF_ILM_DELETE_AFTER),
                        "actions": {
                            "delete": {}
                        }
                    }
                }
            }
        }

        if existing_policy:
            _LOGGER.info(
                "Updating existing ILM Policy '%s'", self._ilm_policy_name
            )
        else:
            _LOGGER.info(
                "Creating ILM Policy '%s'", self._ilm_policy_name
            )

        await client.transport.perform_request('PUT', url, body=policy)

class DocumentPublisher:  # pylint: disable=unused-variable
    """Publishes documents to Elasticsearch"""

    def __init__(self, config, gateway, index_manager, hass, system_info):
        """Initialize the publisher"""
        self._gateway = gateway
        self._hass = hass

        self._index_alias = index_manager.index_alias

        self._serializer = get_serializer()

        config_dict = hass.config.as_dict()
        self._static_doc_properties = {
            'agent.name': config_dict['name'] if 'name' in config_dict else 'My Home Assistant',
            'agent.type': 'hass',
            'agent.version': system_info['version'],
            'ecs.version': '1.0.0',
            'host.geo.location': {
                'lat': config_dict['latitude'],
                'lon': config_dict['longitude']
            } if 'latitude' in config_dict else None,
            'host.architecture': system_info['arch'],
            'host.os.name': system_info['os_name'],
            'host.hostname': socket.gethostname(),
            'tags': config.get(CONF_TAGS)
        }

        self._publish_frequency = config.get(CONF_PUBLISH_FREQUENCY)
        self._only_publish_changed = config.get(CONF_ONLY_PUBLISH_CHANGED)

        excluded = config.get(CONF_EXCLUDE)
        self._excluded_domains = excluded.get(CONF_DOMAINS)
        self._excluded_entities = excluded.get(CONF_ENTITIES)

        if self._excluded_domains:
            _LOGGER.debug("Excluding the following domains: %s",
                          str(self._excluded_domains))

        if self._excluded_entities:
            _LOGGER.debug("Excluding the following entities: %s",
                          str(self._excluded_entities))

        self.publish_queue = Queue()
        self._last_publish_time = None

        self._start_publish_timer()

    def queue_size(self):
        """Returns the approximate queue size"""
        return self.publish_queue.qsize()

    def last_publish_time(self):
        """Returns the last publish time"""
        return self._last_publish_time

    def enqueue_state(self, entry):
        """queues up the provided state change"""
        state = entry['state']
        domain = state.domain
        entity_id = state.entity_id

        if domain in self._excluded_domains:
            _LOGGER.debug(
                "Skipping %s: it belongs to an excluded domain", entity_id)
            return

        if entity_id in self._excluded_entities:
            _LOGGER.debug(
                "Skipping %s: this entity is explicitly excluded", entity_id)
            return

        self.publish_queue.put(entry)

    async def async_do_publish(self):
        "Publishes all queued documents to the Elasticsearch cluster"
        from elasticsearch import ElasticsearchException
        from elasticsearch.helpers import bulk

        if self.publish_queue.empty():
            _LOGGER.debug("Skipping publish because queue is empty")
            return

        _LOGGER.debug("Collecting queued documents for publish")
        actions = []
        entity_counts = {}
        self._last_publish_time = datetime.now()

        while not self.publish_queue.empty():
            entry = self.publish_queue.get()

            key = entry["state"].entity_id

            entity_counts[key] = 1 if key not in entity_counts else entity_counts[key] + 1
            actions.append(self._state_to_bulk_action(
                entry["state"], entry["event"].time_fired))

        if not self._only_publish_changed:
            all_states = self._hass.states.async_all()
            for state in all_states:
                if (state.domain in self._excluded_domains
                        or state.entity_id in self._excluded_entities):
                    continue

                if state.entity_id not in entity_counts:
                    actions.append(self._state_to_bulk_action(
                        state, self._last_publish_time))

        _LOGGER.info("Publishing %i documents to Elasticsearch", len(actions))

        try:
            await self._hass.async_add_executor_job(self.bulk_sync_wrapper, actions)
        except ElasticsearchException as err:
            _LOGGER.exception(
                "Error publishing documents to Elasticsearch: %s", err)
        return

    def bulk_sync_wrapper(self, actions):
        from elasticsearch import ElasticsearchException
        from elasticsearch.helpers import bulk

        try:
            bulk_response = bulk(self._gateway.get_sync_client(), actions)
            _LOGGER.debug("Elasticsearch bulk response: %s",
                          str(bulk_response))
            _LOGGER.info("Publish Succeeded")
        except ElasticsearchException as err:
            _LOGGER.exception(
                "Error publishing documents to Elasticsearch: %s", err)

    def _state_to_bulk_action(self, state, time):
        """Creates a bulk action from the given state object"""
        try:
            _state = state_helper.state_as_number(state)
            if not is_valid_number(_state):
                _state = state.state
        except ValueError:
            _state = state.state

        if time.tzinfo is None:
            time_tz = time.astimezone(utc)
        else:
            time_tz = time

        orig_attributes = dict(state.attributes)
        attributes = dict()
        for orig_key, orig_value in orig_attributes.items():
            # ES will attempt to expand any attribute keys which contain a ".",
            # so we replace them with an "_" instead.
            # https://github.com/legrego/homeassistant-elasticsearch/issues/92
            key = str.replace(orig_key, ".", "_")
            value = orig_value

            # coerce set to list. ES does not handle sets natively
            if isinstance(orig_value, set):
                value = list(orig_value)

            # if the list/tuple contains simple strings, numbers, or booleans, then we should
            # index the contents as an actual list. Otherwise, we need to serialize
            # the contents so that we can respect the index mapping
            # (Arrays of objects cannot be indexed as-is)
            if value and isinstance(value, (list, tuple)):
                should_serialize = isinstance(
                    value[0], (tuple, dict, set, list))
            else:
                should_serialize = isinstance(value, dict)

            attributes[key] = self._serializer.dumps(
                value) if should_serialize else value

        document_body = {
            'hass.domain': state.domain,
            'hass.object_id': state.object_id,
            'hass.object_id_lower': state.object_id.lower(),
            'hass.entity_id': state.entity_id,
            'hass.entity_id_lower': state.entity_id.lower(),
            'hass.attributes': attributes,
            'hass.value': _state,
            '@timestamp': time_tz
        }

        document_body.update(self._static_doc_properties)

        if ('latitude' in document_body['hass.attributes']
                and 'longitude' in document_body['hass.attributes']):
            document_body['hass.geo.location'] = {
                'lat': document_body['hass.attributes']['latitude'],
                'lon': document_body['hass.attributes']['longitude']
            }

        es_version = self._gateway.es_version
        if es_version.major == 6:
            return {
                "_op_type": "index",
                "_index": self._index_alias,
                "_type": "doc",
                "_source": document_body
            }
        return {
            "_op_type": "index",
            "_index": self._index_alias,
            "_source": document_body
        }

    def _start_publish_timer(self):
        """Initialize the publish timer"""
        asyncio.ensure_future(self._publish_queue_timer())

    def _should_publish(self):
        """Determines if now is a good time to publish documents"""
        if self.publish_queue.empty():
            _LOGGER.debug("should_publish: queue is empty")
            return False

        return True

    async def _publish_queue_timer(self):
        """The publish queue timer"""
        _LOGGER.debug("Starting publish timer: executes every %i seconds.",
                      self._publish_frequency)
        while True:
            try:
                if self._should_publish():
                    await self.async_do_publish()
                else:
                    _LOGGER.debug("Nothing to publish")
            finally:
                await asyncio.sleep(self._publish_frequency)


def get_serializer():
    """Gets the custom JSON serializer"""
    from elasticsearch.serializer import JSONSerializer

    class SetEncoder(JSONSerializer):
        """JSONSerializer which serializes sets to lists"""

        def default(self, data):
            """entry point"""
            if isinstance(data, set):
                return list(data)
            return JSONSerializer.default(self, data)

    return SetEncoder()

def is_valid_number(number):
    """Determines if the passed number is valid for Elasticsearch"""
    is_infinity = math.isinf(number)
    is_nan = number != number  # pylint: disable=comparison-with-itself
    return not is_infinity and not is_nan


def extract_port_from_name(name, default_port):
    """
    extractPortFromName takes a string in the form `id:port` and returns the ID and the port
    If there's no `:`, the default port is returned
    """
    idx = name.rfind(":")
    if idx >= 0:
        return name[:idx], name[idx+1:]

    return name, default_port


def decode_cloud_id(cloud_id):
    """Decodes the cloud id"""

    # Logic adapted from https://github.com/elastic/beats/blob/6.5/libbeat/cloudid/cloudid.go

    this_cloud_id = cloud_id

    # 1. Ignore anything before `:`
    idx = this_cloud_id.rfind(':')
    if idx >= 0:
        this_cloud_id = this_cloud_id[idx+1:]

    # 2. base64 decode
    try:
        this_cloud_id = base64.b64decode(this_cloud_id).decode('utf-8')
    except binascii.Error:
        raise Exception(
            "Invalid cloud_id. Error base64 decoding {}".format(cloud_id))

    # 3. separate based on `$`
    words = this_cloud_id.split("$")
    if len(words) < 3:
        raise Exception(
            "Invalid cloud_id: expected at least 3 parts in {}".format(cloud_id))

    # 4. extract port from the ES host, or use 443 as the default
    host, port = extract_port_from_name(words[0], 443)
    es_id, es_port = extract_port_from_name(words[1], port)

    # 5. form the URLs
    es_url = "https://{}.{}:{}".format(es_id, host, es_port)

    return es_url

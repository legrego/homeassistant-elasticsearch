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
import voluptuous as vol
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

REQUIREMENTS = ['elasticsearch==6.3.1']

CONF_INDEX_FORMAT = 'index_format'
CONF_PUBLISH_FREQUENCY = 'publish_frequency'
CONF_ONLY_PUBLISH_CHANGED = 'only_publish_changed'
CONF_REQUEST_ROLLOVER_FREQUENCY = 'request_rollover_frequency'
CONF_ROLLOVER_AGE = 'rollover_max_age'
CONF_ROLLOVER_DOCS = 'rollover_max_docs'
CONF_ROLLOVER_SIZE = 'rollover_max_size'
CONF_SSL_CA_PATH = 'ssl_ca_path'
CONF_CLOUD_ID = 'cloud_id'

CONF_TAGS = 'tags'

ELASTIC_COMPONENTS = [
    'sensor'
]

_LOGGER = logging.getLogger(__name__)

ONE_MINUTE = 60
ONE_HOUR = 60 * 60

VERSION_SUFFIX = "-v2"
INDEX_TEMPLATE_NAME = "hass-index-template" + VERSION_SUFFIX

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.All(
        vol.Schema({
            vol.Exclusive(CONF_URL, 'url or cloud_id'): cv.url,
            vol.Exclusive(CONF_CLOUD_ID, 'url or cloud_id'): cv.string,
            vol.Optional(CONF_USERNAME): cv.string,
            vol.Optional(CONF_PASSWORD): cv.string,
            vol.Optional(CONF_INDEX_FORMAT, default='hass-events'): cv.string,
            vol.Optional(CONF_ALIAS, default='active-hass-index'): cv.string,
            vol.Optional(CONF_PUBLISH_FREQUENCY, default=ONE_MINUTE): cv.positive_int,
            vol.Optional(CONF_ONLY_PUBLISH_CHANGED, default=False): cv.boolean,
            vol.Optional(CONF_REQUEST_ROLLOVER_FREQUENCY, default=ONE_HOUR): cv.positive_int,
            vol.Optional(CONF_ROLLOVER_AGE): cv.string,
            vol.Optional(CONF_ROLLOVER_DOCS): cv.positive_int,
            vol.Optional(CONF_ROLLOVER_SIZE, default='30gb'): cv.string,
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


@asyncio.coroutine
async def async_setup(hass, config):
    """Setup the Elasticsearch component."""
    conf = config[DATA_ELASTICSEARCH]

    hass.data[DOMAIN] = {}

    _LOGGER.debug("Creating ES gateway")
    gateway = ElasticsearchGateway(hass, conf)
    hass.data[DOMAIN]['gateway'] = gateway

    _LOGGER.debug("Creating document publisher")
    system_info = await hass.helpers.system_info.async_get_system_info()
    publisher = DocumentPublisher(conf, gateway, hass, system_info)
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

    for component in ELASTIC_COMPONENTS:
        discovery.load_platform(hass, component, DOMAIN, {}, config)

    hass.services.async_register(DOMAIN, 'publish_events', service_handler.publish_events)

    _LOGGER.info("Elastic component fully initialized")
    return True

class ServiceHandler: # pylint: disable=unused-variable
    """Handles calls to exposed services"""

    def __init__(self, publisher):
        """Initializes the service handler"""
        self._publisher = publisher

    def publish_events(self, service):
        """Publishes all queued events to Elasticsearch"""
        self._publisher.do_publish()

class ElasticsearchGateway: # pylint: disable=unused-variable
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

    def get_client(self):
        """Returns the underlying ES Client"""
        return self.client

    def _create_es_client(self):
        """Constructs an instance of the Elasticsearch client"""
        import elasticsearch

        use_basic_auth = self._username is not None and self._password is not None

        serializer = self._get_serializer()

        if use_basic_auth:
            auth = (self._username, self._password)
            return elasticsearch.Elasticsearch(
                [self._url],
                http_auth=auth,
                serializer=serializer,
                verify_certs=self._verify_certs,
                ca_certs=self._ca_certs
            )

        return elasticsearch.Elasticsearch(
            [self._url],
            serializer=serializer,
            verify_certs=self._verify_certs,
            ca_certs=self._ca_certs
        )

    def _get_serializer(self):
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


class DocumentPublisher: # pylint: disable=unused-variable
    """Publishes documents to Elasticsearch"""

    def __init__(self, config, gateway, hass, system_info):
        """Initialize the publisher"""
        self._gateway = gateway
        self._hass = hass
        self._index_format = config.get(CONF_INDEX_FORMAT) + VERSION_SUFFIX
        self._index_alias = config.get(CONF_ALIAS) + VERSION_SUFFIX

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
            _LOGGER.debug("Excluding the following domains: %s", str(self._excluded_domains))

        if self._excluded_entities:
            _LOGGER.debug("Excluding the following entities: %s", str(self._excluded_entities))

        self._rollover_frequency = config.get(CONF_REQUEST_ROLLOVER_FREQUENCY)
        self._rollover_conditions = {
            "max_age": config.get(CONF_ROLLOVER_AGE),
            "max_docs": config.get(CONF_ROLLOVER_DOCS),
            "max_size": config.get(CONF_ROLLOVER_SIZE)
        }
        if self._rollover_conditions["max_age"] is None:
            del self._rollover_conditions["max_age"]
        if self._rollover_conditions["max_docs"] is None:
            del self._rollover_conditions["max_docs"]

        self.publish_queue = Queue()
        self._last_publish_time = None

        self._create_index_template()
        self._start_publish_timer()
        self._start_rollover_timer()

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
            _LOGGER.debug("Skipping %s: it belongs to an excluded domain", entity_id)
            return

        if entity_id in self._excluded_entities:
            _LOGGER.debug("Skipping %s: this entity is explicitly excluded", entity_id)
            return

        self.publish_queue.put(entry)

    def do_publish(self):
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
            actions.append(self._state_to_bulk_action(entry["state"], entry["event"].time_fired))

        if not self._only_publish_changed:
            all_states = self._hass.states.async_all()
            for state in all_states:
                if (state.domain in self._excluded_domains
                        or state.entity_id in self._excluded_entities):
                    continue

                if state.entity_id not in entity_counts:
                    actions.append(self._state_to_bulk_action(state, self._last_publish_time))

        _LOGGER.info("Publishing %i documents to Elasticsearch", len(actions))

        try:
            bulk_response = bulk(self._gateway.get_client(), actions)
            _LOGGER.debug("Elasticsearch bulk response: %s", str(bulk_response))
            _LOGGER.info("Publish Succeeded")
        except ElasticsearchException as err:
            _LOGGER.exception("Error publishing documents to Elasticsearch: %s", err)
        return

    def _state_to_bulk_action(self, state, time):
        """Creates a bulk action from the given state object"""
        try:
            _state = state_helper.state_as_number(state)
        except ValueError:
            _state = state.state

        document_body = {
            'hass.domain': state.domain,
            'hass.object_id': state.object_id,
            'hass.entity_id': state.entity_id,
            'hass.attributes': dict(state.attributes),
            'hass.value': _state,
            '@timestamp': time
        }

        document_body.update(self._static_doc_properties)

        if ('latitude' in document_body['hass.attributes']
                and 'longitude' in document_body['hass.attributes']):
            document_body['hass.geo.location'] = {
                'lat': document_body['hass.attributes']['latitude'],
                'lon': document_body['hass.attributes']['longitude']
            }

        return {
            "_op_type": "index",
            "_index": self._index_alias,
            "_type": "doc",
            "_source": document_body
        }

    def _start_publish_timer(self):
        """Initialize the publish timer"""
        asyncio.ensure_future(self._publish_queue_timer())

    def _start_rollover_timer(self):
        """Initialize the rollover timer"""
        asyncio.ensure_future(self._rollover_timer())

    def _do_rollover(self):
        """Initiates a Rollover request to the Elasticsearch cluster"""
        import elasticsearch

        _LOGGER.debug("Performing index rollover")
        try:
            rollover_response = self._gateway.get_client().indices.rollover(
                alias=self._index_alias,
                body={
                    "conditions": self._rollover_conditions
                }
            )

            _LOGGER.debug("Elasticsearch rollover response: %s", str(rollover_response))
            _LOGGER.info("Rollover Succeeded")
        except elasticsearch.ElasticsearchException as err:
            _LOGGER.exception("Error performing rollover: %s", err)

    def _should_publish(self):
        """Determines if now is a good time to publish documents"""
        if self.publish_queue.empty():
            _LOGGER.debug("should_publish: queue is empty")
            return False

        return True

    @asyncio.coroutine
    def _publish_queue_timer(self):
        """The publish queue timer"""
        _LOGGER.debug("Starting publish timer: executes every %i seconds.",
                      self._publish_frequency)
        while True:
            try:
                if self._should_publish():
                    self.do_publish()
                else:
                    _LOGGER.debug("Nothing to publish")
            finally:
                yield from asyncio.sleep(self._publish_frequency)

    @asyncio.coroutine
    def _rollover_timer(self):
        """The rollover timer"""
        _LOGGER.debug("Starting rollover timer: executes every %i seconds.",
                      self._rollover_frequency)
        while True:
            try:
                self._do_rollover()
            finally:
                yield from asyncio.sleep(self._rollover_frequency)

    def _create_index_template(self):
        """
        Initializes the Elasticsearch cluster with an index template, initial index, and alias.
        """
        import elasticsearch

        client = self._gateway.get_client()

        with open(os.path.join(os.path.dirname(__file__), 'index_mapping.json')) as json_file:
            mapping = json.load(json_file)

        if not client.indices.exists_template(name=INDEX_TEMPLATE_NAME):
            _LOGGER.debug("Creating index template")
            try:
                client.indices.put_template(
                    name=INDEX_TEMPLATE_NAME,
                    body={
                        "index_patterns": [self._index_format + "*"],
                        "settings": {
                            "number_of_shards": 1
                        },
                        "mappings": {
                            "doc": mapping
                        },
                        "aliases": {
                            "all-hass-events": {}
                        }
                    }
                )
            except elasticsearch.ElasticsearchException as err:
                _LOGGER.exception("Error creating index template: %s", err)

        if not client.indices.exists_alias(name=self._index_alias):
            _LOGGER.debug("Creating initial index and alias")
            try:
                client.indices.create(index=self._index_format + "-000001", body={
                    "aliases": {
                        self._index_alias: {}
                    }
                })
            except elasticsearch.ElasticsearchException as err:
                _LOGGER.exception("Error creating initial index/alias: %s", err)

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
        raise Exception("Invalid cloud_id. Error base64 decoding {}".format(cloud_id))

    # 3. separate based on `$`
    words = this_cloud_id.split("$")
    if len(words) < 3:
        raise Exception("Invalid cloud_id: expected at least 3 parts in {}".format(cloud_id))

    # 4. extract port from the ES host, or use 443 as the default
    host, port = extract_port_from_name(words[0], 443)
    es_id, es_port = extract_port_from_name(words[1], port)

    # 5. form the URLs
    es_url = "https://{}.{}:{}".format(es_id, host, es_port)

    return es_url

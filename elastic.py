"""
Support for sending event data to an Elasticsearch cluster
"""
import logging
from queue import Queue
from datetime import (datetime)
import asyncio
import voluptuous as vol
from homeassistant.const import (
    CONF_URL, CONF_USERNAME, CONF_PASSWORD, CONF_ALIAS, EVENT_STATE_CHANGED)
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
CONF_REQUEST_ROLLOVER_FREQUENCY = 'request_rollover_frequency'
CONF_ROLLOVER_AGE = 'rollover_max_age'
CONF_ROLLOVER_DOCS = 'rollover_max_docs'
CONF_ROLLOVER_SIZE = 'rollover_max_size'

ELASTIC_COMPONENTS = [
    'sensor'
]

_LOGGER = logging.getLogger(__name__)

ONE_MINUTE = 60
ONE_HOUR = 60 * 60

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_URL): cv.url,
        vol.Optional(CONF_USERNAME): cv.string,
        vol.Optional(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_INDEX_FORMAT, default='hass-events'): cv.string,
        vol.Optional(CONF_ALIAS, default='active-hass-index'): cv.string,
        vol.Optional(CONF_PUBLISH_FREQUENCY, default=ONE_MINUTE): cv.positive_int,
        vol.Optional(CONF_REQUEST_ROLLOVER_FREQUENCY, default=ONE_HOUR): cv.positive_int,
        vol.Optional(CONF_ROLLOVER_AGE, default='60d'): cv.string,
        vol.Optional(CONF_ROLLOVER_DOCS, default=1000000): cv.positive_int,
        vol.Optional(CONF_ROLLOVER_SIZE, default='5gb'): cv.string
    }),
}, extra=vol.ALLOW_EXTRA)


@asyncio.coroutine
def async_setup(hass, config):
    """Setup the Elasticsearch component."""
    conf = config[DATA_ELASTICSEARCH]

    hass.data[DOMAIN] = {}

    _LOGGER.debug("Creating ES gateway")
    gateway = ElasticsearchGateway(hass, conf)
    hass.data[DOMAIN]['gateway'] = gateway

    _LOGGER.debug("Creating document publisher")
    publisher = DocumentPublisher(conf, gateway)
    hass.data[DOMAIN]['publisher'] = publisher

    _LOGGER.debug("Creating service handler")
    service_handler = ServiceHandler(publisher)

    def elastic_event_listener(event):
        """Listen for new messages on the bus and queue them for send."""
        state = event.data.get('new_state')
        if state is None:
            return
        try:
            _state = state_helper.state_as_number(state)
        except ValueError:
            _state = state.state

        document_body = {
            'domain': state.domain,
            'entity_id': state.object_id,
            'attributes': dict(state.attributes),
            'time': event.time_fired,
            'value': _state,
        }

        publisher.write_document(document_body)

        return

    hass.bus.async_listen(EVENT_STATE_CHANGED, elastic_event_listener)

    for component in ELASTIC_COMPONENTS:
        discovery.load_platform(hass, component, DOMAIN, {}, config)

    hass.services.async_register(DOMAIN, 'publish_events', service_handler.publish_events)

    _LOGGER.debug("Elastic component fully initialized")
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

        _LOGGER.debug("Creating Elasticsearch client")
        self.client = self._create_es_client()

    def get_client(self):
        """Returns the underlying ES Client"""
        return self.client

    def _create_es_client(self):
        """Constructs an instance of the Elasticsearch client"""
        import elasticsearch

        use_basic_auth = self._username is not None and self._password is not None

        if use_basic_auth:
            auth = (self._username, self._password)
            return elasticsearch.Elasticsearch([self._url], http_auth=auth)

        return elasticsearch.Elasticsearch([self._url])


class DocumentPublisher: # pylint: disable=unused-variable
    """Publishes documents to Elasticsearch"""

    def __init__(self, config, gateway):
        """Initialize the publisher"""
        self._gateway = gateway
        self._index_format = config.get(CONF_INDEX_FORMAT)
        self._index_alias = config.get(CONF_ALIAS)
        self._publish_frequency = config.get(CONF_PUBLISH_FREQUENCY)

        self._rollover_frequency = config.get(CONF_REQUEST_ROLLOVER_FREQUENCY)
        self._rollover_conditions = {
            "max_age": config.get(CONF_ROLLOVER_AGE),
            "max_docs": config.get(CONF_ROLLOVER_DOCS),
            "max_size": config.get(CONF_ROLLOVER_SIZE)
        }

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

    def write_document(self, document):
        """Queue a document for publish to the cluster"""
        self.publish_queue.put({
            "_op_type": "index",
            "_index": self._index_alias,
            "_type": "doc",
            "_source": document
        })

    def do_publish(self):
        "Publishes all queued documents to the Elasticsearch cluster"
        from elasticsearch import ElasticsearchException
        from elasticsearch.helpers import bulk

        if self.publish_queue.empty():
            _LOGGER.debug("Skipping publish because queue is empty")
            return

        _LOGGER.debug("Collecting queued documents for publish")
        actions = []
        while not self.publish_queue.empty():
            doc = self.publish_queue.get()
            actions.append(doc)

        self._last_publish_time = datetime.now()
        _LOGGER.info("Publishing %i documents to Elasticsearch", len(actions))

        try:
            bulk_response = bulk(self._gateway.get_client(), actions)
            _LOGGER.debug("Elasticsearch bulk response: %s", str(bulk_response))
            _LOGGER.info("Publish Succeeded")
        except ElasticsearchException as err:
            _LOGGER.exception("Error publishing documents to Elasticsearch: %s", err)
        return

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

        if not client.indices.exists_template(name="hass-index-template"):
            _LOGGER.debug("Creating index template")
            try:
                client.indices.put_template(
                    name="hass-index-template",
                    body={
                        "index_patterns": [self._index_format + "*"],
                        "settings": {
                            "number_of_shards": 1
                        },
                        "mappings": {
                            "doc": {
                                "dynamic": 'strict',
                                "properties": {
                                    "domain": {"type": 'keyword'},
                                    "entity_id": {"type": 'keyword'},
                                    "attributes": {
                                        "type": 'object',
                                        "dynamic": True
                                    },
                                    "time": {"type": 'date'},
                                    "value": {
                                        "type": 'text',
                                        "fields": {
                                            "keyword": {
                                                "type": "keyword",
                                                "ignore_above": 2048
                                            },
                                            "float": {
                                                "type": "float",
                                                "ignore_malformed": true
                                            }
                                        }
                                    }
                                }
                            }
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
                client.indices.create(index=self._index_format + "-00001", body={
                    "aliases": {
                        self._index_alias: {}
                    }
                })
            except elasticsearch.ElasticsearchException as err:
                _LOGGER.exception("Error creating initial index/alias: %s", err)

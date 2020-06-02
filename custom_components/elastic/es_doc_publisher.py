"""Publishes documents to Elasticsearch"""
import socket
import asyncio
from queue import Queue
from datetime import (datetime)
import math
from pytz import utc
from homeassistant.const import (CONF_DOMAINS, CONF_ENTITIES, CONF_EXCLUDE)
from homeassistant.helpers import (
    state as state_helper
)
from .const import (
    CONF_TAGS, CONF_PUBLISH_FREQUENCY, CONF_ONLY_PUBLISH_CHANGED
)

from .logger import LOGGER

from .es_serializer import get_serializer

class DocumentPublisher:
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
            LOGGER.debug("Excluding the following domains: %s",
                         str(self._excluded_domains))

        if self._excluded_entities:
            LOGGER.debug("Excluding the following entities: %s",
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
            LOGGER.debug(
                "Skipping %s: it belongs to an excluded domain", entity_id)
            return

        if entity_id in self._excluded_entities:
            LOGGER.debug(
                "Skipping %s: this entity is explicitly excluded", entity_id)
            return

        self.publish_queue.put(entry)

    async def async_do_publish(self):
        "Publishes all queued documents to the Elasticsearch cluster"
        from elasticsearch import ElasticsearchException

        if self.publish_queue.empty():
            LOGGER.debug("Skipping publish because queue is empty")
            return

        LOGGER.debug("Collecting queued documents for publish")
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

        LOGGER.info("Publishing %i documents to Elasticsearch", len(actions))

        try:
            await self._hass.async_add_executor_job(self.bulk_sync_wrapper, actions)
        except ElasticsearchException as err:
            LOGGER.exception(
                "Error publishing documents to Elasticsearch: %s", err)
        return

    def bulk_sync_wrapper(self, actions):
        """
        Wrapper to publish events.
        Workaround for elasticsearch_async not supporting bulk operations
        """
        from elasticsearch import ElasticsearchException
        from elasticsearch.helpers import bulk

        try:
            bulk_response = bulk(self._gateway.get_sync_client(), actions)
            LOGGER.debug("Elasticsearch bulk response: %s",
                         str(bulk_response))
            LOGGER.info("Publish Succeeded")
        except ElasticsearchException as err:
            LOGGER.exception(
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

            # Skip any attributes with empty keys. Elasticsearch cannot index these.
            # https://github.com/legrego/homeassistant-elasticsearch/issues/96
            if not key:
                LOGGER.warning(
                    "Not publishing keyless attribute from entity [%s].",
                    state.entity_id
                )
                continue

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
            LOGGER.debug("should_publish: queue is empty")
            return False

        return True

    async def _publish_queue_timer(self):
        """The publish queue timer"""
        LOGGER.debug("Starting publish timer: executes every %i seconds.",
                     self._publish_frequency)
        while True:
            try:
                if self._should_publish():
                    await self.async_do_publish()
                else:
                    LOGGER.debug("Nothing to publish")
            finally:
                await asyncio.sleep(self._publish_frequency)


def is_valid_number(number):
    """Determines if the passed number is valid for Elasticsearch"""
    is_infinity = math.isinf(number)
    is_nan = number != number  # pylint: disable=comparison-with-itself
    return not is_infinity and not is_nan

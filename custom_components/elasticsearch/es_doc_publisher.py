"""Publishes documents to Elasticsearch"""
import asyncio
import math
from datetime import datetime
from queue import Queue

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.helpers import state as state_helper
from homeassistant.helpers.typing import HomeAssistantType, StateType
from pytz import utc

from .const import (
    CONF_EXCLUDED_DOMAINS,
    CONF_EXCLUDED_ENTITIES,
    CONF_ONLY_PUBLISH_CHANGED,
    CONF_PUBLISH_ENABLED,
    CONF_PUBLISH_FREQUENCY,
    CONF_TAGS,
)
from .es_serializer import get_serializer
from .logger import LOGGER
from .system_info import async_get_system_info


class DocumentPublisher:
    """Publishes documents to Elasticsearch"""

    def __init__(self, config, gateway, index_manager, hass: HomeAssistantType):
        """Initialize the publisher"""

        self.publish_enabled = config.get(CONF_PUBLISH_ENABLED)
        self.publish_active = False
        self.remove_state_change_listener = None

        if not self.publish_enabled:
            LOGGER.debug("Not initializing document publisher")
            return

        self._gateway = gateway
        self._hass = hass

        self._index_alias = index_manager.index_alias

        self._serializer = get_serializer()

        self._static_doc_properties = None

        self._publish_frequency = config.get(CONF_PUBLISH_FREQUENCY)
        self._only_publish_changed = config.get(CONF_ONLY_PUBLISH_CHANGED)
        self._tags = config.get(CONF_TAGS)

        self._excluded_domains = config.get(CONF_EXCLUDED_DOMAINS)
        self._excluded_entities = config.get(CONF_EXCLUDED_ENTITIES)

        if self._excluded_domains:
            LOGGER.debug(
                "Excluding the following domains: %s", str(self._excluded_domains)
            )

        if self._excluded_entities:
            LOGGER.debug(
                "Excluding the following entities: %s", str(self._excluded_entities)
            )

        def elastic_event_listener(event):
            """Listen for new messages on the bus and queue them for send."""
            state = event.data.get("new_state")
            if state is None:
                return

            self.enqueue_state({"state": state, "event": event})

        self.remove_state_change_listener = hass.bus.async_listen(
            EVENT_STATE_CHANGED, elastic_event_listener
        )

        self.publish_queue = Queue()
        self._last_publish_time = None

        self._start_publish_timer()

    async def async_init(self):
        if not self.publish_enabled:
            return
        config_dict = self._hass.config.as_dict()
        system_info = await async_get_system_info(self._hass)
        self._static_doc_properties = {
            "agent.name": config_dict["name"]
            if "name" in config_dict
            else "My Home Assistant",
            "agent.type": "hass",
            "agent.version": system_info["version"],
            "ecs.version": "1.0.0",
            "host.geo.location": {
                "lat": config_dict["latitude"],
                "lon": config_dict["longitude"],
            }
            if "latitude" in config_dict
            else None,
            "host.architecture": system_info["arch"],
            "host.os.name": system_info["os_name"],
            "host.hostname": system_info["hostname"],
            "tags": self._tags,
        }

    async def async_stop_publisher(self):
        LOGGER.debug("Stopping document publisher")
        attempt_flush = self.publish_active

        self.publish_active = False
        if self.remove_state_change_listener:
            self.remove_state_change_listener()
        if attempt_flush:
            LOGGER.debug("Flushing event cache to ES")
            await self.async_do_publish()

    def queue_size(self):
        """Returns the approximate queue size"""
        return self.publish_queue.qsize()

    def last_publish_time(self):
        """Returns the last publish time"""
        return self._last_publish_time

    def enqueue_state(self, entry):
        """queues up the provided state change"""
        state = entry["state"]
        domain = state.domain
        entity_id = state.entity_id

        if not self.publish_enabled:
            LOGGER.warning(
                "Attempted to queue a state change for %s.%s, but publish is not enabled. This is a no-op (and a bug).",
                domain,
                entity_id,
            )
            return

        if domain in self._excluded_domains:
            LOGGER.debug(
                "Skipping %s: it belongs to an excluded domain (%s)", entity_id, domain
            )
            return

        if entity_id in self._excluded_entities:
            LOGGER.debug("Skipping %s: this entity is explicitly excluded", entity_id)
            return

        self.publish_queue.put(entry)

    async def async_do_publish(self):
        "Publishes all queued documents to the Elasticsearch cluster"
        from elasticsearch.exceptions import ElasticsearchException

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

            entity_counts[key] = (
                1 if key not in entity_counts else entity_counts[key] + 1
            )
            actions.append(
                self._state_to_bulk_action(entry["state"], entry["event"].time_fired)
            )

        if not self._only_publish_changed:
            all_states = self._hass.states.async_all()
            for state in all_states:
                if (
                    state.domain in self._excluded_domains
                    or state.entity_id in self._excluded_entities
                ):
                    continue

                if state.entity_id not in entity_counts:
                    actions.append(
                        self._state_to_bulk_action(state, self._last_publish_time)
                    )

        LOGGER.info("Publishing %i documents to Elasticsearch", len(actions))

        try:
            await self.async_bulk_sync_wrapper(actions)
        except ElasticsearchException as err:
            LOGGER.exception("Error publishing documents to Elasticsearch: %s", err)
        return

    async def async_bulk_sync_wrapper(self, actions):
        """
        Wrapper to publish events.
        Workaround for elasticsearch_async not supporting bulk operations
        """
        from elasticsearch.exceptions import ElasticsearchException
        from elasticsearch.helpers import async_bulk

        try:
            bulk_response = await async_bulk(self._gateway.get_client(), actions)
            LOGGER.debug("Elasticsearch bulk response: %s", str(bulk_response))
            LOGGER.info("Publish Succeeded")
        except ElasticsearchException as err:
            LOGGER.exception("Error publishing documents to Elasticsearch: %s", err)

    def _state_to_bulk_action(self, state: StateType, time):
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
                    state.entity_id,
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
                should_serialize = isinstance(value[0], (tuple, dict, set, list))
            else:
                should_serialize = isinstance(value, dict)

            attributes[key] = (
                self._serializer.dumps(value) if should_serialize else value
            )

        document_body = {
            "hass.domain": state.domain,
            "hass.object_id": state.object_id,
            "hass.object_id_lower": state.object_id.lower(),
            "hass.entity_id": state.entity_id,
            "hass.entity_id_lower": state.entity_id.lower(),
            "hass.attributes": attributes,
            "hass.value": _state,
            "@timestamp": time_tz,
        }

        if self._static_doc_properties is None:
            LOGGER.warning(
                "Event for entity [%s] is missing static doc properties. This is a bug.",
                state.entity_id,
            )
        else:
            document_body.update(self._static_doc_properties)

        if (
            "latitude" in document_body["hass.attributes"]
            and "longitude" in document_body["hass.attributes"]
        ):
            document_body["hass.geo.location"] = {
                "lat": document_body["hass.attributes"]["latitude"],
                "lon": document_body["hass.attributes"]["longitude"],
            }

        es_version = self._gateway.es_version
        if es_version.major == 6:
            return {
                "_op_type": "index",
                "_index": self._index_alias,
                "_type": "doc",
                "_source": document_body,
            }
        return {
            "_op_type": "index",
            "_index": self._index_alias,
            "_source": document_body,
        }

    def _start_publish_timer(self):
        """Initialize the publish timer"""
        asyncio.ensure_future(self._publish_queue_timer())
        self.publish_active = True

    def _should_publish(self):
        """Determines if now is a good time to publish documents"""
        if self.publish_queue.empty():
            LOGGER.debug("should_publish: queue is empty")
            return False

        return True

    async def _publish_queue_timer(self):
        """The publish queue timer"""
        LOGGER.debug(
            "Starting publish timer: executes every %i seconds.",
            self._publish_frequency,
        )
        while self.publish_active:
            try:
                if self._should_publish():
                    await self.async_do_publish()
                else:
                    LOGGER.debug("Nothing to publish")
            finally:
                if self.publish_active:
                    await asyncio.sleep(self._publish_frequency)


def is_valid_number(number):
    """Determines if the passed number is valid for Elasticsearch"""
    is_infinity = math.isinf(number)
    is_nan = number != number  # pylint: disable=comparison-with-itself
    return not is_infinity and not is_nan

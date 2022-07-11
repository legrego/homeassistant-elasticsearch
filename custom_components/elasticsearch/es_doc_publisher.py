"""Publishes documents to Elasticsearch"""
import asyncio
import math
from datetime import datetime
from queue import Queue

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.helpers import state as state_helper
from homeassistant.helpers.typing import EventType, HomeAssistantType, StateType
from pytz import utc

from .const import (
    CONF_EXCLUDED_DOMAINS,
    CONF_EXCLUDED_ENTITIES,
    CONF_INCLUDED_DOMAINS,
    CONF_INCLUDED_ENTITIES,
    CONF_PUBLISH_ENABLED,
    CONF_PUBLISH_FREQUENCY,
    CONF_PUBLISH_MODE,
    CONF_TAGS,
    PUBLISH_MODE_ALL,
    PUBLISH_MODE_STATE_CHANGES,
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
        self._publish_mode = config.get(CONF_PUBLISH_MODE)
        self._tags = config.get(CONF_TAGS)

        self._excluded_domains = config.get(CONF_EXCLUDED_DOMAINS)
        self._excluded_entities = config.get(CONF_EXCLUDED_ENTITIES)
        self._included_domains = config.get(CONF_INCLUDED_DOMAINS)
        self._included_entities = config.get(CONF_INCLUDED_ENTITIES)

        if self._excluded_domains:
            LOGGER.debug(
                "Excluding the following domains: %s", str(self._excluded_domains)
            )

        if self._excluded_entities:
            LOGGER.debug(
                "Excluding the following entities: %s", str(self._excluded_entities)
            )

        if self._included_domains:
            LOGGER.debug(
                "Including the following domains: %s", str(self._included_domains)
            )

        if self._included_entities:
            LOGGER.debug(
                "Including the following entities: %s", str(self._included_entities)
            )

        def elastic_event_listener(event: EventType):
            """Listen for new messages on the bus and queue them for send."""
            state: StateType = event.data.get("new_state")
            old_state: StateType = event.data.get("old_state")
            if state is None:
                return

            if (
                old_state is not None
                and self._publish_mode == PUBLISH_MODE_STATE_CHANGES
            ):
                state_value_changed = old_state.state != state.state
                if not state_value_changed:
                    LOGGER.debug(
                        "Excluding event state change for %s because the value did not change",
                        state.entity_id,
                    )
                    return

            self.enqueue_state(state, event)

        self.remove_state_change_listener = hass.bus.async_listen(
            EVENT_STATE_CHANGED, elastic_event_listener
        )

        self.publish_queue = Queue()
        self._last_publish_time = None

    async def async_init(self):
        if not self.publish_enabled:
            LOGGER.debug("Aborting async_init: publish is not enabled")
            return
        config_dict = self._hass.config.as_dict()
        LOGGER.debug("async_init: getting system info")
        system_info = await async_get_system_info(self._hass)
        LOGGER.debug("async_init: initializing static doc properties")
        self._static_doc_properties = {
            "agent.name": config_dict["name"]
            if "name" in config_dict
            else "My Home Assistant",
            "agent.type": "hass",
            "agent.version": system_info["version"]
            if "version" in system_info
            else "UNKNOWN",
            "ecs.version": "1.0.0",
            "host.geo.location": {
                "lat": config_dict["latitude"],
                "lon": config_dict["longitude"],
            }
            if "latitude" in config_dict
            else None,
            "host.architecture": system_info["arch"]
            if "arch" in system_info
            else "UNKNOWN",
            "host.os.name": system_info["os_name"]
            if "os_name" in system_info
            else "UNKNOWN",
            "host.hostname": system_info["hostname"]
            if "hostname" in system_info
            else "UNKNOWN",
            "tags": self._tags,
        }
        LOGGER.debug(
            "async_init: static doc properties: %s", str(self._static_doc_properties)
        )
        LOGGER.debug("async_init: starting publish timer")
        self._start_publish_timer()
        LOGGER.debug("async_init: done")

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

    def enqueue_state(self, state: StateType, event: EventType):
        """queues up the provided state change"""

        domain = state.domain
        entity_id = state.entity_id

        if self._should_publish_state_change(domain, entity_id):
            self.publish_queue.put([state, event])

    async def async_do_publish(self):
        "Publishes all queued documents to the Elasticsearch cluster"
        from elasticsearch.exceptions import ElasticsearchException

        publish_all_states = self._publish_mode == PUBLISH_MODE_ALL

        if self.publish_queue.empty() and not publish_all_states:
            LOGGER.debug("Skipping publish because queue is empty")
            return

        LOGGER.debug("Collecting queued documents for publish")
        actions = []
        entity_counts = {}
        self._last_publish_time = datetime.now()

        while not self.publish_queue.empty():
            [state, event] = self.publish_queue.get()

            key = state.entity_id

            entity_counts[key] = (
                1 if key not in entity_counts else entity_counts[key] + 1
            )
            actions.append(self._state_to_bulk_action(state, event.time_fired))

        if publish_all_states:
            all_states = self._hass.states.async_all()
            for state in all_states:
                if (
                    # Explicitly excluded domains
                    state.domain in self._excluded_domains
                    # Explicitly excluded entities
                    or state.entity_id in self._excluded_entities
                    # If set, only included domains
                    or (
                        self._included_domains
                        and state.domain not in self._included_domains
                    )
                    # If set, only included entities
                    or (
                        self._included_entities
                        and state.entity_id not in self._included_entities
                    )
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

    def _should_publish_state_change(self, domain: str, entity_id: str):
        """Determines if a state change should be published."""
        if not self.publish_enabled:
            LOGGER.warning(
                "Attempted to queue a state change for %s.%s, but publish is not enabled. This is a no-op (and a bug).",
                domain,
                entity_id,
            )
            return False

        # Publish entities if they are explicitly included
        if self._included_entities and entity_id in self._included_entities:
            LOGGER.debug("Including %s: this entity is explicitly included", entity_id)
            return True

        # Skip entities if they are explicitly excluded
        if entity_id in self._excluded_entities:
            LOGGER.debug("Skipping %s: this entity is explicitly excluded", entity_id)
            return False

        # Skip entities belonging to an excluded domain
        if domain in self._excluded_domains:
            LOGGER.debug(
                "Skipping %s: it belongs to an excluded domain (%s)", entity_id, domain
            )
            return False

        # Skip entities if they do not belong to an explicitly included domain.
        # Having 0 explicitly included domains indicates that all domains are allowed.
        if self._included_domains and domain not in self._included_domains:
            LOGGER.debug(
                "Skipping %s: it does not belong to an included domain (%s)",
                entity_id,
                domain,
            )
            return False

        # Skip entities if they are not explicitly included.
        # Having 0 explicitly included entities indicates that all entities are allowed.
        if self._included_entities and entity_id not in self._included_entities:
            LOGGER.debug(
                "Skipping %s: this entity is not specifically included", entity_id
            )
            return False

        return True

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

        return {
            "_op_type": "index",
            "_index": self._index_alias,
            "_source": document_body,
            # If we aren't writing to an alias, that means the
            # Index Template likely wasn't created properly, and we should bail.
            "require_alias": True,
        }

    def _start_publish_timer(self):
        """Initialize the publish timer"""
        asyncio.ensure_future(self._publish_queue_timer())
        self.publish_active = True

    def _should_publish(self):
        """Determines if now is a good time to publish documents"""
        if self.publish_queue.empty():
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

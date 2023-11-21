"""Publishes documents to Elasticsearch."""
import asyncio
import math
import time
from datetime import datetime
from queue import Queue

from homeassistant.const import EVENT_HOMEASSISTANT_CLOSE, EVENT_STATE_CHANGED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import state as state_helper
from homeassistant.helpers.typing import EventType, StateType
from pytz import utc

from custom_components.elasticsearch.entity_details import EntityDetails
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from custom_components.elasticsearch.es_index_manager import IndexManager
from custom_components.elasticsearch.system_info import SystemInfo

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

ALLOWED_ATTRIBUTE_TYPES = tuple | dict | set | list | int | float | bool | str | None

class DocumentPublisher:
    """Publishes documents to Elasticsearch."""

    def __init__(self, config, gateway: ElasticsearchGateway, index_manager: IndexManager, hass: HomeAssistant):
        """Initialize the publisher."""

        self.publish_enabled = config.get(CONF_PUBLISH_ENABLED)
        self.publish_active = False
        self.remove_state_change_listener = None

        if not self.publish_enabled:
            LOGGER.debug("Not initializing document publisher")
            return

        self._gateway: ElasticsearchGateway = gateway
        self._hass: HomeAssistant = hass

        self._index_alias: str = index_manager.index_alias

        self._serializer = get_serializer()

        self._static_doc_properties = None

        self._system_info: SystemInfo = SystemInfo(hass)
        self._entity_details: EntityDetails = EntityDetails(hass)

        self._publish_frequency = config.get(CONF_PUBLISH_FREQUENCY)
        self._publish_mode = config.get(CONF_PUBLISH_MODE)
        self._publish_timer_ref = None
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

        @callback
        def hass_close_event_listener(event: EventType):
            LOGGER.debug("Detected Home Assistant Close Event.")
            self.stop_publisher()

        self.remove_hass_close_listener = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_CLOSE, hass_close_event_listener
        )

        self.publish_queue = Queue()
        self._last_publish_time = None

    async def async_init(self):
        """Perform async initialization for the ES document publisher."""
        if not self.publish_enabled:
            LOGGER.debug("Aborting async_init: publish is not enabled")
            return
        config_dict = self._hass.config.as_dict()
        LOGGER.debug("async_init: getting system info")
        system_info = await self._system_info.async_get_system_info()
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

        await self._entity_details.async_init()

        LOGGER.debug("async_init: starting publish timer")
        self._start_publish_timer()
        LOGGER.debug("async_init: done")

    def stop_publisher(self):
        """Perform shutdown for ES Document Publisher."""
        if not self.publish_active:
            LOGGER.debug("Not stopping document publisher, publish is not active.")
            return

        LOGGER.debug("Stopping document publisher")
        self.publish_active = False
        if self._publish_timer_ref is not None:
            self._publish_timer_ref.cancel()
            self._publish_timer_ref = None

        if self.remove_state_change_listener:
            self.remove_state_change_listener()

        if self.remove_hass_close_listener:
            self.remove_hass_close_listener()

        LOGGER.debug("Publisher stopped")

    def queue_size(self):
        """Return the approximate queue size."""
        return self.publish_queue.qsize()

    def enqueue_state(self, state: StateType, event: EventType):
        """Queue up the provided state change."""

        domain = state.domain
        entity_id = state.entity_id

        if self._should_publish_entity_state(domain, entity_id):
            self.publish_queue.put([state, event])

    async def async_do_publish(self):
        """Publish all queued documents to the Elasticsearch cluster."""
        from elasticsearch7.exceptions import ElasticsearchException

        publish_all_states = self._publish_mode == PUBLISH_MODE_ALL

        if self.publish_queue.empty() and not publish_all_states:
            LOGGER.debug("Skipping publish because queue is empty")
            return

        LOGGER.debug("Collecting queued documents for publish")
        actions = []
        entity_counts = {}
        self._last_publish_time = datetime.now()
        self._entity_details.reset_cache()

        while self.publish_active and not self.publish_queue.empty():
            [state, event] = self.publish_queue.get()

            key = state.entity_id

            entity_counts[key] = (
                1 if key not in entity_counts else entity_counts[key] + 1
            )
            actions.append(self._state_to_bulk_action(state, event.time_fired))

        if publish_all_states:
            all_states = self._hass.states.async_all()
            for state in all_states:
                if state.entity_id not in entity_counts and self._should_publish_entity_state(state.domain, state.entity_id):
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
        """Wrap event publishing.

        Workaround for elasticsearch_async not supporting bulk operations.
        """

        from elasticsearch7.exceptions import ElasticsearchException
        from elasticsearch7.helpers import async_bulk

        try:
            bulk_response = await async_bulk(self._gateway.get_client(), actions)
            LOGGER.debug("Elasticsearch bulk response: %s", str(bulk_response))
            LOGGER.info("Publish Succeeded")
        except ElasticsearchException as err:
            LOGGER.exception("Error publishing documents to Elasticsearch: %s", err)

    def _should_publish_entity_state(self, domain: str, entity_id: str):
        """Determine if a state change should be published."""
        if not self.publish_enabled:
            LOGGER.warning(
                "Attempted to queue a state change for %s.%s, but publish is not enabled. This is a no-op (and a bug).",
                domain,
                entity_id,
            )
            return False

        is_domain_included = self._included_domains and domain in self._included_domains
        is_domain_excluded = self._excluded_domains and domain in self._excluded_domains

        is_entity_included = self._included_entities and entity_id in self._included_entities
        is_entity_excluded = self._excluded_entities and entity_id in self._excluded_entities

        if is_entity_excluded:
            message_suffix = ''
            if is_domain_included:
                message_suffix += ', which supersedes the configured domain inclusion.'

            LOGGER.debug("Skipping %s: this entity is explicitly excluded%s", entity_id, message_suffix)
            return False

        if is_entity_included:
            message_suffix = ''
            if is_domain_excluded:
                message_suffix += ', which supersedes the configured domain exclusion.'

            LOGGER.debug("Including %s: this entity is explicitly included%s", entity_id, message_suffix)
            return True

        if is_domain_included:
            LOGGER.debug("Including %s: this entity belongs to an included domain (%s)", entity_id, domain)
            return True

        if is_domain_excluded:
            LOGGER.debug(
                "Skipping %s: it belongs to an excluded domain (%s)", entity_id, domain
            )
            return False

        # At this point, neither the domain nor entity belong to an explicit include/exclude list.
        return True

    def _state_to_bulk_action(self, state: StateType, time):
        """Create a bulk action from the given state object."""
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
        attributes = {}
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

            if not isinstance(orig_value, ALLOWED_ATTRIBUTE_TYPES):
                LOGGER.debug(
                    "Not publishing attribute [%s] of disallowed type [%s] from entity [%s].",
                    key, type(orig_value), state.entity_id
                )
                continue

            # coerce set to list. ES does not handle sets natively
            if isinstance(orig_value, set):
                value = list(orig_value)

            # if the list/tuple contains simple strings, numbers, or booleans, then we should
            # index the contents as an actual list. Otherwise, we need to serialize
            # the contents so that we can respect the index mapping
            # (Arrays of objects cannot be indexed as-is)
            if value and isinstance(value, list | tuple):
                should_serialize = isinstance(value[0], tuple | dict | set | list)
            else:
                should_serialize = isinstance(value, dict)

            attributes[key] = (
                self._serializer.dumps(value) if should_serialize else value
            )

        device = {}
        entity = {
            "id": state.entity_id,
            "domain": state.domain,
            "attributes": attributes,
            "device": device,
            "value": _state
        }
        document_body = {
            "hass.domain": state.domain,
            "hass.object_id": state.object_id,
            "hass.object_id_lower": state.object_id.lower(),
            "hass.entity_id": state.entity_id,
            "hass.entity_id_lower": state.entity_id.lower(),
            "hass.attributes": attributes,
            "hass.value": _state,
            "@timestamp": time_tz,
            # new values below. Yes this is duplicitive in the short term.
            "hass.entity": entity
        }

        deets = self._entity_details.async_get(state.entity_id)
        if deets is not None:
            if deets.entity.platform:
                entity["platform"] = deets.entity.platform
            if deets.entity.name:
                entity["name"] = deets.entity.name

            if deets.entity_area:
                entity["area"] = {
                    "id": deets.entity_area.id,
                    "name": deets.entity_area.name
                }

            if deets.device:
                device["id"] = deets.device.id
                device["name"] = deets.device.name

            if deets.device_area:
                device["area"] = {
                    "id": deets.device_area.id,
                    "name": deets.device_area.name
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
        """Initialize the publish timer."""
        self._publish_timer_ref = asyncio.ensure_future(self._publish_queue_timer())
        self.publish_active = True


    def _has_entries_to_publish(self):
        """Determine if now is a good time to publish documents."""
        if self.publish_queue.empty():
            LOGGER.debug("Nothing to publish")
            return False

        return True

    async def _publish_queue_timer(self):
        """Publish queue timer."""
        LOGGER.debug(
            "Starting publish timer: executes every %i seconds.",
            self._publish_frequency,
        )
        next_publish = time.monotonic() + self._publish_frequency
        while self.publish_active:
            try:
                can_publish = next_publish <= time.monotonic()
                if can_publish and self._has_entries_to_publish():
                    try:
                        await self.async_do_publish()
                    finally:
                        next_publish = time.monotonic() + self._publish_frequency
            except Exception as err:
                LOGGER.exception("Error during publish queue handling %s", err)
            finally:
                if self.publish_active:
                    await asyncio.sleep(1)


def is_valid_number(number):
    """Determine if the passed number is valid for Elasticsearch."""
    is_infinity = math.isinf(number)
    is_nan = number != number  # pylint: disable=comparison-with-itself
    return not is_infinity and not is_nan

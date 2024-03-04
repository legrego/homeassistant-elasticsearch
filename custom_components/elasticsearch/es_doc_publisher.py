"""Publishes documents to Elasticsearch."""
import asyncio
import time
from datetime import datetime
from queue import Queue

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_CLOSE, EVENT_STATE_CHANGED
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.typing import EventType

from custom_components.elasticsearch.es_doc_creator import DocumentCreator
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from custom_components.elasticsearch.es_index_manager import IndexManager

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
from .logger import LOGGER


class DocumentPublisher:
    """Publishes documents to Elasticsearch."""

    def __init__(self, config, gateway: ElasticsearchGateway, index_manager: IndexManager, hass: HomeAssistant, config_entry: ConfigEntry):
        """Initialize the publisher."""

        self.publish_enabled = config.get(CONF_PUBLISH_ENABLED)
        self.publish_active = False
        self.remove_state_change_listener = None

        if not self.publish_enabled:
            LOGGER.debug("Not initializing document publisher")
            return

        self._config_entry = config_entry

        self._gateway: ElasticsearchGateway = gateway
        self._hass: HomeAssistant = hass

        self._destination_type: str = index_manager.index_mode

        self._index_alias: str = index_manager.index_alias
        self._datastream: str = index_manager.datastream_type + "-" + index_manager.datastream_name + "-" + index_manager.datastream_namespace
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
            state: State = event.data.get("new_state")
            old_state: State = event.data.get("old_state")
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

        self._document_creator = DocumentCreator(hass, config)

        self.publish_queue = Queue[tuple[State, EventType]]()
        self._last_publish_time = None

    async def async_init(self):
        """Perform async initialization for the ES document publisher."""
        if not self.publish_enabled:
            LOGGER.debug("Aborting async_init: publish is not enabled")
            return

        await self._document_creator.async_init()

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

    def enqueue_state(self, state: State, event: EventType):
        """Queue up the provided state change."""

        domain = state.domain
        entity_id = state.entity_id

        if self._should_publish_entity_state(domain, entity_id):
            self.publish_queue.put((state, event))

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

        while self.publish_active and not self.publish_queue.empty():
            (state, event) = self.publish_queue.get()

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

    def _state_to_bulk_action(self, state: State, time: datetime):
        """Create a bulk action from the given state object."""

        document = self._document_creator.state_to_document(state, time)

        # Write to an index or datastream depending on mode
        if self._destination_type == "index":
            return self._create_index_bulk_action(state, time)
        elif self._destination_type == "datastream":
            return self._create_datastream_bulk_action(state, time)

    def _state_to_index_bulk_action(self, state: State, time: datetime):
        """Create a bulk action from the given state object."""

        document = self._document_creator.state_to_document(state, time)

        return {
            "_op_type": "index",
            "_index": self._index_alias,
            "_source": document,
            # If we aren't writing to an alias, that means the
            # Index Template likely wasn't created properly, and we should bail.
            "require_alias": True,
        }

    def _state_to_datastream_bulk_action(self, state: State, time: datetime):
        """Create a bulk action from the given state object."""

        document = self._document_creator.state_to_document(state, time)

        return {
            "_op_type": "index",
            "_index": self._datastream,
            "_source": document
        }

    def _start_publish_timer(self):
        """Initialize the publish timer."""
        if self._config_entry:
            self._publish_timer_ref = self._config_entry.async_create_background_task(self._hass, self._publish_queue_timer(), 'publish_queue_timer')
        else:
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
        from elasticsearch7 import TransportError
        LOGGER.debug(
            "Starting publish timer: executes every %i seconds.",
            self._publish_frequency,
        )
        next_publish = time.monotonic() + self._publish_frequency
        while self.publish_active:
            try:
                can_publish = next_publish <= time.monotonic()
                if can_publish and not self._gateway.active_connection_error and self._has_entries_to_publish():
                    try:
                        await self.async_do_publish()
                    finally:
                        next_publish = time.monotonic() + self._publish_frequency
            except TransportError as transport_error:
                # Do not spam the logs with connection errors if we already know there is a problem.
                if not self._gateway.active_connection_error:
                    LOGGER.exception("Connection error during publish queue handling. Publishing will be paused until connection is fixed. %s", transport_error)
                    self._gateway.notify_of_connection_error()
            except Exception as err:
                LOGGER.exception("Error during publish queue handling %s", err)
            finally:
                if self.publish_active:
                    await asyncio.sleep(1)

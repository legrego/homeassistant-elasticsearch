"""Publishes documents to Elasticsearch."""
import asyncio
import time
from datetime import datetime
from queue import Queue

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_CLOSE, EVENT_STATE_CHANGED
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.typing import EventType

from custom_components.elasticsearch.errors import ElasticException
from custom_components.elasticsearch.es_doc_creator import DocumentCreator
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from custom_components.elasticsearch.es_index_manager import IndexManager

from .const import (
    CONF_EXCLUDED_DOMAINS,
    CONF_EXCLUDED_ENTITIES,
    CONF_INCLUDED_DOMAINS,
    CONF_INCLUDED_ENTITIES,
    CONF_INDEX_MODE,
    CONF_PUBLISH_ENABLED,
    CONF_PUBLISH_FREQUENCY,
    CONF_PUBLISH_MODE,
    CONF_TAGS,
    INDEX_MODE_DATASTREAM,
    INDEX_MODE_LEGACY,
    PUBLISH_MODE_ALL,
    PUBLISH_MODE_STATE_CHANGES,
    PUBLISH_REASON_ATTR_CHANGE,
    PUBLISH_REASON_POLLING,
    PUBLISH_REASON_STATE_CHANGE,
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

        self._destination_type: str = config.get(CONF_INDEX_MODE)

        if self._destination_type == INDEX_MODE_LEGACY:
            self.legacy_index_name: str = index_manager.index_alias
        elif self._destination_type == INDEX_MODE_DATASTREAM:
            self.datastream_type: str = index_manager.datastream_type
            self.datastream_dataset_prefix: str = index_manager.datastream_name_prefix
            self.datastream_namespace: str = index_manager.datastream_namespace

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
            elif old_state is None:
                reason = PUBLISH_REASON_STATE_CHANGE
            else:  # state and old_state are both available
                state_value_changed = old_state.state != state.state

                if (
                    not state_value_changed
                    and self._publish_mode == PUBLISH_MODE_STATE_CHANGES
                ):
                    LOGGER.debug(
                        "Excluding event state change for %s because the value did not change and publish mode is set to state changes only.",
                        state.entity_id,
                    )
                    return

                if state_value_changed:
                    reason = PUBLISH_REASON_STATE_CHANGE
                else:
                    reason = PUBLISH_REASON_ATTR_CHANGE

            self.enqueue_state(state, event, reason)

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

        # Initialize an empty queue
        self.empty_queue()

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

    def enqueue_state(self, state: State, event: EventType, reason: str):
        """Queue up the provided state change."""

        domain = state.domain
        entity_id = state.entity_id

        if self._should_publish_entity_state(domain, entity_id):
            self.publish_queue.put((state, event, reason))

    def empty_queue(self):
        """Empty the publish queue."""
        self.publish_queue = Queue[
            tuple[State, EventType, str]
        ]()  # Initialize a new queue and let the runtime perform garbage collection.

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
            (state, event, reason) = self.publish_queue.get()

            key = state.entity_id

            entity_counts[key] = (
                1 if key not in entity_counts else entity_counts[key] + 1
            )
            actions.append(self._state_to_bulk_action(state, event.time_fired, reason))

        if publish_all_states:
            all_states = self._hass.states.async_all()
            reason = PUBLISH_REASON_POLLING
            for state in all_states:
                if (
                    state.entity_id not in entity_counts
                    and self._should_publish_entity_state(state.domain, state.entity_id)
                ):
                    actions.append(
                        self._state_to_bulk_action(
                            state, self._last_publish_time, reason
                        )
                    )

        # Check for duplicate entries
        # The timestamp and object_id field are combined to generate the Elasticsearch document ID
        # so we check and log warnings for duplicates
        self.check_duplicate_entries(actions)

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

    def _state_to_bulk_action(self, state: State, time: datetime, reason: str):
        """Create a bulk action from the given state object."""

        if self._destination_type == INDEX_MODE_DATASTREAM:
            document = self._document_creator.state_to_document(
                state, time, reason, version=2
            )

            # dataset = homeassistant.device_tracker
            dataset = self.datastream_dataset_prefix + "." + state.domain

            # <type>-<name>-<namespace>
            destination_data_stream = self._sanitize_datastream_name(
                self.datastream_type + "-" + dataset + "-" + self.datastream_namespace
            )

            # Split destination_data_stream on hyphers to get type, name, and namespace from sanitized datastream
            destination_data_stream_parts = destination_data_stream.split("-")
            destination_data_stream_type = destination_data_stream_parts[0]
            destination_data_stream_dataset = destination_data_stream_parts[1]
            destination_data_stream_namespace = destination_data_stream_parts[2]

            # Populate data stream fields on the document
            document["data_stream"] = {
                "dataset": destination_data_stream_dataset,
                "namespace": destination_data_stream_namespace,
                "type": destination_data_stream_type,
            }

            return {
                "_op_type": "create",
                "_index": destination_data_stream,
                "_source": document,
            }

        if self._destination_type == INDEX_MODE_LEGACY:
            document = self._document_creator.state_to_document(
                state, time, reason, version=1
            )

            return {
                "_op_type": "index",
                "_index": self.legacy_index_name,
                "_source": document,
                # If we aren't writing to an alias, that means the
                # Index Template likely wasn't created properly, and we should bail.
                "require_alias": True,
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

    def _sanitize_datastream_name(self, name: str):
        """Sanitize a datastream name."""

        newname = name

        if self._datastream_has_fatal_name(newname):
            raise ElasticException("Invalid / unfixable datastream name: %s", newname)

        if self._datastream_has_unsafe_name(newname):
            LOGGER.debug(
                "Datastream name %s is unsafe, attempting to sanitize.", newname
            )

        # Cannot include \, /, *, ?, ", <, >, |, ` ` (space character), comma, #, :
        invalid_chars = r"\\/*?\":<>|,#+"
        newname = newname.translate(str.maketrans("", "", invalid_chars))
        newname = newname.replace(" ", "_")

        # Cannot be . or ..
        if newname in (".", ".."):
            raise ElasticException("Invalid datastream name: %s", newname)

        while newname.startswith(("-", "_", "+", ".")):
            newname = newname[1::]

        newname = newname.lower()

        newname = newname[:255]

        # if the datastream still has an unsafe name after sanitization, throw an error
        if self._datastream_has_unsafe_name(newname):
            raise ElasticException("Invalid / unfixable datastream name: %s", newname)

        return newname

    def _datastream_has_unsafe_name(self, name: str):
        """Check if a datastream name is unsafe."""

        if self._datastream_has_fatal_name(name):
            return True

        invalid_chars = r"\\/*?\":<>|,#+"
        if name != name.translate(str.maketrans("", "", invalid_chars)):
            return True

        if len(name) > 255:
            return True

        if name.startswith(("-", "_", "+", ".")):
            return True

        if name != name.lower():
            return True

        return False

    def _datastream_has_fatal_name(self, name: str):
        """Check if a datastream name is invalid."""
        if name in (".", ".."):
            return True

        if name == "":
            return True

        return False

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

    def check_duplicate_entries(self, actions: list):
        """Check for duplicate entries in the actions list."""
        duplicate_entries = {}

        for action in actions:
            key = (
                action["_source"]["@timestamp"]
                + "_"
                + action["_source"]["hass.entity"]["domain"]
                + "."
                + action["_source"]["hass.object_id"]
            )

            if key in duplicate_entries:
                old_action = duplicate_entries[key]

                LOGGER.warning(
                    "Duplicate entry #1 found: %s, event source %s: %s",
                    key,
                    old_action["_source"]["event"]["action"],
                    old_action["_source"],
                )
                LOGGER.warning(
                    "Duplicate entry #2 found: %s, event source %s: %s",
                    key,
                    action["_source"]["event"]["action"],
                    action["_source"],
                )

            else:
                duplicate_entries[key] = action

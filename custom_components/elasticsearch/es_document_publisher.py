"""Publishes documents to Elasticsearch."""

import asyncio
import json
import re
import time
import unicodedata
from asyncio import Task
from datetime import UTC, datetime
from functools import lru_cache
from logging import Logger
from math import isinf
from queue import Queue

from elasticsearch.const import (
    StateChangeType,
)
from homeassistant.components.sun import STATE_ABOVE_HORIZON, STATE_BELOW_HORIZON
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_STATE_CHANGED,
    STATE_CLOSED,
    STATE_HOME,
    STATE_LOCKED,
    STATE_NOT_HOME,
    STATE_OFF,
    STATE_ON,
    STATE_OPEN,
    STATE_UNKNOWN,
    STATE_UNLOCKED,
)
from homeassistant.core import Event, HomeAssistant, State
from homeassistant.helpers import state as state_helper
from homeassistant.util import dt as dt_util

from custom_components.elasticsearch.es_gateway import ElasticsearchGateway

from .logger import LOGGER as BASE_LOGGER

ALLOWED_ATTRIBUTE_TYPES = tuple | dict | set | list | int | float | bool | str | None
SKIP_ATTRIBUTES = [
    "friendly_name",
    "entity_picture",
    "icon",
    "device_class",
    "state_class",
    "unit_of_measurement",
]

type EventQueue = Queue[tuple[datetime, State, StateChangeType]]


class Pipeline:
    """Manages the Pipeline lifecycle."""

    class Manager:
        """Manages the Gather -> Format -> Publish pipeline."""

        def __init__(
            self,
            hass: HomeAssistant,
            gateway: ElasticsearchGateway,
            log: Logger = BASE_LOGGER,
            publish_frequency: int = 60,
        ) -> None:
            """Initialize the manager."""
            self._logger = log
            self._hass = hass
            self._gateway = gateway

            # Set _queue to an instance of EventQueue
            self._queue = Queue[tuple[datetime, State, StateChangeType]]()

            self._listener = Pipeline.Listener(
                hass=self._hass,
                log=self._logger,
                queue=self._queue,
            )
            self._poller = Pipeline.Poller(
                hass=self._hass,
                log=self._logger,
                frequency=publish_frequency,
                queue=self._queue,
            )
            self._formatter = Pipeline.Formatter(hass=self._hass, log=self._logger)
            self._publisher = Pipeline.Publisher(hass=self._hass, log=self._logger)

    class Listener:
        """Listens for state changes and queues them for processing."""

        def __init__(
            self,
            hass: HomeAssistant,
            queue: EventQueue,
            log: Logger = BASE_LOGGER,
        ) -> None:
            """Initialize the listener."""
            self._logger: Logger = log
            self._hass: HomeAssistant = hass
            self._queue: EventQueue = queue
            self._bus_listener_cancel = None

        def async_init(self) -> None:
            """Initialize the listener."""

            self._bus_listener_cancel = self._hass.bus.async_listen(
                EVENT_STATE_CHANGED,
                self._handle_event,
            )

        async def _handle_event(self, event: Event) -> None:
            """Listen for new messages on the bus and queue them for send."""
            new_state: State | None = event.data.get("new_state")
            old_state: State | None = event.data.get("old_state")

            if new_state is None:
                return

            reason = (
                StateChangeType.STATE
                if old_state is None or old_state.state != new_state.state
                else StateChangeType.ATTRIBUTE
            )

            self._queue.put((event.time_fired, new_state, reason))

        def stop(self) -> None:
            """Stop the listener."""
            if self._bus_listener_cancel:
                self._bus_listener_cancel()

        def __del__(self) -> None:
            """Clean up the listener."""
            self.stop()

    class Poller:
        """Polls for state changes and queues them for processing."""

        def __init__(
            self,
            hass: HomeAssistant,
            queue: EventQueue,
            log: Logger = BASE_LOGGER,
            frequency: int = 60,
        ) -> None:
            """Initialize the poller."""
            self._logger: Logger = log
            self._hass: HomeAssistant = hass
            self._background_task_cancel: Task | None = None
            self._queue: EventQueue = queue
            self._frequency: int = frequency

            self._next_poll = time.monotonic()

        def async_init(self, config_entry: ConfigEntry) -> None:
            """Initialize the poller."""
            self._background_task_cancel = config_entry.async_create_background_task(
                self._hass,
                self._poll(),
                "publish_queue_timer",
            )

        # Previous Implementation

        #     async def _publish_queue_timer(self) -> None:
        #         """Publish queue timer."""
        #         from elasticsearch7 import TransportError

        #         self._logger.debug(
        #             "Starting publish timer: executes every %i seconds.",
        #             self._publish_frequency,
        #         )

        #         self.publish_active = True

        #         next_publish = time.monotonic() + self._publish_frequency
        #         while self.publish_active:
        #             try:
        #                 time_to_publish = next_publish <= time.monotonic()

        #                 can_publish = self._gateway.active

        #                 should_publish = self._has_entries_to_publish() or self._publish_mode == PUBLISH_MODE_ALL

        #                 if time_to_publish and can_publish and should_publish:
        #                     try:
        #                         await self.async_do_publish()
        #                     finally:
        #                         next_publish = time.monotonic() + self._publish_frequency
        #             except TransportError as transport_error:
        #                 # Do not spam the logs with connection errors if we already know there is a problem.
        #                 if not self._gateway.active:
        #                     self._logger.exception(
        #                         "Connection error during publish queue handling. Publishing will be paused until connection is fixed. %s",
        #                         transport_error,
        #                     )
        #             except Exception as err:
        #                 self._logger.exception("Error during publish queue handling %s", err)
        #             finally:
        #                 if self.publish_active:
        #                     await asyncio.sleep(1)

        def _time_to_poll(self) -> bool:
            """Determine if now is a good time to poll for state changes."""
            return self._next_poll <= time.monotonic()

        def _schedule_next_poll(self) -> None:
            self._next_poll = time.monotonic() + self._frequency

        def _should_stop_polling(self) -> bool:
            """Determine if the poller should stop."""
            return self._hass.is_stopping

        async def _spin(self) -> None:
            """Spin the event loop."""
            await asyncio.sleep(1)

        async def _wait_for_poll(self) -> None:
            """Wait for the next poll time."""
            while not self._time_to_poll():
                await self._spin()
                continue

        async def _poll(self) -> None:
            """Poll for state changes and queue them for send."""

            self._schedule_next_poll()

            while True:
                if self._should_stop_polling():
                    break

                await self._wait_for_poll()

                _next_poll = time.monotonic() + self._frequency

                now: datetime = datetime.now(tz=UTC)

                all_states = self._hass.states.async_all()

                reason = StateChangeType.NO_CHANGE

                [self._queue.put((now, i, reason)) for i in all_states]

    class Formatter:
        """Formats state changes into documents."""

        def __init__(self, hass: HomeAssistant, log: Logger = BASE_LOGGER) -> None:
            """Initialize the formatter."""
            self._logger = log
            self._hass = hass

        @lru_cache(maxsize=4096)
        @staticmethod
        def normalize_attribute_name(attribute_name: str) -> str:
            """Create an ECS-compliant version of the provided attribute name."""
            # Normalize to closest ASCII equivalent where possible
            normalized_string = (
                unicodedata.normalize("NFKD", attribute_name).encode("ascii", "ignore").decode()
            )

            # Replace all non-word characters with an underscore
            replaced_string = re.sub(r"[\W]+", "_", normalized_string)
            # Remove leading and trailing underscores
            replaced_string = re.sub(r"^_+|_+$", "", replaced_string)

            return replaced_string.lower()

        @classmethod
        def is_valid_number(cls, number: float) -> bool:
            """Determine if the passed number is valid for Elasticsearch."""
            is_infinity = isinf(number)
            is_nan = number != number  # pylint: disable=comparison-with-itself  # noqa: PLR0124
            return not is_infinity and not is_nan

        @classmethod
        def try_state_as_number(cls, state: State) -> bool:
            """Try to coerce our state to a number and return true if we can, false if we can't."""

            try:
                cls.state_as_number(state)
            except ValueError:
                return False
            else:
                return True

        @classmethod
        def state_as_number(cls, state: State) -> float:
            """Try to coerce our state to a number."""

            number = state_helper.state_as_number(state)

            if not cls.is_valid_number(number):
                msg = "Could not coerce state to a number."
                raise ValueError(msg)

            return number

        @classmethod
        def try_state_as_boolean(cls, state: State) -> bool:
            """Try to coerce our state to a boolean and return true if we can, false if we can't."""

            try:
                cls.state_as_boolean(state)
            except ValueError:
                return False
            else:
                return True

        @classmethod
        def state_as_boolean(cls, state: State) -> bool:
            """Try to coerce our state to a boolean."""
            # copied from helper state_as_number function
            if state.state in (
                "true",
                STATE_ON,
                STATE_LOCKED,
                STATE_ABOVE_HORIZON,
                STATE_OPEN,
                STATE_HOME,
            ):
                return True
            if state.state in (
                "false",
                STATE_OFF,
                STATE_UNLOCKED,
                STATE_UNKNOWN,
                STATE_BELOW_HORIZON,
                STATE_CLOSED,
                STATE_NOT_HOME,
            ):
                return False

            msg = "Could not coerce state to a boolean."
            raise ValueError(msg)

        @classmethod
        def try_state_as_datetime(cls, state: State) -> bool:
            """Try to coerce our state to a datetime and return True if we can, false if we can't."""

            try:
                cls.state_as_datetime(state)
            except ValueError:
                return False
            else:
                return True

        @classmethod
        def state_as_datetime(cls, state: State) -> datetime:
            """Try to coerce our state to a datetime."""

            return dt_util.parse_datetime(state.state, raise_on_error=True)

        def _state_to_attributes(self, state: State) -> dict:
            """Convert the attributes of a State object into a dictionary compatible with Elasticsearch mappings."""
            orig_attributes = dict(state.attributes)
            attributes = {}
            for orig_key, orig_value in orig_attributes.items():
                # Skip any attributes with invalid keys. Elasticsearch cannot index these.
                # https://github.com/legrego/homeassistant-elasticsearch/issues/96
                # https://github.com/legrego/homeassistant-elasticsearch/issues/192
                if not orig_key or not isinstance(orig_key, str):
                    self._logger.debug(
                        "Not publishing attribute with unsupported key [%s] from entity [%s].",
                        orig_key if isinstance(orig_key, str) else f"type:{type(orig_key)}",
                        state.entity_id,
                    )
                    continue

                if orig_key in SKIP_ATTRIBUTES:
                    continue

                key = self.normalize_attribute_name(orig_key)
                value = orig_value

                # coerce set to list. ES does not handle sets natively
                if not isinstance(orig_value, ALLOWED_ATTRIBUTE_TYPES):
                    self._logger.debug(
                        "Not publishing attribute [%s] of disallowed type [%s] from entity [%s].",
                        key,
                        type(orig_value),
                        state.entity_id,
                    )
                    continue

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

                if key in attributes:
                    self._logger.warning(
                        "Attribute [%s] shares a key [%s] with another attribute for entity [%s]. Discarding previous attribute value.",
                        orig_key,
                        key,
                        state.entity_id,
                    )
                attributes[key] = json.dumps(value) if should_serialize else value

            return attributes

        def state_to_coerced_value(self, state: State) -> dict:
            """Coerce the state value into a dictionary of possible types."""
            value = state.state

            if not isinstance(value, str):
                return {"string": value}

            if self.try_state_as_boolean(state):
                return {"boolean": self.state_as_boolean(state)}

            elif self.try_state_as_number(state):
                return {"float": self.state_as_number(state)}

            elif self.try_state_as_datetime(state):
                _temp_state = self.state_as_datetime(state)
                return {
                    "datetime": _temp_state.isoformat(),
                    "date": _temp_state.date().isoformat(),
                    "time": _temp_state.time().isoformat(),
                }

            else:
                return {"string": value}

        def format(self, time: datetime, state: State, reason: StateChangeType) -> dict:
            """Format the state change into a document."""

            # Document format
            # {
            #     "@timestamp": "2023-04-12T12:00:00+00:00",
            #     "event": {
            #       "action": "Polling",
            #       "kind": "event",
            #       "type": "info"
            #     },
            #     "hass.entity": {
            #       "attributes": {},
            #       "domain": "sensor",
            #       "geo.location": {
            #         "lat": 99.0,
            #         "lon": 99.0
            #       },
            #       "id": "sensor.test_1",
            #       "value": "2",
            #       "valueas": {
            #         "float": 2.0
            #       }
            #     },
            #     "hass.entity.object.id": "test_1"
            #   }

            # Create the document
            base_document = {
                "@timestamp": time.isoformat(),
                "event.action": {
                    "action": reason.value,
                    "kind": "event",
                    "type": "info",
                },
                "hass.entity": {
                    "attributes": self.state_to_attributes(state),
                    "domain": state.domain,
                    "id": state.entity_id,
                    "value": state.state,
                    "valueas": self.state_to_coerced_value(state),
                },
                "hass.entity.object.id": state.object_id,
            }

            return base_document

    class Publisher:
        """Publishes documents to Elasticsearch."""

        def __init__(self, hass: HomeAssistant, log: Logger = BASE_LOGGER) -> None:
            """Initialize the publisher."""
            self._logger = log
            self._hass = hass


# We are refactoring the below code snippet into the Document class above:


# class DocumentPublisher:
#     """Publishes documents to Elasticsearch."""

#     _logger = BASE_LOGGER

#     def __init__(
#         self,
#         hass: HomeAssistant,
#         gateway: ElasticsearchGateway,
#         log: Logger = BASE_LOGGER,
#     ) -> None:
#         """Initialize the publisher."""
#         self._logger = log
#         self._hass = hass
#         self._gateway = gateway

# """Publishes documents to Elasticsearch."""

# import asyncio
# import time
# from datetime import datetime
# from functools import lru_cache
# from logging import Logger
# from queue import Queue

# from homeassistant.config_entries import ConfigEntry
# from homeassistant.const import (
#     CONF_ALIAS,
#     EVENT_HOMEASSISTANT_CLOSE,
#     EVENT_STATE_CHANGED,
# )
# from homeassistant.core import Event, HomeAssistant, State, callback

# from custom_components.elasticsearch.errors import ElasticException
# from custom_components.elasticsearch.es_doc_creator import DocumentCreator
# from custom_components.elasticsearch.es_gateway import ElasticsearchGateway

# from .const import (
#     CONF_EXCLUDED_DOMAINS,
#     CONF_EXCLUDED_ENTITIES,
#     CONF_INCLUDED_DOMAINS,
#     CONF_INCLUDED_ENTITIES,
#     CONF_INDEX_MODE,
#     CONF_PUBLISH_ENABLED,
#     CONF_PUBLISH_FREQUENCY,
#     CONF_PUBLISH_MODE,
#     CONF_TAGS,
#     DATASTREAM_DATASET_PREFIX,
#     DATASTREAM_NAMESPACE,
#     DATASTREAM_TYPE,
#     INDEX_MODE_DATASTREAM,
#     INDEX_MODE_LEGACY,
#     PUBLISH_MODE_ALL,
#     PUBLISH_MODE_STATE_CHANGES,
#     PUBLISH_REASON_ATTR_CHANGE,
#     PUBLISH_REASON_POLLING,
#     PUBLISH_REASON_STATE_CHANGE,
#     VERSION_SUFFIX,
# )
# from .logger import LOGGER as BASE_LOGGER


# class DocumentPublisher:
#     """Publishes documents to Elasticsearch."""

#     _logger = BASE_LOGGER

#     def __init__(
#         self,
#         gateway: ElasticsearchGateway,
#         hass: HomeAssistant,
#         config_entry: ConfigEntry,
#         log: Logger = BASE_LOGGER,
#     ) -> None:
#         """Initialize the publisher."""

#         self._logger = log
#         self._config_entry = config_entry

#         self.publish_enabled = config_entry.options.get(CONF_PUBLISH_ENABLED)
#         self.publish_active = False
#         self.remove_state_change_listener = None
#         self._publish_timer_ref = None

#         self.publish_queue = None

#         self.empty_queue()

#         if not self.publish_enabled:
#             self._logger.debug("Not initializing document publisher")
#             return

#         self._config_entry = config_entry

#         self._gateway: ElasticsearchGateway = gateway
#         self._hass: HomeAssistant = hass

#         self._destination_type: str = str(config_entry.data.get(CONF_INDEX_MODE))

#         if self._destination_type == INDEX_MODE_LEGACY:
#             self.legacy_index_name = config_entry.options.get(CONF_ALIAS) + VERSION_SUFFIX

#         self._publish_frequency = config_entry.options.get(CONF_PUBLISH_FREQUENCY)
#         self._publish_mode = config_entry.options.get(CONF_PUBLISH_MODE)
#         self._tags = config_entry.options.get(CONF_TAGS)

#         self._excluded_domains = config_entry.options.get(CONF_EXCLUDED_DOMAINS)
#         self._excluded_entities = config_entry.options.get(CONF_EXCLUDED_ENTITIES)
#         self._included_domains = config_entry.options.get(CONF_INCLUDED_DOMAINS)
#         self._included_entities = config_entry.options.get(CONF_INCLUDED_ENTITIES)

#         if self._excluded_domains:
#             self._logger.debug("Excluding the following domains: %s", str(self._excluded_domains))

#         if self._excluded_entities:
#             self._logger.debug("Excluding the following entities: %s", str(self._excluded_entities))

#         if self._included_domains:
#             self._logger.debug("Including the following domains: %s", str(self._included_domains))

#         if self._included_entities:
#             self._logger.debug("Including the following entities: %s", str(self._included_entities))

#         def elastic_event_listener(event: Event) -> None:
#             """Listen for new messages on the bus and queue them for send."""
#             state: State = event.data.get("new_state")
#             old_state: State = event.data.get("old_state")

#             reason = self._determine_change_type(state, old_state)

#             self.enqueue_state(state, event, reason)

#         self.remove_state_change_listener = hass.bus.async_listen(EVENT_STATE_CHANGED, elastic_event_listener)

#         @callback
#         def hass_close_event_listener() -> None:
#             self._logger.debug("Detected Home Assistant Close Event.")
#             self.stop_publisher()

#         self.remove_hass_close_listener = hass.bus.async_listen_once(
#             EVENT_HOMEASSISTANT_CLOSE,
#             hass_close_event_listener,  # type: ignore
#         )

#         self._document_creator = DocumentCreator(log=log, hass=hass, config_entry=config_entry)

#         self._last_publish_time = None

#     async def async_init(self) -> None:
#         """Perform async initialization for the ES document publisher."""
#         if not self.publish_enabled:
#             self._logger.debug("Aborting async_init: publish is not enabled")
#             return

#         await self._document_creator.async_init()

#         self._logger.debug("async_init: starting publish timer")
#         self._start_publish_timer()
#         self._logger.debug("async_init: done")

#     def stop_publisher(self) -> None:
#         """Perform shutdown for ES Document Publisher."""
#         self._logger.info("Stopping document publisher")

#         if not self.publish_active:
#             self._logger.debug(
#                 "Publisher is stopping but publishing documents was not active before stopping",
#             )

#         self.publish_active = False
#         if self._publish_timer_ref is not None:
#             self._publish_timer_ref.cancel()
#             self._publish_timer_ref = None

#         if self.remove_state_change_listener:
#             self.remove_state_change_listener()

#         if self.remove_hass_close_listener:
#             self.remove_hass_close_listener()

#         self._logger.info("Stopped document publisher")

#     def queue_size(self) -> int:
#         """Return the approximate queue size."""
#         return self.publish_queue.qsize()

#     def enqueue_state(self, state: State, event: Event, reason: str) -> bool | None:
#         """Queue up the provided state change."""

#         domain = state.domain
#         entity_id = state.entity_id

#         if not self._should_publish_entity_passes_filter(entity_id):
#             return None

#         if not self._should_publish_state_change_matches_mode(reason, state.entity_id):
#             return None

#         if not self.publish_enabled:
#             self._logger.warning(
#                 "Attempted to queue a state change for %s.%s, but publish is not enabled. This is a no-op (and a bug).",
#                 domain,
#                 entity_id,
#             )
#             return False

#         self.publish_queue.put((state, event, reason))
#         return None

#     def empty_queue(self) -> None:
#         """Empty the publish queue."""
#         self.publish_queue = Queue[
#             tuple[State, Event, str]
#         ]()  # Initialize a new queue and let the runtime perform garbage collection.

#     async def async_do_publish(self) -> None:
#         """Publish all queued documents to the Elasticsearch cluster."""
#         from elasticsearch7.exceptions import ElasticsearchException

#         publish_all_states = self._publish_mode == PUBLISH_MODE_ALL

#         if self.publish_queue.empty() and not publish_all_states:
#             self._logger.debug("Skipping publish because queue is empty")
#             return

#         self._logger.debug("Collecting queued documents for publish")
#         actions = []
#         entity_counts = {}
#         self._last_publish_time = datetime.now()

#         while self.publish_active and not self.publish_queue.empty():
#             (state, event, reason) = self.publish_queue.get()

#             key = state.entity_id

#             entity_counts[key] = 1 if key not in entity_counts else entity_counts[key] + 1
#             actions.append(self._state_to_bulk_action(state, event.time_fired, reason))

#         if publish_all_states:
#             all_states = self._hass.states.async_all()
#             reason = PUBLISH_REASON_POLLING
#             for state in all_states:
#                 if state.entity_id not in entity_counts and self._should_publish_entity_passes_filter(
#                     state.entity_id,
#                 ):
#                     actions.append(self._state_to_bulk_action(state, self._last_publish_time, reason))

#         self._logger.info("Publishing %i documents to Elasticsearch", len(actions))

#         try:
#             await self.async_bulk_sync_wrapper(actions)
#         except ElasticsearchException as err:
#             self._logger.exception("Error publishing documents to Elasticsearch: %s", err)
#         return

#     async def async_bulk_sync_wrapper(self, actions) -> None:
#         """Wrap event publishing.

#         Workaround for elasticsearch_async not supporting bulk operations.
#         """

#         from elasticsearch7.exceptions import ElasticsearchException
#         from elasticsearch7.helpers import async_bulk

#         try:
#             bulk_response = await async_bulk(self._gateway.client, actions)
#             self._logger.debug("Elasticsearch bulk response: %s", str(bulk_response))
#             self._logger.info("Publish Succeeded")
#         except ElasticsearchException as err:
#             self._logger.exception("Error publishing documents to Elasticsearch: %s", err)

#     def _determine_change_type(self, new_state: State, old_state: State) -> str | None:
#         if new_state is None:
#             return None

#         elif old_state is None:
#             reason = PUBLISH_REASON_STATE_CHANGE
#         else:  # state and old_state are both available
#             state_value_changed = old_state.state != new_state.state

#             reason = PUBLISH_REASON_STATE_CHANGE if state_value_changed else PUBLISH_REASON_ATTR_CHANGE

#         return reason

#     def _should_publish_state_change_matches_mode(self, change_type, entity_id) -> bool:
#         """Determine if a state change should be published."""

#         # Publish mode is All or Any Changes, so publish everything!
#         if self._publish_mode != PUBLISH_MODE_STATE_CHANGES:
#             return True

#         if change_type == PUBLISH_REASON_ATTR_CHANGE and self._publish_mode == PUBLISH_MODE_STATE_CHANGES:
#             self._logger.debug(
#                 "Excluding event state change for %s because the value did not change and publish mode is set to state changes only.",
#                 entity_id,
#             )
#             return False

#         return True

#     def _should_publish_entity_passes_filter(self, entity_id: str) -> bool:
#         """Determine if a state change should be published."""

#         domain = entity_id.split(".")[0]

#         is_domain_included = domain in self._included_domains
#         is_domain_excluded = domain in self._excluded_domains

#         is_entity_included = entity_id in self._included_entities
#         is_entity_excluded = entity_id in self._excluded_entities

#         if self._destination_type == INDEX_MODE_DATASTREAM:
#             if is_entity_included:
#                 return True

#             if is_entity_excluded:
#                 return False

#             if is_domain_included:
#                 return True

#             if is_domain_excluded:
#                 return False

#             if len(self._included_entities) == 0 and len(self._included_domains) == 0:
#                 return True

#             return False
#         else:
#             if is_entity_excluded:
#                 return False
#             if is_entity_included or is_domain_included:
#                 return True
#             if is_domain_excluded:
#                 return False
#             return True

#     def _state_to_bulk_action(self, state: State, time: datetime, reason: str) -> dict:
#         """Create a bulk action from the given state object."""

#         if self._destination_type == INDEX_MODE_DATASTREAM:
#             document = self._document_creator.state_to_document(state, time, reason, version=2)

#             (
#                 datastream_type,
#                 datastream_dataset,
#                 datastream_namespace,
#                 datastream_fullname,
#             ) = self._sanitize_datastream_name(
#                 type=DATASTREAM_TYPE,
#                 dataset=DATASTREAM_DATASET_PREFIX + "." + state.domain,
#                 namespace=DATASTREAM_NAMESPACE,
#             )

#             # Populate data stream fields on the document
#             document["data_stream"] = {
#                 "type": datastream_type,
#                 "dataset": datastream_dataset,
#                 "namespace": datastream_namespace,
#             }

#             return {
#                 "_op_type": "create",
#                 "_index": datastream_fullname,
#                 "_source": document,
#             }

#         if self._destination_type == INDEX_MODE_LEGACY:
#             document = self._document_creator.state_to_document(state, time, reason, version=1)

#             return {
#                 "_op_type": "index",
#                 "_index": self.legacy_index_name,
#                 "_source": document,
#                 # If we aren't writing to an alias, that means the
#                 # Index Template likely wasn't created properly, and we should bail.
#                 "require_alias": True,
#             }
#         return None

#     def _start_publish_timer(self) -> None:
#         """Initialize the publish timer."""
#         if self._config_entry:
#             self._publish_timer_ref = self._config_entry.async_create_background_task(
#                 self._hass,
#                 self._publish_queue_timer(),
#                 "publish_queue_timer",
#             )
#         else:
#             self._publish_timer_ref = asyncio.ensure_future(self._publish_queue_timer())

#     def _has_entries_to_publish(self) -> bool:
#         """Determine if now is a good time to publish documents."""
#         if self.publish_queue.empty():
#             self._logger.debug("Nothing to publish")
#             return False

#         return True

#     @classmethod
#     @lru_cache(maxsize=128)
#     def _sanitize_datastream_name(cls, dataset: str, type: str = "metrics", namespace: str = "default"):
#         """Sanitize a datastream name."""

#         full_datastream_name = f"{type}-{dataset}-{namespace}"

#         if cls._datastream_has_fatal_name(full_datastream_name):
#             msg = "Invalid / unfixable datastream name: %s"
#             raise ElasticException(msg, full_datastream_name)

#         if cls._datastream_has_unsafe_name(full_datastream_name):
#             cls._logger.debug(
#                 "Datastream name %s is unsafe, attempting to sanitize.",
#                 full_datastream_name,
#             )

#         sanitized_dataset = dataset

#         # Cannot include \, /, *, ?, ", <, >, |, ` ` (space character), comma, #, :
#         invalid_chars = r"\\/*?\":<>|,#+"
#         sanitized_dataset = sanitized_dataset.translate(str.maketrans("", "", invalid_chars))
#         sanitized_dataset = sanitized_dataset.replace(" ", "_")

#         while sanitized_dataset.startswith(("-", "_", "+", ".")):
#             sanitized_dataset = sanitized_dataset[1::]

#         sanitized_dataset = sanitized_dataset.lower()

#         max_dataset_name_length = 255 - len(type) - len(namespace) - 2
#         sanitized_dataset = sanitized_dataset[:max_dataset_name_length]

#         full_sanitized_datastream_name = f"{type}-{sanitized_dataset}-{namespace}"
#         # if the datastream still has an unsafe name after sanitization, throw an error
#         if cls._datastream_has_unsafe_name(full_sanitized_datastream_name):
#             msg = "Invalid / unfixable datastream name: %s"
#             raise ElasticException(
#                 msg,
#                 full_sanitized_datastream_name,
#             )

#         return (type, sanitized_dataset, namespace, full_sanitized_datastream_name)

#     @classmethod
#     def _datastream_has_unsafe_name(cls, name: str) -> bool:
#         """Check if a datastream name is unsafe."""

#         if cls._datastream_has_fatal_name(name):
#             return True

#         invalid_chars = r"\\/*?\":<>|,#+"
#         if name != name.translate(str.maketrans("", "", invalid_chars)):
#             return True

#         if len(name) > 255:
#             return True

#         # This happens when dataset is empty
#         if "--" in name:
#             return True

#         if name.startswith(("-", "_", "+", ".")):
#             return True

#         if name != name.lower():
#             return True

#         return False

#     @classmethod
#     def _datastream_has_fatal_name(cls, name: str) -> bool:
#         """Check if a datastream name is invalid."""
#         if name in (".", ".."):
#             return True

#         if name == "":
#             return True

#         return False

#     async def _publish_queue_timer(self) -> None:
#         """Publish queue timer."""
#         from elasticsearch7 import TransportError

#         self._logger.debug(
#             "Starting publish timer: executes every %i seconds.",
#             self._publish_frequency,
#         )

#         self.publish_active = True

#         next_publish = time.monotonic() + self._publish_frequency
#         while self.publish_active:
#             try:
#                 time_to_publish = next_publish <= time.monotonic()

#                 can_publish = self._gateway.active

#                 should_publish = self._has_entries_to_publish() or self._publish_mode == PUBLISH_MODE_ALL

#                 if time_to_publish and can_publish and should_publish:
#                     try:
#                         await self.async_do_publish()
#                     finally:
#                         next_publish = time.monotonic() + self._publish_frequency
#             except TransportError as transport_error:
#                 # Do not spam the logs with connection errors if we already know there is a problem.
#                 if not self._gateway.active:
#                     self._logger.exception(
#                         "Connection error during publish queue handling. Publishing will be paused until connection is fixed. %s",
#                         transport_error,
#                     )
#             except Exception as err:
#                 self._logger.exception("Error during publish queue handling %s", err)
#             finally:
#                 if self.publish_active:
#                     await asyncio.sleep(1)

#     def check_duplicate_entries(self, actions: list) -> None:
#         """Check for duplicate entries in the actions list."""
#         duplicate_entries = {}

#         for action in actions:
#             key = (
#                 action["_source"]["@timestamp"]
#                 + "_"
#                 + action["_source"]["hass.entity"]["domain"]
#                 + "."
#                 + action["_source"]["hass.entity.object_id"]
#             )

#             if key in duplicate_entries:
#                 old_action = duplicate_entries[key]

#                 self._logger.warning(
#                     "Duplicate entry #1 found: %s, event source %s: %s",
#                     key,
#                     old_action["_source"]["event"]["action"],
#                     old_action["_source"],
#                 )
#                 self._logger.warning(
#                     "Duplicate entry #2 found: %s, event source %s: %s",
#                     key,
#                     action["_source"]["event"]["action"],
#                     action["_source"],
#                 )

#             else:
#                 duplicate_entries[key] = action

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
    DATASTREAM_DATASET_PREFIX,
    DATASTREAM_NAMESPACE,
    DATASTREAM_TYPE,
    StateChangeType,
)
from elasticsearch.system_info import SystemInfo, SystemInfoResult
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


class PipelineSettings:
    """Pipeline settings."""

    def __init__(
        self,
        included_domains: list[str],
        included_entities: list[str],
        excluded_domains: list[str],
        excluded_entities: list[str],
        allowed_change_types: list[StateChangeType],
        publish_frequency: int,
    ) -> None:
        """Initialize the settings."""
        self.included_domains: list[str] = included_domains
        self.included_entities: list[str] = included_entities
        self.excluded_domains: list[str] = excluded_domains
        self.excluded_entities: list[str] = excluded_entities
        self.allowed_change_types: list[StateChangeType] = allowed_change_types
        self.publish_frequency: int = publish_frequency


class Pipeline:
    """Manages the Pipeline lifecycle."""

    class Manager:
        """Manages the Gather -> Filter -> Format -> Publish pipeline."""

        def __init__(
            self,
            hass: HomeAssistant,
            gateway: ElasticsearchGateway,
            log: Logger,
            settings: PipelineSettings,
        ) -> None:
            """Initialize the manager."""
            self._logger = log if log else BASE_LOGGER
            self._hass: HomeAssistant = hass
            self._gateway: ElasticsearchGateway = gateway
            self._publish_frequency: int = settings.publish_frequency
            self._cancel_manager: Task

            self._static_fields: dict[str, str | float] = {}

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
                queue=self._queue,
            )
            self._filterer = Pipeline.Filterer(hass=self._hass, log=self._logger, settings=settings)
            self._formatter = Pipeline.Formatter(hass=self._hass, log=self._logger)
            self._publisher = Pipeline.Publisher(hass=self._hass, gateway=gateway, log=self._logger)

        async def async_init(self, config_entry: ConfigEntry) -> None:
            """Initialize the manager."""

            system_info: SystemInfo = SystemInfo(hass=self._hass)
            result: SystemInfoResult | None = await system_info.async_get_system_info()

            if result:
                if result.version:
                    self._static_fields["agent.version"] = result.version
                if result.arch:
                    self._static_fields["host.architecture"] = result.arch
                if result.os_name:
                    self._static_fields["host.os.name"] = result.os_name
                if result.hostname:
                    self._static_fields["host.hostname"] = result.hostname

            # Start gathering
            await self._listener.async_init()
            await self._poller.async_init()

            # Start the processors
            await self._formatter.async_init(self._static_fields)
            await self._publisher.async_init()

            # Start processing
            self._cancel_manager = config_entry.async_create_background_task(
                self._hass,
                self._loop(),
                "pipeline_manager_etl_loop",
            )

        async def _loop(self) -> None:
            """Run the pipeline loop."""

            _next_poll = time.monotonic() + self._publish_frequency

            def _time_to_run() -> bool:
                """Determine if now is a good time to poll for state changes."""
                return _next_poll <= time.monotonic()

            def _schedule_next_run() -> None:
                _next_poll = time.monotonic() + self._publish_frequency

            def _should_stop_running() -> bool:
                """Determine if the runner should stop."""
                return self._hass.is_stopping

            async def _spin() -> None:
                """Spin the event loop."""
                await asyncio.sleep(1)

            async def _wait_for_run() -> None:
                """Wait for the next poll time."""
                while not _time_to_run():
                    if _should_stop_running():
                        break
                    await _spin()
                    continue

            while True:
                await _wait_for_run()
                _schedule_next_run()

                documents = []

                await self._poller.poll()

                while not self._queue.empty():
                    timestamp, state, reason = self._queue.get()

                    if not self._filterer.passes_filter(state, reason):
                        continue

                    documents.append(self._formatter.format(timestamp, state, reason))

                await self._publisher.publish(documents)

        def stop(self) -> None:
            """Stop the manager."""
            if self._cancel_manager:
                self._cancel_manager.cancel()

            if self._listener:
                self._listener.stop()

        def __del__(self) -> None:
            """Clean up the manager."""
            self.stop()

    class Filterer:
        """Filters state changes for processing."""

        def __init__(
            self,
            log: Logger,
            hass: HomeAssistant,
            settings: PipelineSettings,
        ) -> None:
            """Initialize the filterer."""
            self._logger = log if log else BASE_LOGGER
            self._hass: HomeAssistant = hass

            self._included_domains: list[str] = settings.included_domains
            self._included_entities: list[str] = settings.included_entities
            self._excluded_domains: list[str] = settings.excluded_domains
            self._excluded_entities: list[str] = settings.excluded_entities
            self._allowed_change_types: list[StateChangeType] = settings.allowed_change_types

        async def async_init(self) -> None:
            """Initialize the filterer."""

        def passes_filter(self, state: State, reason: StateChangeType) -> bool:
            """Filter state changes for processing."""

            if self._passes_change_type_filter(reason):
                return False

            if not self._passes_entity_domain_filters(state.entity_id, state.domain):
                return False

            return True

        def _passes_change_type_filter(self, reason: StateChangeType) -> bool:
            """Determine if a state change should be published."""

            return reason in self._allowed_change_types

        def _passes_entity_domain_filters(self, entity_id: str, domain: str) -> bool:
            """Determine if a state change should be published."""

            if entity_id in self._included_entities:
                return True

            if entity_id in self._excluded_entities:
                return False

            if domain in self._included_domains:
                return True

            if domain in self._excluded_domains:
                return False

            # If we have no included entities or domains, we should publish everything
            if len(self._included_entities) == 0 and len(self._included_domains) == 0:
                return True

            # otherwise, do not publish
            return False

    class Listener:
        """Listens for state changes and queues them for processing."""

        def __init__(
            self,
            hass: HomeAssistant,
            queue: EventQueue,
            log: Logger,
        ) -> None:
            """Initialize the listener."""
            self._logger = log if log else BASE_LOGGER
            self._hass: HomeAssistant = hass
            self._queue: EventQueue = queue
            self._bus_listener_cancel = None

        async def async_init(self) -> None:
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
            log: Logger,
        ) -> None:
            """Initialize the poller."""
            self._logger = log if log else BASE_LOGGER
            self._hass: HomeAssistant = hass
            self._background_task_cancel: Task | None = None
            self._queue: EventQueue = queue

            self._next_poll = time.monotonic()

        async def async_init(self) -> None:
            """Initialize the poller."""

        async def poll(self) -> None:
            """Poll for state changes and queue them for send."""

            now: datetime = datetime.now(tz=UTC)

            all_states = self._hass.states.async_all()

            reason = StateChangeType.NO_CHANGE

            [self._queue.put((now, i, reason)) for i in all_states]

    class Formatter:
        """Formats state changes into documents."""

        def __init__(self, hass: HomeAssistant, log: Logger = BASE_LOGGER) -> None:
            """Initialize the formatter."""
            self._logger = log if log else BASE_LOGGER
            self._hass = hass
            self._static_fields = {}

        async def async_init(self, static_fields: dict) -> None:
            """Initialize the formatter."""
            self._static_fields = static_fields

        @lru_cache(maxsize=128)
        @classmethod
        def _sanitize_domain(cls, domain: str) -> str:
            """Sanitize the domain name."""
            # Only allow alphanumeric characters a-z 0-9 and underscores
            return re.sub(r"[^a-z0-9_]", "", domain.lower())[0:128]

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

            attributes = {}

            for key, value in state.attributes.items():
                if key in SKIP_ATTRIBUTES:
                    continue

                if not isinstance(value, ALLOWED_ATTRIBUTE_TYPES):
                    self._logger.debug(
                        "Not publishing attribute [%s] of disallowed type [%s] from entity [%s].",
                        key,
                        type(value),
                        state.entity_id,
                    )
                    continue

                new_key = self.normalize_attribute_name(key)

                if new_key in attributes:
                    self._logger.warning(
                        "Attribute [%s] shares a key [%s] with another attribute for entity [%s]. Discarding previous attribute value.",
                        key,
                        new_key,
                        state.entity_id,
                    )

                new_value = value

                if isinstance(value, dict):
                    new_value = json.dumps(value)
                elif isinstance(value, set):
                    new_value = list(value)
                elif isinstance(value, list | tuple) and isinstance(value[0], tuple | dict | set | list):
                    new_value = json.dumps(value)

                attributes[key] = value

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

        def state_to_datastream(self, state: State) -> dict:
            """Convert the state into a datastream."""
            return {
                "type": DATASTREAM_TYPE,
                "dataset": DATASTREAM_DATASET_PREFIX + "." + self._sanitize_domain(state.domain),
                "namespace": DATASTREAM_NAMESPACE,
            }

        def format(self, time: datetime, state: State, reason: StateChangeType) -> dict:
            """Format the state change into a document."""

            ds_type = DATASTREAM_TYPE
            ds_dataset = DATASTREAM_DATASET_PREFIX + "." + self._sanitize_domain(state.domain)
            ds_namespace = DATASTREAM_NAMESPACE

            # Create the document
            base_document = {
                "@timestamp": time.isoformat(),
                "event.action": {
                    "action": reason.value,
                    "kind": "event",
                    "type": "info" if reason == StateChangeType.NO_CHANGE else "change",
                },
                "hass.entity": {
                    "attributes": self._state_to_attributes(state),
                    "domain": state.domain,
                    "id": state.entity_id,
                    "value": state.state,
                    "valueas": self.state_to_coerced_value(state),
                    "object.id": state.object_id,
                },
                "datastream": self.state_to_datastream(state),
            }

            # Add static attributes
            base_document.update(self._static_fields)

            return base_document

    class Publisher:
        """Publishes documents to Elasticsearch."""

        def __init__(
            self,
            hass: HomeAssistant,
            gateway: ElasticsearchGateway,
            log: Logger = BASE_LOGGER,
        ) -> None:
            """Initialize the publisher."""
            self._logger = log
            self._hass = hass
            self._gateway = gateway

        async def async_init():
            """Initialize the publisher."""

        def _format_datastream_name(
            self,
            type: str,
            dataset: str,
            namespace: str,
        ) -> str:
            """Format the datastream name."""
            return f"{type}-{dataset}-{namespace}"

        def _add_action_and_meta_data(self, document: dict) -> dict:
            """Prepare the document for insertion into Elasticsearch."""

            return {
                "_op_type": "create",
                "_index": self._format_datastream_name(
                    type=document["datastream"]["type"],
                    dataset=document["datastream"]["dataset"],
                    namespace=document["datastream"]["namespace"],
                ),
                "_source": document,
            }

        async def publish(self, documents: list[dict]) -> None:
            """Publish the document to Elasticsearch."""

            await self._gateway.bulk(documents)

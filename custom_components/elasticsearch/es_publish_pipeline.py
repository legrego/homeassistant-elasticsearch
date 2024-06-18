"""Publishes documents to Elasticsearch."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from functools import lru_cache
from logging import Logger
from math import isinf, isnan
from queue import Queue
from typing import TYPE_CHECKING, Any

from homeassistant.components.sun.const import STATE_ABOVE_HORIZON, STATE_BELOW_HORIZON
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
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry
from homeassistant.helpers import state as state_helper
from homeassistant.util import dt as dt_util
from homeassistant.util.logging import async_create_catching_coro

from custom_components.elasticsearch.const import (
    CONST_ENTITY_DETAILS_TO_ES_DOCUMENT as EXTENDED_DETAILS_TO_ES_DOCUMENT,
)
from custom_components.elasticsearch.const import (
    CONST_ENTITY_DETAILS_TO_ES_DOCUMENT_KEYS as KEYS_TO_KEEP,
)
from custom_components.elasticsearch.const import (
    DATASTREAM_DATASET_PREFIX,
    DATASTREAM_NAMESPACE,
    DATASTREAM_TYPE,
    StateChangeType,
)
from custom_components.elasticsearch.entity_details import (
    ExtendedEntityDetails,
    ExtendedRegistryEntry,
)
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from custom_components.elasticsearch.logger import LOGGER as BASE_LOGGER
from custom_components.elasticsearch.logger import log_enter_exit_debug
from custom_components.elasticsearch.loop import LoopHandler
from custom_components.elasticsearch.system_info import SystemInfo, SystemInfoResult

if TYPE_CHECKING:
    from asyncio import Task  # pragma: no cover

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
        change_detection_type: list[StateChangeType],
        polling_frequency: int,
        publish_frequency: int,
    ) -> None:
        """Initialize the settings."""
        self.included_domains: list[str] = included_domains
        self.included_entities: list[str] = included_entities
        self.excluded_domains: list[str] = excluded_domains
        self.excluded_entities: list[str] = excluded_entities
        self.change_detection_type: list[StateChangeType] = change_detection_type
        self.publish_frequency: int = publish_frequency
        self.polling_frequency: int = polling_frequency

    def to_dict(self) -> dict:
        """Convert the settings to a dictionary."""
        return {
            "included_domains": self.included_domains,
            "included_entities": self.included_entities,
            "excluded_domains": self.excluded_domains,
            "excluded_entities": self.excluded_entities,
            "change_detection_type": [i.value for i in self.change_detection_type],
            "publish_frequency": self.publish_frequency,
            "polling_frequency": self.polling_frequency,
        }


class Pipeline:
    """Manages the Pipeline lifecycle."""

    class Manager:
        """Manages the Gather -> Filter -> Format -> Publish pipeline."""

        def __init__(
            self,
            hass: HomeAssistant,
            gateway: ElasticsearchGateway,
            settings: PipelineSettings,
            log: Logger = BASE_LOGGER,
        ) -> None:
            """Initialize the manager."""
            self._logger = log if log else BASE_LOGGER
            self._hass: HomeAssistant = hass
            self._gateway: ElasticsearchGateway = gateway

            self._cancel_publisher: Task | None = None

            self._settings: PipelineSettings = settings

            self._static_fields: dict[str, str | float] = {}

            self._queue: EventQueue = Queue[tuple[datetime, State, StateChangeType]]()

            self._listener: Pipeline.Listener = Pipeline.Listener(
                hass=self._hass,
                log=self._logger,
                queue=self._queue,
            )

            self._poller: Pipeline.Poller = Pipeline.Poller(
                hass=self._hass,
                log=self._logger,
                queue=self._queue,
                settings=self._settings,
            )

            self._filterer: Pipeline.Filterer = Pipeline.Filterer(
                hass=self._hass,
                log=self._logger,
                settings=settings,
            )
            self._formatter: Pipeline.Formatter = Pipeline.Formatter(hass=self._hass, log=self._logger)
            self._publisher: Pipeline.Publisher = Pipeline.Publisher(
                hass=self._hass,
                settings=self._settings,
                gateway=gateway,
                log=self._logger,
            )

        @log_enter_exit_debug
        async def async_init(self, config_entry: ConfigEntry) -> None:
            """Initialize the manager."""

            if self._settings.publish_frequency is None:
                self._logger.warning("No publish frequency set. Disabling publishing.")
                return

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

            if len(self._settings.change_detection_type) != 0:
                await self._listener.async_init()

            if self._settings.polling_frequency is not None:
                await self._poller.async_init(config_entry=config_entry)

            # Initialize document sinks
            await self._formatter.async_init(self._static_fields)
            await self._publisher.async_init(config_entry=config_entry)

            filter_format_publish = LoopHandler(
                name="es_filter_format_publish_loop",
                func=self._publish,
                frequency=self._settings.publish_frequency,
                log=self._logger,
            )

            self._cancel_publisher = config_entry.async_create_background_task(
                self._hass,
                async_create_catching_coro(filter_format_publish.start()),
                "es_filter_format_publish_task",
            )

        async def _sip_queue(self) -> AsyncGenerator[dict[str, Any], Any]:
            while not self._queue.empty():
                timestamp, state, reason = self._queue.get()

                if not self._filterer.passes_filter(state, reason):
                    continue

                try:
                    yield self._formatter.format(timestamp, state, reason)
                except Exception:
                    self._logger.exception(
                        "Error formatting document for entity [%s]. Skipping document.",
                        state.entity_id,
                    )

        async def _publish(self) -> None:
            """Publish the documents to Elasticsearch."""

            await self._publisher.publish(iterable=self._sip_queue())

        @log_enter_exit_debug
        def stop(self) -> None:
            """Stop the manager."""
            if self._cancel_publisher is not None:
                self._cancel_publisher.cancel()

            self._listener.stop()
            self._poller.stop()
            self._publisher.stop()

        def __del__(self) -> None:
            """Clean up the manager."""
            self.stop()

    class Filterer:
        """Filters state changes for processing."""

        def __init__(
            self,
            hass: HomeAssistant,
            settings: PipelineSettings,
            log: Logger = BASE_LOGGER,
        ) -> None:
            """Initialize the filterer."""
            self._logger = log if log else BASE_LOGGER

            self._included_domains: list[str] = settings.included_domains
            self._included_entities: list[str] = settings.included_entities
            self._excluded_domains: list[str] = settings.excluded_domains
            self._excluded_entities: list[str] = settings.excluded_entities
            self._change_detection_type: list[StateChangeType] = settings.change_detection_type

            self._entity_registry = entity_registry.async_get(hass)

        @log_enter_exit_debug
        async def async_init(self) -> None:
            """Initialize the filterer."""

        def passes_filter(self, state: State, reason: StateChangeType) -> bool:
            """Filter state changes for processing."""

            if not self._passes_change_detection_type_filter(reason):
                return False

            if not self._passes_entity_domain_filters(entity_id=state.entity_id, domain=state.domain):
                return False

            if not self._passes_entity_exists_filter(entity_id=state.entity_id):
                return False

            return True

        def _passes_change_detection_type_filter(self, reason: StateChangeType) -> bool:
            """Determine if a state change should be published."""

            # If polling is enabled, we publish all polled events
            if reason.value == StateChangeType.NO_CHANGE.value:
                return True

            return reason.value in self._change_detection_type

        def _passes_entity_exists_filter(self, entity_id: str) -> bool:
            """Check the entity registry and make sure we can see the entity before proceeding."""

            entity = self._entity_registry.async_get(entity_id)

            if entity is None:
                self._logger.debug(
                    "Entity [%s] not found in registry. Skipping document.",
                    entity_id,
                )
                return False

            return True

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
            log: Logger = BASE_LOGGER,
        ) -> None:
            """Initialize the listener."""
            self._logger = log if log else BASE_LOGGER
            self._hass: HomeAssistant = hass
            self._queue: EventQueue = queue
            self._cancel_listener = None

        @log_enter_exit_debug
        async def async_init(self) -> None:
            """Initialize the listener."""

            self._cancel_listener = self._hass.bus.async_listen(
                EVENT_STATE_CHANGED,
                self._handle_event,
            )

        @callback
        async def _handle_event(self, event: Event[EventStateChangedData]) -> None:
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

        @log_enter_exit_debug
        def stop(self) -> None:
            """Stop the listener."""
            if self._cancel_listener:
                self._cancel_listener()

        def __del__(self) -> None:
            """Clean up the listener."""
            self.stop()

    class Poller:
        """Polls for state changes and queues them for processing."""

        def __init__(
            self,
            hass: HomeAssistant,
            queue: EventQueue,
            settings: PipelineSettings,
            log: Logger = BASE_LOGGER,
        ) -> None:
            """Initialize the poller."""
            self._logger = log if log else BASE_LOGGER
            self._hass: HomeAssistant = hass
            self._cancel_poller: Task | None = None

            self._queue: EventQueue = queue

            self._settings: PipelineSettings = settings

        @log_enter_exit_debug
        async def async_init(self, config_entry: ConfigEntry) -> None:
            """Initialize the poller."""
            state_poll_loop = LoopHandler(
                name="es_state_poll_loop",
                func=self.poll,
                frequency=self._settings.polling_frequency,
                log=self._logger,
            )

            self._cancel_poller = config_entry.async_create_background_task(
                self._hass,
                async_create_catching_coro(state_poll_loop.start()),
                "es_state_poll_task",
            )

        async def poll(self) -> None:
            """Poll for state changes and queue them for send."""

            now: datetime = datetime.now(tz=UTC)

            all_states = self._hass.states.async_all()

            reason = StateChangeType.NO_CHANGE

            [self._queue.put((now, i, reason)) for i in all_states]

        @log_enter_exit_debug
        def stop(self) -> None:
            """Stop the poller."""
            if self._cancel_poller:
                self._cancel_poller.cancel()

        def __del__(self) -> None:
            """Clean up the poller."""
            self.stop()

    class Formatter:
        """Formats state changes into documents."""

        def __init__(self, hass: HomeAssistant, log: Logger = BASE_LOGGER) -> None:
            """Initialize the formatter."""
            self._logger = log if log else BASE_LOGGER
            self._static_fields: dict[str, Any] = {}
            self._extended_entity_details = ExtendedEntityDetails(hass, self._logger)

        @log_enter_exit_debug
        async def async_init(self, static_fields: dict[str, Any]) -> None:
            """Initialize the formatter."""
            self._static_fields = static_fields

        def format(self, time: datetime, state: State, reason: StateChangeType) -> dict[str, Any]:
            """Format the state change into a document."""

            document = {
                "@timestamp": time.isoformat(),
                "event.action": reason.to_publish_reason(),
                "event.kind": "event",
                "event.type": "info" if reason == StateChangeType.NO_CHANGE else "change",
                "hass.entity.attributes": self._state_to_attributes(state),
                "hass.entity.domain": state.domain,
                "hass.entity.id": state.entity_id,
                "hass.entity.value": state.state,
                "hass.entity.valueas": self.state_to_coerced_value(state),
                "hass.entity.object.id": state.object_id,
                **Pipeline.Formatter.domain_to_datastream(state.domain),
                **self._state_to_extended_details(state),
                **self._static_fields,
            }

            # Return the document with null and [] values removed
            return {k: v for k, v in document.items() if v is not None and len(v) != 0}

        # Methods for assembling the document

        def _state_to_extended_details(self, state: State) -> dict:
            """Gather entity details from the state object and return a mapped dictionary ready to be put in an elasticsearch document."""

            extended_registry_entry: ExtendedRegistryEntry = self._extended_entity_details.async_get(
                state.entity_id,
            )

            entry_dict = extended_registry_entry.to_dict(flatten=True, keep_keys=KEYS_TO_KEEP)

            # The logic for friendly name is in the state for some reason
            entry_dict.update(
                {
                    "friendly_name": state.name,
                },
            )

            return {
                f"hass.entity.{k}": entry_dict.get(v)
                for k, v in EXTENDED_DETAILS_TO_ES_DOCUMENT.items()
                if (entry_dict.get(v) is not None and len(entry_dict.get(v, [])) != 0)
            }

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
                elif (
                    isinstance(value, list | tuple)
                    and len(value) > 0
                    and isinstance(value[0], tuple | dict | set | list)
                ):
                    new_value = json.dumps(value)

                attributes[new_key] = new_value

            return attributes

        def state_to_coerced_value(self, state: State) -> dict:
            """Coerce the state value into a dictionary of possible types."""
            value = state.state

            success, result = self.try_state_as_boolean(state)
            if success and result is not None:
                return {"boolean": result}

            success, result = self.try_state_as_number(state)
            if success and result is not None:
                return {"float": result}

            success, result = self.try_state_as_datetime(state)
            if success and result is not None:
                return {
                    "datetime": result.isoformat(),
                    "date": result.date().isoformat(),
                    "time": result.time().isoformat(),
                }

            return {"string": value}

        # Static converter helpers

        @staticmethod
        @lru_cache(maxsize=128)
        def sanitize_domain(domain: str) -> str:
            """Sanitize the domain name."""
            # Only allow alphanumeric characters a-z 0-9 and underscores
            return re.sub(r"[^a-z0-9_]", "", domain.lower())[0:128]

        @staticmethod
        def domain_to_datastream(domain: str) -> dict:
            """Convert the state into a datastream."""
            return {
                "datastream.type": DATASTREAM_TYPE,
                "datastream.dataset": DATASTREAM_DATASET_PREFIX
                + "."
                + Pipeline.Formatter.sanitize_domain(domain),
                "datastream.namespace": DATASTREAM_NAMESPACE,
            }

        @staticmethod
        @lru_cache(maxsize=4096)
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

        # Methods for value coercion
        @classmethod
        def try_state_as_number(cls, state: State) -> tuple[bool, float | None]:
            """Try to coerce our state to a number and return true if we can, false if we can't."""
            try:
                return True, cls.state_as_number(state)
            except ValueError:
                return False, None

        @classmethod
        def state_as_number(cls, state: State) -> float:
            """Try to coerce our state to a number."""

            number = state_helper.state_as_number(state)

            if isinf(number) or isnan(number):
                msg = "Could not coerce state to a number."
                raise ValueError(msg)

            return number

        @classmethod
        def try_state_as_boolean(cls, state: State) -> tuple[bool, bool | None]:
            """Try to coerce our state to a boolean and return true if we can, false if we can't."""
            try:
                return True, cls.state_as_boolean(state)
            except ValueError:
                return False, None

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
        def try_state_as_datetime(cls, state: State) -> tuple[bool, datetime | None]:
            """Try to coerce our state to a datetime and return True if we can, false if we can't."""

            try:
                return True, cls.state_as_datetime(state)
            except ValueError:
                return False, None

        @classmethod
        def state_as_datetime(cls, state: State) -> datetime:
            """Try to coerce our state to a datetime."""

            return dt_util.parse_datetime(state.state, raise_on_error=True)

    class Publisher:
        """Publishes documents to Elasticsearch."""

        def __init__(
            self,
            hass: HomeAssistant,
            gateway: ElasticsearchGateway,
            settings: PipelineSettings,
            log: Logger = BASE_LOGGER,
        ) -> None:
            """Initialize the publisher."""
            self._logger = log
            self._gateway = gateway
            self._settings = settings
            self._hass = hass

        @log_enter_exit_debug
        async def async_init(self, config_entry: ConfigEntry) -> None:
            """Initialize the publisher."""

        @staticmethod
        @lru_cache(maxsize=128)
        def _format_datastream_name(
            datastream_type: str,
            datastream_dataset: str,
            datastream_namespace: str,
        ) -> str:
            """Format the datastream name."""
            return f"{datastream_type}-{datastream_dataset}-{datastream_namespace}"

        async def _add_action_and_meta_data(
            self,
            iterable: AsyncGenerator[dict[str, Any], Any],
        ) -> AsyncGenerator[dict[str, Any], Any]:
            """Prepare the document for insertion into Elasticsearch."""
            async for document in iterable:
                yield {
                    "_op_type": "create",
                    "_index": self._format_datastream_name(
                        datastream_type=document["datastream.type"],
                        datastream_dataset=document["datastream.dataset"],
                        datastream_namespace=document["datastream.namespace"],
                    ),
                    "_source": document,
                }

        async def publish(self, iterable: AsyncGenerator[dict[str, Any], Any]) -> None:
            """Publish the document to Elasticsearch."""

            actions = self._add_action_and_meta_data(iterable)

            await self._gateway.bulk(actions=actions)

        @log_enter_exit_debug
        def stop(self) -> None:
            """Stop the publisher."""

        def __del__(self) -> None:
            """Clean up the publisher."""
            self.stop()

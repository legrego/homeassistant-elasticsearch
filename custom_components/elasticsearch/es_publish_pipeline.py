"""Publishes documents to Elasticsearch."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from functools import lru_cache
from logging import Logger
from math import isinf, isnan
from typing import TYPE_CHECKING, Any

from homeassistant.components.lock.const import LockState
from homeassistant.components.sun.const import STATE_ABOVE_HORIZON, STATE_BELOW_HORIZON
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    EVENT_STATE_CHANGED,
    STATE_CLOSED,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_OFF,
    STATE_ON,
    STATE_OPEN,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import (
    area_registry,
    device_registry,
    entity_registry,
    label_registry,
)
from homeassistant.helpers import state as state_helper
from homeassistant.util import dt as dt_util
from homeassistant.util.logging import async_create_catching_coro

from custom_components.elasticsearch import utils
from custom_components.elasticsearch.const import (
    CONF_TAGS,
    DATASTREAM_DATASET_PREFIX,
    DATASTREAM_NAMESPACE,
    DATASTREAM_TYPE,
    StateChangeType,
)
from custom_components.elasticsearch.encoder import convert_set_to_list
from custom_components.elasticsearch.entity_details import (
    ExtendedEntityDetails,
)
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    ESIntegrationConnectionException,
)
from custom_components.elasticsearch.logger import LOGGER as BASE_LOGGER
from custom_components.elasticsearch.logger import (
    async_log_enter_exit_debug,
    log_enter_exit_debug,
    log_enter_exit_info,
)
from custom_components.elasticsearch.loop import LoopHandler
from custom_components.elasticsearch.system_info import SystemInfo, SystemInfoResult

if TYPE_CHECKING:  # pragma: no cover
    from homeassistant.helpers.device_registry import DeviceEntry
    from homeassistant.helpers.entity_registry import RegistryEntry

    from custom_components.elasticsearch.es_gateway import ElasticsearchGateway

ALLOWED_ATTRIBUTE_KEY_TYPES = str
ALLOWED_ATTRIBUTE_VALUE_TYPES = (
    tuple | dict | set | list | int | float | bool | str | None
)
SKIP_ATTRIBUTES = [
    "friendly_name",
    "entity_picture",
    "icon",
    "device_class",
    "state_class",
    "unit_of_measurement",
]


class EventQueue(asyncio.Queue[tuple[datetime, State, StateChangeType]]):
    """Queue for storing events."""


class PipelineSettings:
    """Pipeline settings."""

    def __init__(
        self,
        include_targets: bool,
        exclude_targets: bool,
        debug_attribute_filtering: bool,
        included_areas: list[str],
        excluded_areas: list[str],
        included_labels: list[str],
        excluded_labels: list[str],
        included_devices: list[str],
        excluded_devices: list[str],
        included_entities: list[str],
        excluded_entities: list[str],
        change_detection_type: list[StateChangeType],
        tags: list[str],
        polling_frequency: int,
        publish_frequency: int,
    ) -> None:
        """Initialize the settings."""
        self.publish_frequency: int = publish_frequency
        self.polling_frequency: int = polling_frequency
        self.change_detection_type: list[StateChangeType] = change_detection_type
        self.tags: list[str] = tags
        self.debug_attribute_filtering: bool = debug_attribute_filtering
        self.include_targets: bool = include_targets
        self.exclude_targets: bool = exclude_targets
        self.included_labels: list[str] = included_labels
        self.excluded_labels: list[str] = excluded_labels
        self.included_areas: list[str] = included_areas
        self.excluded_areas: list[str] = excluded_areas
        self.included_devices: list[str] = included_devices
        self.excluded_devices: list[str] = excluded_devices
        self.included_entities: list[str] = included_entities
        self.excluded_entities: list[str] = excluded_entities


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

            self._config_entry: ConfigEntry | None = None

            self._settings: PipelineSettings = settings

            self._static_fields: dict[str, str | float | list[str] | list[float]] = {}

            self._queue: EventQueue = EventQueue()

            self._filterer: Pipeline.Filterer = Pipeline.Filterer(
                hass=self._hass,
                log=self._logger,
                settings=settings,
            )

            self._listener: Pipeline.Listener = Pipeline.Listener(
                hass=self._hass,
                log=self._logger,
                filterer=self._filterer,
                queue=self._queue,
            )

            self._poller: Pipeline.Poller = Pipeline.Poller(
                hass=self._hass,
                log=self._logger,
                filterer=self._filterer,
                queue=self._queue,
                settings=self._settings,
            )

            self._formatter: Pipeline.Formatter = Pipeline.Formatter(
                hass=self._hass, settings=self._settings, log=self._logger
            )

            self._publisher: Pipeline.Publisher = Pipeline.Publisher(
                hass=self._hass,
                settings=self._settings,
                manager=self,
                gateway=gateway,
                log=self._logger,
            )

        @async_log_enter_exit_debug
        async def async_init(self, config_entry: ConfigEntry) -> None:
            """Initialize the manager."""

            self._config_entry = config_entry

            if self._settings.publish_frequency == 0:
                self._logger.error("No publish frequency set. Disabling publishing.")
                return

            await self._populate_static_fields()

            # Initialize listener if change detection type is configured
            if len(self._settings.change_detection_type) != 0:
                await self._listener.async_init()
            else:
                self._logger.warning(
                    "No change detection type set. Disabling change listener."
                )

            # We only need to initialize the poller if the user has configured a polling frequency
            if self._settings.polling_frequency > 0:
                await self._poller.async_init(config_entry=config_entry)
            else:
                self._logger.warning("No polling frequency set. Disabling polling.")

            # Initialize document sinks
            await self._formatter.async_init(self._static_fields)
            await self._publisher.async_init(config_entry=config_entry)

        async def sip_queue(self) -> AsyncGenerator[dict[str, Any], Any]:
            """Sip an event off of the queue."""

            while not self._queue.empty():
                timestamp: datetime | None = None
                state: State | None = None
                reason: StateChangeType | None = None

                try:
                    timestamp, state, reason = self._queue.get_nowait()

                    yield self._formatter.format(timestamp, state, reason)
                except asyncio.QueueEmpty:
                    pass
                except Exception:
                    self._logger.exception(
                        "Error formatting document for entity [%s]. Skipping document.",
                        state.entity_id if state is not None else "Unknown",
                    )

        @property
        def queue(self) -> EventQueue:
            """Return the queue."""
            return self._queue

        async def _populate_static_fields(self) -> None:
            """Populate the static fields for generated documents."""
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

            if (
                self._hass.config.latitude is not None
                and self._hass.config.longitude is not None
            ):
                self._static_fields["host.location"] = [
                    self._hass.config.longitude,
                    self._hass.config.latitude,
                ]

            if self._settings.tags != []:
                self._static_fields[CONF_TAGS] = self._settings.tags

        @log_enter_exit_info
        def reload_config_entry(self, msg) -> None:
            """Reload the config entry."""

            if (
                self._config_entry
                and self._config_entry.state == ConfigEntryState.LOADED
            ):
                self._logger.info("%s Reloading integration.", msg)
                self._hass.config_entries.async_schedule_reload(
                    self._config_entry.entry_id
                )
            else:
                self._logger.warning("%s Config entry not found or not loaded.", msg)

        @log_enter_exit_debug
        def stop(self) -> None:
            """Stop the manager."""

            self._listener.stop()

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

            self._include_targets: bool = settings.include_targets
            self._exclude_targets: bool = settings.exclude_targets

            self._debug_attribute_filtering: bool = settings.debug_attribute_filtering

            self._included_areas: list[str] = settings.included_areas
            self._excluded_areas: list[str] = settings.excluded_areas
            self._included_devices: list[str] = settings.included_devices
            self._excluded_devices: list[str] = settings.excluded_devices
            self._included_labels: list[str] = settings.included_labels
            self._excluded_labels: list[str] = settings.excluded_labels
            self._included_entities: list[str] = settings.included_entities
            self._excluded_entities: list[str] = settings.excluded_entities
            self._change_detection_type: list[StateChangeType] = (
                settings.change_detection_type
            )

            self._entity_registry = entity_registry.async_get(hass)
            self._label_registry = label_registry.async_get(hass)
            self._area_registry = area_registry.async_get(hass)
            self._device_registry = device_registry.async_get(hass)

        def _reject(self, base_message, message: str) -> bool:
            """Help handle logging for cases where a filter results in rejection of the entity state update."""

            message = base_message + " Rejected: " + message
            self._logger.debug(message)

            return False

        def _accept(self, base_message, message: str) -> bool:
            """Help handle logging for cases where a filter results in inclusion of the entity state update."""

            message = base_message + " Accepted: " + message
            self._logger.debug(message)

            return True

        def passes_filter(self, state: State, reason: StateChangeType) -> bool:
            """Filter state changes for processing."""
            base_msg = f"Processing filters for entity [{state.entity_id}]: "

            if not self._passes_change_detection_type_filter(reason):
                return False

            entity: RegistryEntry | None = self._entity_registry.async_get(
                state.entity_id
            )

            if not entity:
                return self._reject(base_msg, "Entity not found in registry.")

            device: DeviceEntry | None = (
                self._device_registry.async_get(entity.device_id)
                if entity.device_id
                else None
            )

            if self._exclude_targets and not self._passes_exclude_targets(
                entity=entity, device=device
            ):
                return False

            if self._include_targets and not self._passes_include_targets(
                entity=entity, device=device
            ):
                return False

            return self._accept(base_msg, "Entity passed all filters.")

        def _passes_exclude_targets(
            self, entity: RegistryEntry, device: DeviceEntry | None
        ) -> bool:
            base_msg = f"Processing exclusion filters for entity [{entity.entity_id}]: "

            if entity.entity_id in self._excluded_entities:
                return self._reject(base_msg, "In the excluded entities list.")

            if entity.area_id in self._excluded_areas:
                return self._reject(
                    base_msg, f"In an excluded area [{entity.area_id}]."
                )

            for label in entity.labels:
                if label in self._excluded_labels:
                    return self._reject(
                        base_msg, f"Excluded entity label present: [{label}]."
                    )

            if device is not None:
                if device.id in self._excluded_devices:
                    return self._reject(
                        base_msg, f"Attached to an excluded device [{device.id}]."
                    )

                for label in device.labels:
                    if label in self._excluded_labels:
                        return self._reject(
                            base_msg, f"Excluded device label present: [{label}]."
                        )

            return self._accept(base_msg, "Entity was not excluded by filters.")

        def _passes_include_targets(
            self, entity: RegistryEntry, device: DeviceEntry | None
        ) -> bool:
            base_msg = f"Processing inclusion filters for entity [{entity.entity_id}]: "

            if entity.entity_id in self._included_entities:
                return self._accept(base_msg, "In the included entities list.")

            if entity.area_id in self._included_areas:
                return self._accept(
                    base_msg, f"In an included area [{entity.area_id}]."
                )

            for label in entity.labels:
                if label in self._included_labels:
                    return self._accept(
                        base_msg, f"Included entity label present: [{label}]."
                    )

            if device is not None:
                if device.id in self._included_devices:
                    return self._accept(
                        base_msg, f"Attached to an included device [{device.id}]."
                    )

                for label in device.labels:
                    if label in self._included_labels:
                        return self._accept(
                            base_msg, f"Included device label present: [{label}]."
                        )

            return False

        def _passes_change_detection_type_filter(self, reason: StateChangeType) -> bool:
            """Determine if a state change should be published."""
            base_msg = f"Processing change detection type filter: Change type [{reason.value}]: "

            # If polling is enabled, we publish all polled events
            if reason.value == StateChangeType.NO_CHANGE.value:
                return True

            if reason.value in self._change_detection_type:
                return True

            return self._reject(base_msg, "is not in the change detection type list.")

    class Listener:
        """Listens for state changes and queues them for processing."""

        def __init__(
            self,
            hass: HomeAssistant,
            filterer: Pipeline.Filterer,
            queue: EventQueue,
            log: Logger = BASE_LOGGER,
        ) -> None:
            """Initialize the listener."""
            self._logger = log if log else BASE_LOGGER
            self._hass: HomeAssistant = hass
            self._filterer: Pipeline.Filterer = filterer
            self._queue: EventQueue = queue
            self._cancel_listener = None

        @async_log_enter_exit_debug
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

            # Ensure we only queue states that pass the filter
            if self._filterer.passes_filter(new_state, reason):
                self._queue.put_nowait((event.time_fired, new_state, reason))

        @log_enter_exit_debug
        def stop(self) -> None:
            """Stop the listener."""
            if self._cancel_listener:
                self._cancel_listener()
                self._cancel_listener = None

    class Poller:
        """Polls for state changes and queues them for processing."""

        def __init__(
            self,
            hass: HomeAssistant,
            filterer: Pipeline.Filterer,
            queue: EventQueue,
            settings: PipelineSettings,
            log: Logger = BASE_LOGGER,
        ) -> None:
            """Initialize the poller."""
            self._logger = log if log else BASE_LOGGER
            self._hass: HomeAssistant = hass
            self._queue: EventQueue = queue
            self._filterer: Pipeline.Filterer = filterer
            self._settings: PipelineSettings = settings

        @async_log_enter_exit_debug
        async def async_init(self, config_entry: ConfigEntry) -> None:
            """Initialize the poller."""
            state_poll_loop = LoopHandler(
                name="es_state_poll_loop",
                func=self.poll,
                frequency=self._settings.polling_frequency,
                log=self._logger,
            )

            config_entry.async_create_background_task(
                self._hass,
                async_create_catching_coro(state_poll_loop.start()),
                "es_state_poll_task",
            )

            await state_poll_loop.wait_for_first_run()

        async def poll(self) -> None:
            """Poll for state changes and queue them for send."""

            now: datetime = datetime.now(tz=UTC)
            reason = StateChangeType.NO_CHANGE

            for state in self._hass.states.async_all():
                # Ensure we only queue states that pass the filter
                if self._filterer.passes_filter(state, reason):
                    self._queue.put_nowait((now, state, reason))

    class Formatter:
        """Formats state changes into documents."""

        def __init__(
            self,
            hass: HomeAssistant,
            settings: PipelineSettings,
            log: Logger = BASE_LOGGER,
        ) -> None:
            """Initialize the formatter."""
            self._logger = log if log else BASE_LOGGER
            self._static_fields: dict[str, Any] = {}

            self._debug_attribute_filtering: bool = settings.debug_attribute_filtering

            self._extended_entity_details = ExtendedEntityDetails(hass, self._logger)

        @async_log_enter_exit_debug
        async def async_init(self, static_fields: dict[str, Any]) -> None:
            """Initialize the formatter."""
            self._static_fields = static_fields

        def format(
            self, time: datetime, state: State, reason: StateChangeType
        ) -> dict[str, Any]:
            """Format the state change into a document."""

            document = {
                "@timestamp": time.isoformat(),
                "event.action": reason.to_publish_reason(),
                "event.kind": "event",
                "event.type": "info"
                if reason == StateChangeType.NO_CHANGE
                else "change",
                "hass.entity": {**self._state_to_extended_details(state)},
                "hass.entity.attributes": self._state_to_attributes(state),
                "hass.entity.value": state.state,
                "hass.entity.valueas": self._state_to_coerced_value(state),
                "hass.entity.object.id": state.object_id,
                **Pipeline.Formatter.domain_to_datastream(state.domain),
                **self._static_fields,
            }

            return utils.prepare_dict(document)

        def _state_to_extended_details(self, state: State) -> dict:
            """Gather entity details from the state object and return a mapped dictionary ready to be put in an elasticsearch document."""

            document = self._extended_entity_details.async_get(
                state.entity_id
            ).to_dict()

            # The logic for friendly name is in the state for some reason
            document["friendly_name"] = state.name

            if state.attributes.get("longitude") and state.attributes.get("latitude"):
                document["location"] = [
                    state.attributes.get("longitude"),
                    state.attributes.get("latitude"),
                ]

            return document

        def _state_to_attributes(self, state: State) -> dict:
            """Convert the attributes of a State object into a dictionary compatible with Elasticsearch mappings."""

            attributes = {}

            for key, value in state.attributes.items():
                if not self.filter_attribute(state.entity_id, key, value):
                    continue

                new_key = self.normalize_attribute_name(key)

                if new_key in attributes:
                    self._logger.warning(
                        "Attribute [%s] shares a key [%s] with another attribute for entity [%s]. Discarding previous attribute value.",
                        key,
                        new_key,
                        state.entity_id,
                    )

                attributes[new_key] = convert_set_to_list(value)

            return attributes

        def _state_to_coerced_value(self, state: State) -> dict:
            """Coerce the state value into a dictionary of possible types."""
            value: str = state.state

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
                "data_stream.type": DATASTREAM_TYPE,
                "data_stream.dataset": DATASTREAM_DATASET_PREFIX
                + "."
                + Pipeline.Formatter.sanitize_domain(domain),
                "data_stream.namespace": DATASTREAM_NAMESPACE,
            }

        def filter_attribute(self, entity_id, key, value) -> bool:
            """Filter out attributes we don't want to publish."""

            def reject(msg: str) -> bool:
                if self._debug_attribute_filtering:
                    message = (
                        f"Filtering attributes for entity [{entity_id}]: Attribute [{key}] "
                        + msg
                    )
                    self._logger.debug(message)

                return False

            if key in SKIP_ATTRIBUTES:
                return reject("is in the list of attributes to skip.")

            if not isinstance(key, ALLOWED_ATTRIBUTE_KEY_TYPES):
                return reject(f"has a disallowed key type [{type(key)}].")

            if not isinstance(value, ALLOWED_ATTRIBUTE_VALUE_TYPES):
                return reject(
                    f"with value [{value}] has disallowed value type [{type(value)}]."
                )

            if key.strip() == "":
                return reject(
                    "is empty after stripping leading and trailing whitespace."
                )

            return True

        @staticmethod
        @lru_cache(maxsize=4096)
        def normalize_attribute_name(attribute_name: str) -> str:
            """Create an ECS-compliant version of the provided attribute name."""
            # Normalize to closest ASCII equivalent where possible
            normalized_string = (
                unicodedata.normalize("NFKD", attribute_name)
                .encode("ascii", "ignore")
                .decode()
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
                LockState.LOCKED,
                STATE_ABOVE_HORIZON,
                STATE_OPEN,
                STATE_HOME,
            ):
                return True
            if state.state in (
                "false",
                STATE_OFF,
                LockState.UNLOCKED,
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
            manager: Pipeline.Manager,
            log: Logger = BASE_LOGGER,
        ) -> None:
            """Initialize the publisher."""
            self._logger = log
            self._gateway = gateway
            self._manager = manager
            self._settings = settings
            self._hass = hass
            self._queue: EventQueue = manager.queue

        @async_log_enter_exit_debug
        async def async_init(self, config_entry: ConfigEntry) -> None:
            """Initialize the publisher."""
            filter_format_publish = LoopHandler(
                name="es_filter_format_publish_loop",
                func=self.publish,
                frequency=self._settings.publish_frequency,
                log=self._logger,
            )

            config_entry.async_create_background_task(
                self._hass,
                async_create_catching_coro(filter_format_publish.start()),
                "es_filter_format_publish_task",
            )

            await filter_format_publish.wait_for_first_run()

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
                        datastream_type=document["data_stream.type"],
                        datastream_dataset=document["data_stream.dataset"],
                        datastream_namespace=document["data_stream.namespace"],
                    ),
                    "_source": document,
                }

        async def publish(self) -> None:
            """Publish the document to Elasticsearch."""

            try:
                if not await self._gateway.check_connection():
                    self._logger.debug(
                        "Skipping publishing as connection is not available."
                    )
                    return

                actions = self._add_action_and_meta_data(
                    iterable=self._manager.sip_queue()
                )

                await self._gateway.bulk(actions=actions)

            except AuthenticationRequired:
                msg = "Authentication issue in publishing loop."
                self._manager.reload_config_entry(msg)

                self._logger.error(msg)
                self._logger.debug(msg, exc_info=True)

            except ESIntegrationConnectionException:
                msg = "Connection error in publishing loop."

                self._logger.error(msg)
                self._logger.debug(msg, exc_info=True)

            except Exception:  # noqa: BLE001
                msg = "Unknown error while publishing documents."

                self._logger.error(msg)
                self._logger.debug(msg, exc_info=True)

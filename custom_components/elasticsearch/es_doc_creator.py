"""Create Elasticsearch documents from Home Assistant events."""

import re
import unicodedata
from datetime import datetime
from functools import lru_cache
from math import isinf

from homeassistant.components.sun import STATE_ABOVE_HORIZON, STATE_BELOW_HORIZON
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
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
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import state as state_helper
from homeassistant.util import dt as dt_util
from pytz import utc

from custom_components.elasticsearch.const import CONF_TAGS, PUBLISH_REASON_POLLING
from custom_components.elasticsearch.entity_details import EntityDetails
from custom_components.elasticsearch.es_serializer import get_serializer
from custom_components.elasticsearch.logger import LOGGER
from custom_components.elasticsearch.system_info import SystemInfo

ALLOWED_ATTRIBUTE_TYPES = tuple | dict | set | list | int | float | bool | str | None
SKIP_ATTRIBUTES = [
    "friendly_name",
    "entity_picture",
    "icon",
    "device_class",
    "state_class",
    "unit_of_measurement",
]


class DocumentCreator:
    """Create ES documents from Home Assistant state change events."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize."""
        self._entity_details = EntityDetails(hass)
        self._static_v1doc_properties: dict | None = None
        self._static_v2doc_properties: dict | None = None
        self._serializer = get_serializer()
        self._system_info: SystemInfo = SystemInfo(hass)
        self._hass = hass

        self.append_tags = config_entry.options.get(CONF_TAGS, None)

    async def async_init(self) -> None:
        """Async initialization."""

        LOGGER.debug("async_init: initializing static doc properties")

        await self._populate_static_doc_properties()

    async def _populate_static_doc_properties(self) -> dict:
        hass_config = self._hass.config

        shared_properties = {
            "agent.name": "My Home Assistant",
            "agent.type": "hass",
            "ecs.version": "1.0.0",
            "host.geo.location": {
                "lat": hass_config.latitude,
                "lon": hass_config.longitude,
            },
        }

        shared_properties["tags"] = self.append_tags

        system_info = await self._system_info.async_get_system_info()
        if system_info:
            if system_info.version:
                shared_properties["agent.version"] = system_info.version
            if system_info.arch:
                shared_properties["host.architecture"] = system_info.arch
            if system_info.os_name:
                shared_properties["host.os.name"] = system_info.os_name
            if system_info.hostname:
                shared_properties["host.hostname"] = system_info.hostname

        self._static_v1doc_properties = shared_properties.copy()
        self._static_v2doc_properties = shared_properties.copy()

    def _state_to_attributes(self, state: State) -> dict:
        """Convert the attributes of a State object into a dictionary compatible with Elasticsearch mappings.

        Args:
            state (State): The State object containing the attributes.

        Returns:
            dict: A dictionary containing the converted attributes.

        """
        orig_attributes = dict(state.attributes)
        attributes = {}
        for orig_key, orig_value in orig_attributes.items():
            # Skip any attributes with invalid keys. Elasticsearch cannot index these.
            # https://github.com/legrego/homeassistant-elasticsearch/issues/96
            # https://github.com/legrego/homeassistant-elasticsearch/issues/192
            if not orig_key or not isinstance(orig_key, str):
                LOGGER.debug(
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
                LOGGER.debug(
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
                LOGGER.warning(
                    "Attribute [%s] shares a key [%s] with another attribute for entity [%s]. Discarding previous attribute value.",
                    orig_key,
                    key,
                    state.entity_id,
                )
            attributes[key] = (
                self._serializer.dumps(value) if should_serialize else value
            )

        return attributes

    def _state_to_entity_details(self, state: State) -> dict:
        """Gather entity details from the state object and return a mapped dictionary ready to be put in an elasticsearch document.

        Args:
            state (State): The state object to convert.

        Returns:
            dict: An Elasticsearch mapping-compatible entity details dictionary.

        """
        entity_details = self._entity_details.async_get(state.entity_id)

        if entity_details is None:
            return {}

        entity = entity_details.entity
        entity_capabilities = entity.capabilities or {}
        entity_area = entity_details.entity_area

        entity_additions = {
            "labels": entity_details.entity_labels,
            "name": entity.name or entity.original_name,
            "friendly_name": state.name,
            "platform": entity.platform,
            "unit_of_measurement": str(entity.unit_of_measurement),
            "area.id": entity_area.id if entity_area else None,
            "area.name": entity_area.name if entity_area else None,
            "class": entity_capabilities.get("state_class"),
        }

        entity_additions = {
            k: str(v)
            for k, v in entity_additions.items()
            if (v is not None and v != "None")
        }

        device = entity_details.device
        device_floor = entity_details.device_floor
        device_area = entity_details.device_area

        device_additions = {
            "class": entity.device_class or entity.original_device_class,
            "id": (device.id if device else None),
            "labels": entity_details.device_labels,
            "name": (device.name if device else None),
            "friendly_name": (device.name_by_user if device else None),
            "floor.id": device_floor.floor_id if device_floor else None,
            "floor.name": device_floor.name if device_floor else None,
            "area.id": device_area.id if device_area else None,
            "area.name": device_area.name if device_area else None,
        }

        device_additions = {
            k: str(v)
            for k, v in device_additions.items()
            if (v is not None and v != "None")
        }

        return {**entity_additions, "device": {**device_additions}}

    def _state_to_value_v1(self, state: State) -> str | float:
        """Coerce the value from state into a string or a float.

        Args:
            state (State): The state to be coerced.

        Returns:
            str | float: The coerced state value.

        """
        _state = state.state

        if isinstance(_state, str) and self.try_state_as_number(state):
            return state_helper.state_as_number(state)

        else:
            return _state

    def _state_to_value_v2(self, state: State) -> dict:
        """Convert the given state value into to a dictionary containing value and valueas keys representing the values in version 2 format.

        Args:
            state (State): The state to convert.

        Returns:
            dict: A dictionary representing the value in version 2 format. i.e. {value: "thisValue", valueas: {<type>: "thisCoercedValue"}}

        """
        additions = {"valueas": {}}

        _state = state.state

        if isinstance(_state, str) and self.try_state_as_boolean(state):
            additions["valueas"]["boolean"] = self.state_as_boolean(state)

        elif (
            isinstance(_state, str)
            and self.try_state_as_number(state)
            and self.is_valid_number(state_helper.state_as_number(state))
        ):
            additions["valueas"]["float"] = state_helper.state_as_number(state)

        elif isinstance(_state, str) and self.try_state_as_datetime(state):
            _tempState = self.state_as_datetime(state)

            additions["valueas"]["datetime"] = _tempState.isoformat()
            additions["valueas"]["date"] = _tempState.date().isoformat()
            additions["valueas"]["time"] = _tempState.time().isoformat()

        else:
            additions["valueas"]["string"] = _state

        # in v2, value is always a string
        additions["value"] = _state

        return additions

    def _state_to_document_v1(self, state: State, entity: dict, time: datetime) -> dict:
        """Convert entity state to Legacy ES document format."""
        additions = {
            "hass.domain": state.domain,
            "hass.object_id_lower": state.object_id.lower(),
            "hass.entity_id": state.entity_id,
            "hass.entity_id_lower": state.entity_id.lower(),
            "hass.attributes": entity["attributes"],
            "hass.entity": entity,
        }

        additions["hass.entity"]["value"] = self._state_to_value_v1(state)
        additions["hass.value"] = additions["hass.entity"]["value"]

        # If the entity has its own latitude and longitude, use it instead of the hass server's location
        if "latitude" in entity["attributes"] and "longitude" in entity["attributes"]:
            additions["hass.geo.location"] = {
                "lat": entity["attributes"]["latitude"],
                "lon": entity["attributes"]["longitude"],
            }

        return additions

    def _state_to_document_v2(self, state: State, entity: dict, time: datetime) -> dict:
        """Convert entity state to modern ES document format."""
        additions = {"hass.entity": entity}

        additions["hass.entity"].update(self._state_to_value_v2(state))

        # If the entity has its own latitude and longitude, use it instead of the hass server's location
        if "latitude" in entity["attributes"] and "longitude" in entity["attributes"]:
            additions["hass.entity"]["geo.location"] = {
                "lat": entity["attributes"]["latitude"],
                "lon": entity["attributes"]["longitude"],
            }
        else:
            additions["hass.entity"]["geo.location"] = {
                "lat": self._hass.config.latitude,
                "lon": self._hass.config.longitude,
            }

        return additions

    def state_to_document(
        self, state: State, time: datetime, reason: str, version: int = 2
    ) -> dict:
        """Convert entity state to ES document."""

        if time.tzinfo is None:
            time_tz = time.astimezone(utc)
        else:
            time_tz = time

        attributes = self._state_to_attributes(state)

        entity = {
            "id": state.entity_id,
            "domain": state.domain,
            "attributes": attributes,
            "value": state.state,
        }

        # Add details from entity onto object
        entity.update(self._state_to_entity_details(state))

        """
        # log the python type of 'value' for debugging purposes
        LOGGER.debug(
            "Entity [%s] has value [%s] of type [%s]",
            state.entity_id,
            _state,
            type(_state)
        )
        """

        updateType = "change"
        if reason == PUBLISH_REASON_POLLING:
            updateType = "info"

        document_body = {
            "@timestamp": time_tz.isoformat(),
            "hass.object_id": state.object_id,
            "event": {
                "action": reason,
                "type": updateType,
                "kind": "event",
            },
        }

        if (
            self._static_v1doc_properties is None
            or self._static_v2doc_properties is None
        ):
            LOGGER.warning(
                "Event for entity [%s] is missing static doc properties. This is a bug.",
                state.entity_id,
            )
        else:
            pass

        if version == 1:
            document_body.update(self._state_to_document_v1(state, entity, time_tz))

            if self._static_v1doc_properties is not None:
                document_body.update(self._static_v1doc_properties)

        if version == 2:
            document_body.update(self._state_to_document_v2(state, entity, time_tz))

            if self._static_v2doc_properties is not None:
                document_body.update(self._static_v2doc_properties)

        return document_body

    @lru_cache(maxsize=4096)
    def normalize_attribute_name(self, attribute_name: str) -> str:
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

    @classmethod
    def is_valid_number(self, number) -> bool:
        """Determine if the passed number is valid for Elasticsearch."""
        is_infinity = isinf(number)
        is_nan = number != number  # pylint: disable=comparison-with-itself
        return not is_infinity and not is_nan

    @classmethod
    def try_state_as_number(self, state: State) -> bool:
        """Try to coerce our state to a number and return true if we can, false if we can't."""

        try:
            self.state_as_number(state)
            return True
        except ValueError:
            return False

    @classmethod
    def state_as_number(self, state: State) -> bool:
        """Try to coerce our state to a number."""

        number = state_helper.state_as_number(state)

        if not self.is_valid_number(number):
            raise ValueError("Could not coerce state to a number.")

        return number

    @classmethod
    def try_state_as_boolean(self, state: State) -> bool:
        """Try to coerce our state to a boolean and return true if we can, false if we can't."""

        try:
            self.state_as_boolean(state)
            return True
        except ValueError:
            return False

    @classmethod
    def state_as_boolean(self, state: State) -> bool:
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

        raise ValueError("Could not coerce state to a boolean.")

    @classmethod
    def try_state_as_datetime(self, state: State) -> datetime:
        """Try to coerce our state to a datetime and return True if we can, false if we can't."""

        try:
            self.state_as_datetime(state)
            return True
        except ValueError:
            return False

    @classmethod
    def state_as_datetime(self, state: State) -> datetime:
        """Try to coerce our state to a datetime."""

        parsed = dt_util.parse_datetime(state.state)

        # TODO: More recent versions of HA allow us to pass `raise_on_error`.
        # We can remove this explicit `raise` once we update the minimum supported HA version.
        # parsed = dt_util.parse_datetime(_state, raise_on_error=True)

        if parsed is None:
            raise ValueError("Could not coerce state to a datetime.")

        return parsed

"""Create Elasticsearch documents from Home Assistant events."""

from datetime import datetime
from math import isinf

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import state as state_helper
from pytz import utc

from custom_components.elasticsearch.const import CONF_TAGS
from custom_components.elasticsearch.entity_details import EntityDetails
from custom_components.elasticsearch.es_serializer import get_serializer
from custom_components.elasticsearch.logger import LOGGER
from custom_components.elasticsearch.system_info import SystemInfo

ALLOWED_ATTRIBUTE_TYPES = tuple | dict | set | list | int | float | bool | str | None


class DocumentCreator:
    """Create ES documents from Home Assistant state change events."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize."""
        self._entity_details = EntityDetails(hass)
        self._static_doc_properties: dict | None = None
        self._serializer = get_serializer()
        self._system_info: SystemInfo = SystemInfo(hass)
        self._hass = hass
        self._config = config

    async def async_init(self) -> None:
        """Async initialization."""

        system_info = await self._system_info.async_get_system_info()
        LOGGER.debug("async_init: initializing static doc properties")
        hass_config = self._hass.config

        self._static_doc_properties = {
            "agent.name": "My Home Assistant",
            "agent.type": "hass",
            "agent.version": system_info.get("version", "UNKNOWN"),
            "ecs.version": "1.0.0",
            "host.geo.location": {
                "lat": hass_config.latitude,
                "lon": hass_config.longitude,
            },
            "host.architecture": system_info.get("arch", "UNKNOWN"),
            "host.os.name": system_info.get("os_name", "UNKNOWN"),
            "host.hostname": system_info.get("hostname", "UNKNOWN"),
            "tags": self._config.get(CONF_TAGS),
        }

    def state_to_document(self, state: State, time: datetime, version: int = 2) -> dict:
        """Convert entity state to ES document."""
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

            # ES will attempt to expand any attribute keys which contain a ".",
            # so we replace them with an "_" instead.
            # https://github.com/legrego/homeassistant-elasticsearch/issues/92
            key = str.replace(orig_key, ".", "_")
            value = orig_value

            if not isinstance(orig_value, ALLOWED_ATTRIBUTE_TYPES):
                LOGGER.debug(
                    "Not publishing attribute [%s] of disallowed type [%s] from entity [%s].",
                    key,
                    type(orig_value),
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
            "value": _state,
        }

        """
        # log the python type of 'value' for debugging purposes
        LOGGER.debug(
            "Entity [%s] has value [%s] of type [%s]",
            state.entity_id,
            _state,
            type(_state)
        )
        """

        document_body = {
            "@timestamp": time_tz,
            "hass.object_id": state.object_id,
            # new values below. Yes this is duplicitive in the short term.
            "hass.entity": entity,
        }

        # We only include object_id, attributes, and domain in version 1
        if version == 1:
            document_body.update(
                {
                    "hass.domain": state.domain,
                    "hass.attributes": attributes,
                    "hass.object_id_lower": state.object_id.lower(),
                    "hass.entity_id": state.entity_id,
                    "hass.entity_id_lower": state.entity_id.lower(),
                }
            )
            if (
                "latitude" in document_body["hass.attributes"]
                and "longitude" in document_body["hass.attributes"]
            ):
                document_body["hass.geo.location"] = {
                    "lat": document_body["hass.attributes"]["latitude"],
                    "lon": document_body["hass.attributes"]["longitude"],
                }

        if version == 2:
            if (
                "latitude" in document_body["hass.entity"]["attributes"]
                and "longitude" in document_body["hass.entity"]["attributes"]
            ):
                document_body["hass.entity.geo.location"] = {
                    "lat": document_body["hass.entity"]["attributes"]["latitude"],
                    "lon": document_body["hass.entity"]["attributes"]["longitude"],
                }

            # Detect the python type of state and populate valueas hass.entity.valueas subfields accordingly
            if isinstance(_state, int):
                document_body["hass.entity"]["valueas"] = {"integer": _state}
            elif isinstance(_state, float):
                document_body["hass.entity"]["valueas"] = {"float": _state}
            elif isinstance(_state, str):
                try:
                    document_body["hass.entity"]["valueas"]["date"] = datetime.fromisoformat(_state).isoformat()
                except ValueError:
                    document_body["hass.entity"]["valueas"] = {"string": _state}
            elif isinstance(_state, bool):
                document_body["hass.entity"]["valueas"] = {"bool": _state}
            elif isinstance(_state, datetime):
                document_body["hass.entity"]["valueas"] = {"date": _state}

        deets = self._entity_details.async_get(state.entity_id)
        if deets is not None:
            if deets.entity.platform:
                entity["platform"] = deets.entity.platform
            if deets.entity.name:
                entity["name"] = deets.entity.name

            if deets.entity_area:
                entity["area"] = {
                    "id": deets.entity_area.id,
                    "name": deets.entity_area.name,
                }

            if deets.device:
                device["id"] = deets.device.id
                device["name"] = deets.device.name

            if deets.device_area:
                device["area"] = {
                    "id": deets.device_area.id,
                    "name": deets.device_area.name,
                }

        if self._static_doc_properties is None:
            LOGGER.warning(
                "Event for entity [%s] is missing static doc properties. This is a bug.",
                state.entity_id,
            )
        else:
            document_body.update(self._static_doc_properties)

        return document_body


def is_valid_number(number):
    """Determine if the passed number is valid for Elasticsearch."""
    is_infinity = isinf(number)
    is_nan = number != number  # pylint: disable=comparison-with-itself
    return not is_infinity and not is_nan

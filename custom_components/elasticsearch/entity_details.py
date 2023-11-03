
"""Retrieve entity details."""

from dataclasses import dataclass
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.helpers import area_registry, device_registry, entity_registry

from custom_components.elasticsearch.errors import ElasticException

from .logger import LOGGER

@dataclass
class FullEntityDetails():
    """Details about an entity."""

    entity: entity_registry.RegistryEntry
    entity_area: area_registry.AreaEntry | None
    device: device_registry.DeviceEntry | None
    device_area: area_registry.AreaEntry | None

class EntityDetails:
    """Retrieve details about entities for publishing to ES."""

    def __init__(self, hass: HomeAssistantType):
        """Init EntityDetails."""
        self._hass = hass

        self._registry_area: area_registry.AreaRegistry = None
        self._registry_device: device_registry.DeviceRegistry = None
        self._registry_entry: entity_registry.EntityRegistry = None

        self._cache = {}

        self._initialized = False

    async def async_init(self):
        """Async initialization for EntityDetails."""
        LOGGER.debug(
            "async_init: getting entity registry"
        )
        self._registry_entry = entity_registry.async_get(self._hass)
        LOGGER.debug(
            "async_init: finished getting entity registry"
        )

        LOGGER.debug(
            "async_init: getting device registry"
        )
        self._registry_device = device_registry.async_get(self._hass)
        LOGGER.debug(
            "async_init: finished getting device registry"
        )

        LOGGER.debug(
            "async_init: getting area registry"
        )
        self._registry_area = area_registry.async_get(self._hass)
        LOGGER.debug(
            "async_init: finished getting area registry"
        )

        self._initialized = True

    def async_get(self, entity_id: str) -> FullEntityDetails | None:
        """Retrieve entity details."""

        if not self._initialized:
            raise ElasticException("EntityDetails has not finished initialization.")

        cached_entry = self._cache.get(entity_id)
        if cached_entry:
            return cached_entry

        entity: entity_registry.RegistryEntry = self._registry_entry.async_get(entity_id)

        if entity is None:
            LOGGER.debug("Entity not found: %s", entity_id)
            return None

        entity_area: area_registry.AreaEntry = None
        if entity.area_id is not None:
            entity_area = self._registry_area.async_get_area(entity.area_id)

        device: device_registry.DeviceEntry = None
        device_area: area_registry.AreaEntry = None
        if entity.device_id is not None:
            device = self._registry_device.async_get(entity.device_id)
            if device.area_id:
                device_area = self._registry_area.async_get_area(device.area_id)

        details = FullEntityDetails(entity, entity_area, device, device_area)
        self._cache[entity_id] = details
        return details

    def reset_cache(self):
        """Reset the details."""
        self._cache = {}


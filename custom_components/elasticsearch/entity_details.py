
"""Retrieve entity details."""

from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry, device_registry, entity_registry

from .logger import LOGGER


@dataclass
class FullEntityDetails:
    """Details about an entity."""

    entity: entity_registry.RegistryEntry
    entity_area: area_registry.AreaEntry | None
    device: device_registry.DeviceEntry | None
    device_area: area_registry.AreaEntry | None

class EntityDetails:
    """Retrieve details about entities for publishing to ES."""

    def __init__(self, hass: HomeAssistant):
        """Init EntityDetails."""
        self._hass = hass

        self._registry_entry = entity_registry.async_get(self._hass)
        self._registry_device = device_registry.async_get(self._hass)
        self._registry_area = area_registry.async_get(self._hass)

    def async_get(self, entity_id: str) -> FullEntityDetails | None:
        """Retrieve entity details."""

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
        return details


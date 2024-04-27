"""Retrieve entity details."""

from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry,
    device_registry,
    entity_registry,
    floor_registry,
    label_registry,
)

from .logger import LOGGER


@dataclass
class FullEntityDetails:
    """Details about an entity."""

    entity: entity_registry.RegistryEntry
    entity_area: area_registry.AreaEntry | None
    entity_label: label_registry.LabelEntry | None

    device: device_registry.DeviceEntry | None
    device_area: area_registry.AreaEntry | None
    device_floor: floor_registry.FloorEntry | None
    device_label: label_registry.LabelEntry | None


class EntityDetails:
    """Retrieve details about entities for publishing to ES."""

    def __init__(self, hass: HomeAssistant):
        """Init EntityDetails."""
        self._hass = hass

        self._registry_entry = entity_registry.async_get(self._hass)
        self._registry_device = device_registry.async_get(self._hass)
        self._registry_area = area_registry.async_get(self._hass)
        self._registry_floor = floor_registry.async_get(self._hass)
        self._registry_label = label_registry.async_get(self._hass)

    def async_get(self, entity_id: str) -> FullEntityDetails | None:
        """Retrieve entity details."""

        # Use helper functions below to assemble a FullEntityDetails object

        # Get the entity
        entity = self.async_get_entity(entity_id)
        if entity is None:
            LOGGER.debug("Entity not found: %s", entity_id)
            return None

        entity_label = self.async_get_entity_label(entity)
        entity_area = self.async_get_entity_area(entity)

        # Get the device of the entity
        device = self.async_get_device(entity.device_id)
        if device is None:
            LOGGER.debug("Device not found for entity: %s", entity_id)

        device_label = self.async_get_device_label(device)
        device_area = self.async_get_device_area(device)
        device_floor = self.async_get_area_floor(device_area)

        return FullEntityDetails(
            entity,
            entity_area,
            entity_label,
            device,
            device_area,
            device_floor,
            device_label,
        )

    # Entity functions
    def async_get_entity(self, entity_id: str) -> entity_registry.RegistryEntry | None:
        """Retrieve entity details."""
        return self._registry_entry.async_get(entity_id)

    def async_get_entity_area(self, entity) -> area_registry.AreaEntry | None:
        """Retrieve entity area details."""
        if entity.area_id is None:
            return None
        return self._registry_area.async_get_area(entity.area_id)

    def async_get_entity_label(self, entity) -> label_registry.LabelEntry | None:
        """Retrieve entity label details."""
        return list(entity.labels)

    # Device functions
    def async_get_device(self, device_id: str) -> device_registry.DeviceEntry | None:
        """Retrieve device details."""
        return self._registry_device.async_get(device_id)

    def async_get_device_area(self, device) -> area_registry.AreaEntry | None:
        """Retrieve device area details."""
        if device is None or device.area_id is None:
            return None
        return self._registry_area.async_get_area(device.area_id)

    def async_get_device_label(self, device) -> label_registry.LabelEntry | None:
        """Retrieve device label details."""
        if device is None:
            return None
        return list(device.labels)

    # Other Functions
    def async_get_area_floor(self, area) -> floor_registry.FloorEntry | None:
        """Retrieve entity floor details."""
        if area is None:
            return None
        return self._registry_floor.async_get_floor(area.floor_id)

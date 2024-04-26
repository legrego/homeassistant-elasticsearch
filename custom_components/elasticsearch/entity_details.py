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
    entity_floor: floor_registry.FloorEntry | None
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

        entity_area = self.async_get_entity_area(entity_id)
        entity_floor = self.async_get_entity_floor(entity_id)
        entity_label = self.async_get_entity_label(entity_id)

        # Get the device of the entity
        device = self.async_get_device(entity.device_id)
        if device is None:
            LOGGER.debug("Device not found for entity: %s", entity_id)
            return None

        device_area = self.async_get_device_area(device.id)
        device_floor = self.async_get_device_floor(device.id)
        device_label = self.async_get_device_label(device.id)

        return FullEntityDetails(
            entity,
            entity_area,
            entity_floor,
            entity_label,
            device,
            device_area,
            device_floor,
            device_label,
        )

    def async_get_entity_area(self, entity_id: str) -> area_registry.AreaEntry | None:
        """Retrieve entity area details."""
        entity = self._registry_entry.async_get(entity_id)
        if entity is None:
            return None
        return self._registry_area.async_get_area(entity.area_id)

    def async_get_entity_floor(
        self, entity_id: str
    ) -> floor_registry.FloorEntry | None:
        """Retrieve entity floor details."""
        entity = self._registry_entry.async_get(entity_id)
        if entity is None:
            return None
        return self._registry_floor.async_get(entity.floor_id)

    def async_get_entity_label(
        self, entity_id: str
    ) -> label_registry.LabelEntry | None:
        """Retrieve entity label details."""
        entity = self._registry_entry.async_get(entity_id)
        if entity is None:
            return None
        return self._registry_label.async_get(entity.label_id)

    def async_get_device_area(self, device_id: str) -> area_registry.AreaEntry | None:
        """Retrieve device area details."""
        device = self._registry_device.async_get(device_id)
        if device is None:
            return None
        return self._registry_area.async_get_area(device.area_id)

    def async_get_device_floor(
        self, device_id: str
    ) -> floor_registry.FloorEntry | None:
        """Retrieve device floor details."""
        device = self._registry_device.async_get(device_id)
        if device is None:
            return None
        return self._registry_floor.async_get(device.floor_id)

    def async_get_device_label(
        self, device_id: str
    ) -> label_registry.LabelEntry | None:
        """Retrieve device label details."""
        device = self._registry_device.async_get(device_id)
        if device is None:
            return None
        return self._registry_label.async_get(device.label_id)

    def async_get_device(self, device_id: str) -> device_registry.DeviceEntry | None:
        """Retrieve device details."""
        return self._registry_device.async_get(device_id)

    def async_get_area(self, area_id: str) -> area_registry.AreaEntry | None:
        """Retrieve area details."""
        return self._registry_area.async_get_area(area_id)

    def async_get_floor(self, floor_id: str) -> floor_registry.FloorEntry | None:
        """Retrieve floor details."""
        return self._registry_floor.async_get(floor_id)

    def async_get_label(self, label_id: str) -> label_registry.LabelEntry | None:
        """Retrieve label details."""
        return self._registry_label.async_get(label_id)

    def async_get_entity(self, entity_id: str) -> entity_registry.RegistryEntry | None:
        """Retrieve entity details."""
        return self._registry_entry.async_get(entity_id)

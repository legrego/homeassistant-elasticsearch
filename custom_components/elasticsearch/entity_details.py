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
    entity_labels: list[str] | None

    device: device_registry.DeviceEntry | None
    device_area: area_registry.AreaEntry | None
    device_floor: floor_registry.FloorEntry | None
    device_labels: list[str] | None


class EntityDetails:
    """Retrieve details about entities for publishing to ES."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Init EntityDetails."""
        self._hass = hass

        self._registry_entry = entity_registry.async_get(self._hass)
        self._registry_device = device_registry.async_get(self._hass)
        self._registry_area = area_registry.async_get(self._hass)
        self._registry_floor = floor_registry.async_get(self._hass)
        self._registry_label = label_registry.async_get(self._hass)

    def async_get(self, entity_id: str) -> FullEntityDetails | None:
        """Retrieve entity details."""

        # Get the entity
        entity = self.async_get_entity(entity_id)
        if entity is None:
            LOGGER.debug("Entity not found: %s", entity_id)
            return None

        entity_labels = self.async_get_entity_labels(entity)
        entity_area = self.async_get_entity_area(entity)
        entity_floor = self.async_get_area_floor(entity_area) if entity_area else None

        # Get the device of the entity
        device = self.async_get_device(entity.device_id) if entity.device_id else None
        if device is None:
            LOGGER.debug("Device not found for entity: %s", entity_id)

        device_labels = self.async_get_device_labels(device) if device else None
        device_area = self.async_get_device_area(device) if device else None
        device_floor = self.async_get_area_floor(device_area) if device_area else None

        # If entity_floor is None, use device_floor
        if entity_floor is None:
            entity_floor = device_floor

        return FullEntityDetails(
            entity,
            entity_area,
            entity_floor,
            entity_labels,
            device,
            device_area,
            device_floor,
            device_labels,
        )

    # Entity functions
    def async_get_entity(self, entity_id: str) -> entity_registry.RegistryEntry | None:
        """Retrieve entity details."""
        return self._registry_entry.async_get(entity_id)

    def async_get_entity_area(self, entity: entity_registry.RegistryEntry) -> area_registry.AreaEntry | None:
        """Retrieve entity area details."""
        if entity.area_id is None:
            return None
        return self._registry_area.async_get_area(entity.area_id)

    def async_get_entity_labels(
        self,
        entity: entity_registry.RegistryEntry,
    ) -> list[str]:
        """Retrieve entity label details."""
        return list(entity.labels)

    # Device functions
    def async_get_device(self, device_id: str) -> device_registry.DeviceEntry | None:
        """Retrieve device details."""
        return self._registry_device.async_get(device_id)

    def async_get_device_area(self, device: device_registry.DeviceEntry) -> area_registry.AreaEntry | None:
        """Retrieve device area details."""
        if device is None or device.area_id is None:
            return None
        return self._registry_area.async_get_area(device.area_id)

    def async_get_device_labels(self, device: device_registry.DeviceEntry) -> list[str]:
        """Retrieve device label details."""
        return list(device.labels)

    # Other Functions
    def async_get_area_floor(self, area: area_registry.AreaEntry) -> floor_registry.FloorEntry | None:
        """Retrieve entity floor details."""
        if area is None or area.floor_id is None:
            return None
        return self._registry_floor.async_get_floor(area.floor_id)

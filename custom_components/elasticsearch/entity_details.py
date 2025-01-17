"""Retrieve extended details for an entity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers import (
    area_registry,
    device_registry,
    entity_registry,
    floor_registry,
)
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.entity_registry import RegistryEntry

from .logger import LOGGER as BASE_LOGGER

if TYPE_CHECKING:  # pragma: no cover
    from logging import Logger
    from typing import Any

    from homeassistant.core import HomeAssistant


class ExtendedDeviceEntry:
    """Extended device class to include area, floor, and labels."""

    def __init__(
        self,
        details: ExtendedEntityDetails,
        device: DeviceEntry,
        logger: Logger = BASE_LOGGER,
    ) -> None:
        """Init ExtendedDevice."""
        self._logger: Logger = logger
        self._details: ExtendedEntityDetails = details

        self._device: DeviceEntry = device

    @property
    def id(self) -> str:
        """Return the id of the device."""
        return self._device.id

    # @property
    # def device(self) -> DeviceEntry:
    #     """Return the Hass DeviceEntry object."""
    #     return self._device

    @property
    def name(self) -> str | None:
        """Return the Hass friendly name of the device."""
        return self._device.name_by_user or self._device.name

    @property
    def area(self) -> area_registry.AreaEntry | None:
        """Return the Hass AreaEntry of the area of the device."""
        if self._device.area_id is None:
            return None

        return self._details.area_registry.async_get_area(self._device.area_id)

    @property
    def floor(self) -> floor_registry.FloorEntry | None:
        """Return the Hass FloorEntry of the floor of the device."""
        if self.area is None or self.area.floor_id is None:
            return None

        return self._details.floor_registry.async_get_floor(self.area.floor_id)

    @property
    def labels(self) -> list[str]:
        """Return the labels of the device."""
        return sorted(self._device.labels)

    def to_dict(self) -> dict:
        """Convert to dict."""

        device: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "area": None,
            "labels": self.labels,
        }

        if self.area is not None:
            device["area"] = {
                "id": self.area.id,
                "name": self.area.name,
                "floor": None,
            }

        if self.floor is not None:
            device["area"]["floor"] = {
                "id": self.floor.floor_id,
                "name": self.floor.name,
            }

        return device


class ExtendedRegistryEntry:
    """Extended entity class to include device, area, floor, and labels."""

    def __init__(
        self,
        details: ExtendedEntityDetails,
        entity: RegistryEntry,
        device: DeviceEntry | None = None,
        logger: Logger = BASE_LOGGER,
    ) -> None:
        """Initialize an ExtendedRegistryEntry."""
        self._logger: Logger = logger

        self._details: ExtendedEntityDetails = details

        self._entity: RegistryEntry = entity
        self._device: DeviceEntry | None = device

    # @property
    # def entity(self) -> RegistryEntry:
    #     """Return the Hass RegistryEntry object."""
    #     return self._entity

    @property
    def device(self) -> ExtendedDeviceEntry | None:
        """Return the ExtendedDeviceEntry object for the entity."""
        if self._device is None:
            return None

        return ExtendedDeviceEntry(details=self._details, device=self._device)

    @property
    def area(self) -> area_registry.AreaEntry | None:
        """Return the Hass AreaEntry of the area of the entity."""

        if self._entity.area_id is not None:
            return self._details.area_registry.async_get_area(self._entity.area_id)

        return None

    @property
    def floor(self) -> floor_registry.FloorEntry | None:
        """Return the Hass FloorEntry of the floor of the entity."""

        if self.area is not None and self.area.floor_id is not None:
            return self._details.floor_registry.async_get_floor(self.area.floor_id)

        return None

    @property
    def device_class(self) -> str | None:
        """Return the device class of the entity."""
        return self._entity.device_class or self._entity.original_device_class

    @property
    def id(self) -> str | None:
        """Return the id of the entity."""
        return self._entity.entity_id

    @property
    def name(self) -> str | None:
        """Return the name of the entity."""
        return self._entity.name or self._entity.original_name

    @property
    def unit_of_measurement(self) -> str | None:
        """Return the unit of measurement of the entity."""
        return self._entity.unit_of_measurement

    @property
    def platform(self) -> str | None:
        """Return the platform of the entity."""
        return self._entity.platform

    @property
    def domain(self) -> str:
        """Return the domain of the entity."""
        return self._entity.domain

    @property
    def labels(self) -> list[str]:
        """Return the labels of the entity."""
        return sorted(self._entity.labels)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""

        entity: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "domain": self.domain,
            "area": None,
            "device_class": self.device_class,
            "device": None,
            "labels": self.labels,
            "platform": self.platform,
            "unit_of_measurement": self.unit_of_measurement,
        }

        if self.area is not None:
            entity["area"] = {"id": self.area.id, "name": self.area.name, "floor": None}

        if self.floor is not None:
            entity["area"]["floor"] = {
                "id": self.floor.floor_id,
                "name": self.floor.name,
            }

        if self.device is not None:
            entity["device"] = self.device.to_dict()

        return entity


class ExtendedEntityDetails:
    """Creates extended entity and device entries."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: Logger = BASE_LOGGER,
    ) -> None:
        """Init ExtendedEntity class."""
        self._hass: HomeAssistant = hass
        self._logger: Logger = logger

        self.entity_registry: entity_registry.EntityRegistry = entity_registry.async_get(hass)
        self.device_registry: device_registry.DeviceRegistry = device_registry.async_get(hass)
        self.area_registry: area_registry.AreaRegistry = area_registry.async_get(hass)
        self.floor_registry: floor_registry.FloorRegistry = floor_registry.async_get(hass)

    def async_get(self, entity_id: str) -> ExtendedRegistryEntry:
        """Retrieve extended entity details."""
        device: DeviceEntry | None = None
        entity: RegistryEntry | None = None

        entity = self.entity_registry.async_get(entity_id)

        if entity is None:
            msg = f"Entity not found: {entity_id}"
            self._logger.debug(msg)
            raise ValueError(msg)

        if entity.device_id is not None:
            device = self.device_registry.async_get(entity.device_id)

            if device is None:
                self._logger.debug(
                    "Device id [%s] present for entity [%s] but device not found.",
                    entity.device_id,
                    entity_id,
                )

        return ExtendedRegistryEntry(details=self, entity=entity, device=device)

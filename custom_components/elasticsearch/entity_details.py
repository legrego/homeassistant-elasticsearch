"""Retrieve entity details."""

from logging import Logger

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry,
    device_registry,
    entity_registry,
    floor_registry,
)
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.entity_registry import RegistryEntry

from .logger import LOGGER as BASE_LOGGER
from .utils import flatten_dict


class ExtendedDeviceEntry:
    """Extended device class to include area, floor, and labels."""

    def __init__(
        self,
        hass: HomeAssistant,
        device: DeviceEntry | None = None,
        device_id: str | None = None,
        logger: Logger = BASE_LOGGER,
    ) -> None:
        """Init ExtendedDevice."""
        self._hass: HomeAssistant = hass
        self._logger: Logger = logger

        if device is None and device_id is None:
            msg = "device or device_id must be provided"
            raise ValueError(msg)

        if device_id is not None:
            device = device_registry.async_get(self._hass).async_get(device_id)

        if device is not None:
            self._device: DeviceEntry = device

        else:
            msg = f"Device not found: {device_id}"
            self._logger.debug(msg)
            raise ValueError(msg)

    @property
    def device(self) -> DeviceEntry:
        """Return the Hass DeviceEntry object."""
        return self._device

    @property
    def area(self) -> area_registry.AreaEntry | None:
        """Return the Hass AreaEntry of the area of the device."""
        if self._device.area_id is None:
            return None

        return area_registry.async_get(self._hass).async_get_area(self._device.area_id)

    @property
    def floor(self) -> floor_registry.FloorEntry | None:
        """Return the Hass FloorEntry of the floor of the device."""
        if self.area is None or self.area.floor_id is None:
            return None

        return floor_registry.async_get(self._hass).async_get_floor(self.area.floor_id)

    @property
    def labels(self) -> list[str]:
        """Return the labels of the device."""
        return sorted(self._device.labels)

    def to_dict(self, flatten: bool = False, keep_keys: list[str] | None = None) -> dict:
        """Convert to dict."""

        as_dict = self._device.dict_repr

        as_dict["labels"] = self.labels

        if self.area is not None:
            as_dict["area"] = {
                "id": self.area.id,
                "name": self.area.name,
            }

        if self.floor is not None:
            as_dict["floor"] = {
                "floor_id": self.floor.floor_id,
                "name": self.floor.name,
            }

        if flatten:
            return flatten_dict(as_dict, keep_keys=keep_keys)

        return as_dict


class ExtendedRegistryEntry:
    """Extended entity class to include device, area, floor, and labels."""

    def __init__(
        self,
        hass: HomeAssistant,
        entity: RegistryEntry | None = None,
        entity_id: str | None = None,
        logger: Logger = BASE_LOGGER,
    ) -> None:
        """Initialize an ExtendedRegistryEntry."""
        self._hass: HomeAssistant = hass
        self._logger: Logger = logger

        if entity is None and entity_id is None or entity is not None and entity_id is not None:
            msg = "only one of entity or entity_id must be provided"
            raise ValueError(msg)

        if entity_id is not None:
            entity = entity_registry.async_get(self._hass).async_get(entity_id)

        if entity is not None:
            self._entity: RegistryEntry = entity
        else:
            msg = f"Entity not found: {entity_id}"
            logger.debug(msg)
            raise ValueError(msg)

    @property
    def entity(self) -> RegistryEntry:
        """Return the Hass RegistryEntry object."""
        return self._entity

    @property
    def device(self) -> ExtendedDeviceEntry | None:
        """Return the ExtendedDeviceEntry object for the entity."""
        if self._entity.device_id is None:
            return None

        try:
            return ExtendedDeviceEntry(self._hass, device_id=self._entity.device_id)
        except ValueError:
            msg = f"Device not found for entity: {self._entity.entity_id} device: {self._entity.device_id}"
            self._logger.debug(msg, exc_info=True)
            return None

    @property
    def area(self) -> area_registry.AreaEntry | None:
        """Return the Hass AreaEntry of the area of the entity."""

        if self._entity.area_id is not None:
            return area_registry.async_get(self._hass).async_get_area(self._entity.area_id)

        if self.device is not None and self.device.area is not None:
            return self.device.area

        return None

    @property
    def floor(self) -> floor_registry.FloorEntry | None:
        """Return the Hass FloorEntry of the floor of the entity."""

        # use our area if it's present, otherwise fallback to the device's area
        if self.area is not None and self.area.floor_id is not None:
            return floor_registry.async_get(self._hass).async_get_floor(self.area.floor_id)

        return None

    @property
    def labels(self) -> list[str]:
        """Return the labels of the entity."""
        return sorted(self._entity.labels)

    def to_dict(self, flatten: bool = False, keep_keys: list[str] | None = None) -> dict:
        """Convert to dict."""

        as_dict = self._entity.extended_dict

        as_dict["labels"] = self.labels

        if self.area is not None:
            as_dict["area"] = {"id": self.area.id, "name": self.area.name}

        if self.floor is not None:
            as_dict["floor"] = {"floor_id": self.floor.floor_id, "name": self.floor.name}

        if self.device is not None:
            as_dict["device"] = self.device.to_dict()

        if self._entity.device_class or self._entity.original_device_class:
            as_dict["device_class"] = self._entity.device_class or self._entity.original_device_class

        if flatten:
            return flatten_dict(as_dict, keep_keys=keep_keys)

        return as_dict


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

    def async_get(self, entity_id: str) -> ExtendedRegistryEntry:
        """Retrieve entity details."""

        return ExtendedRegistryEntry(self._hass, entity_id=entity_id)

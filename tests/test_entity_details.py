# type: ignore  # noqa: PGH003
"""Test Entity Details."""

import pytest
from custom_components.elasticsearch.const import CONST_ENTITY_DETAILS_TO_ES_DOCUMENT_KEYS as KEYS_TO_KEEP
from custom_components.elasticsearch.entity_details import (
    ExtendedDeviceEntry,
    ExtendedRegistryEntry,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.area_registry import AreaEntry
from homeassistant.helpers.device_registry import DeviceEntry, DeviceRegistry
from homeassistant.helpers.floor_registry import FloorEntry

from tests import const

# Helper functions for the snapshot


def trim_entity_dict(entity_dict):
    """Trim the entity dict to only the keys we care about."""
    if entity_dict is None:
        return None
    return {
        "entity_id": entity_dict.get("entity_id", None),
        "area_id": entity_dict.get("area", {}).get("id", None),
        "floor_name": entity_dict.get("floor", {}).get("name", None),
        "labels": entity_dict.get("labels", None),
    }


def trim_device_dict(device_dict):
    """Trim the device dict to only the keys we care about."""
    if device_dict is None:
        return None
    return {
        "name": device_dict.get("name", None),
        "area_id": device_dict.get("area", {}).get("id", None),
        "floor_name": device_dict.get("floor", {}).get("name", None),
        "labels": device_dict.get("labels", None),
    }


class Test_ExtendedRegistryEntry:
    """Test the ExtendedRegistryEntry class."""

    @pytest.fixture
    def extended_registry_entry(
        self,
        hass,
        entity,
        entity_object_id,  # These are used by the parametrize decorator
        entity_area_name,
        entity_floor_name,
        entity_labels,
    ):
        """Create an ExtendedRegistryEntry instance."""
        entry = ExtendedRegistryEntry(hass, entity)

        assert entry.entity is not None
        assert entry.entity.id == entity.id

        return entry

    def test_init(self, hass: HomeAssistant, entity):
        """Test the init method."""
        new_entry = ExtendedRegistryEntry(hass, entity)

        assert new_entry is not None
        assert new_entry.entity is not None
        assert new_entry.entity.entity_id == entity.entity_id

        new_entry = ExtendedRegistryEntry(hass=hass, entity_id=entity.entity_id)

        assert new_entry is not None
        assert new_entry.entity is not None
        assert new_entry.entity.entity_id == entity.entity_id

    def test_init_failures(self, hass: HomeAssistant):
        """Test the init method."""
        with pytest.raises(ValueError):
            ExtendedRegistryEntry(hass=hass, entity=None, entity_id=None)

        with pytest.raises(ValueError):
            ExtendedRegistryEntry(hass=hass, entity=None, entity_id="nonexistent_entity_id")

    def test_area_property(
        self,
        entity_area: AreaEntry,
        extended_registry_entry: ExtendedRegistryEntry,
    ):
        """Test the area property getter."""
        assert hasattr(extended_registry_entry, "area")
        assert extended_registry_entry.area is not None
        assert extended_registry_entry.area == entity_area
        assert extended_registry_entry.area.name == const.TEST_ENTITY_AREA_NAME

    @pytest.mark.parametrize(
        "entity_area_name",
        [None],
        ids=["passthrough"],
    )
    def test_entity_area_property_from_device(
        self,
        entity_area_name,
        entity,
        device_area_name,
        device,
        extended_registry_entry: ExtendedRegistryEntry,
    ):
        """Test the area property getter."""
        assert hasattr(extended_registry_entry, "area")
        assert extended_registry_entry.area is not None
        assert extended_registry_entry.area.name == const.TEST_DEVICE_AREA_NAME

    def test_device_property(
        self,
        device: DeviceEntry,
        extended_registry_entry: ExtendedRegistryEntry,
    ):
        """Test the device property getter."""
        assert hasattr(extended_registry_entry, "device")
        assert extended_registry_entry.device is not None

        extended_device_entry = extended_registry_entry.device

        assert extended_device_entry._device == device

    def test_device_property_deleted(
        self,
        hass: HomeAssistant,
        device: DeviceEntry,
        extended_registry_entry: ExtendedRegistryEntry,
        device_registry: DeviceRegistry,
    ):
        """Test the device property getter fails if the device_id on the entity doesnt exist."""

        # Remove the device from the registry
        device_registry.async_remove_device(device_id=device.id)

        assert hasattr(extended_registry_entry, "device")

        assert extended_registry_entry.device is None

    @pytest.mark.parametrize(
        "attach_device",
        [False],
        ids=["entity_with_no_device"],
    )
    def test_device_property_not_attached(
        self,
        extended_registry_entry: ExtendedRegistryEntry,
        attach_device,
    ):
        """Test the device property getter fails if there is no device attached for this entity id."""

        assert hasattr(extended_registry_entry, "device")

        assert extended_registry_entry.device is None

    def test_labels_property(
        self,
        entity_labels: list,
        extended_registry_entry: ExtendedRegistryEntry,
    ):
        """Test the labels property getter."""
        assert hasattr(extended_registry_entry, "labels")
        assert extended_registry_entry.labels is not None

        # Verify our labels are not out of order
        assert extended_registry_entry.labels == sorted(entity_labels)
        assert sorted(extended_registry_entry.labels) == extended_registry_entry.labels

        assert extended_registry_entry.labels == const.TEST_ENTITY_LABELS

    def test_floor_property(
        self,
        entity_floor: FloorEntry,
        extended_registry_entry: ExtendedRegistryEntry,
    ):
        """Test the floor property getter."""
        # Make sure the area is also present
        assert hasattr(extended_registry_entry, "floor")
        assert extended_registry_entry.floor is not None
        assert extended_registry_entry.floor == entity_floor
        assert extended_registry_entry.floor.name == const.TEST_ENTITY_FLOOR_NAME

    def test_to_dict(
        self,
        extended_registry_entry: ExtendedRegistryEntry,
        snapshot,
    ):
        """Test the to_dict method."""

        assert extended_registry_entry.to_dict() is not None

        assert trim_entity_dict(extended_registry_entry.to_dict()) == snapshot

    def test_to_flattened_dict(
        self,
        extended_registry_entry: ExtendedRegistryEntry,
        entity_area_name,
        device_area_name,
        snapshot,
    ):
        """Test to_dict with flatten and keep_keys method."""

        flattened = extended_registry_entry.to_dict(flatten=True, keep_keys=KEYS_TO_KEEP)

        assert flattened is not None

        assert flattened == snapshot

    @pytest.mark.parametrize(
        const.TEST_DEVICE_COMBINATION_FIELD_NAMES,
        const.TEST_DEVICE_COMBINATIONS,
        ids=const.TEST_DEVICE_COMBINATION_IDS,
    )
    @pytest.mark.parametrize(
        const.TEST_ENTITY_COMBINATION_FIELD_NAMES,
        const.TEST_ENTITY_COMBINATIONS,
        ids=const.TEST_ENTITY_COMBINATION_IDS,
    )
    async def test_entity_device_combinations(
        self,
        entity,
        entity_object_id,
        entity_area_name,
        entity_floor_name,
        entity_labels,
        device_name,
        device_area_name,
        device_floor_name,
        device_labels,
        extended_registry_entry,
        snapshot,
    ):
        """Test the entity details edge cases."""

        # Basic entity detail check
        assert extended_registry_entry.entity is not None
        assert extended_registry_entry.entity.id == entity.id

        as_dict = extended_registry_entry.to_dict()
        as_flattened_dict = extended_registry_entry.to_dict(flatten=True, keep_keys=KEYS_TO_KEEP)
        assert as_dict is not None
        assert as_flattened_dict is not None

        # Ensure the dict has the same entries that were used to populate the entities and devices
        if entity_area_name is not None:
            assert as_dict["area"] is not None
            assert as_dict["area"]["name"] == entity_area_name

        # Test for entity -> device area fallback
        if entity_area_name is None and device_area_name is not None:
            assert as_dict["area"] is not None
            assert as_dict["area"]["name"] == device_area_name

        if entity_floor_name is not None:
            assert as_dict["floor"] is not None
            assert as_dict["floor"]["name"] == entity_floor_name

        # Test for entity -> device floor fallback
        if entity_area_name is None and entity_floor_name is None and device_floor_name is not None:
            assert as_dict["floor"] is not None
            assert as_dict["floor"]["name"] == device_floor_name

        if entity_labels is not None:
            assert as_dict["labels"] is not None
            assert as_dict["labels"] == entity_labels

        if device_name is not None:
            assert as_dict["device"] is not None
            assert as_dict["device"]["name"] == device_name

        if device_area_name is not None:
            assert as_dict["device"]["area"] is not None
            assert as_dict["device"]["area"]["name"] == device_area_name

        if device_floor_name is not None:
            assert as_dict["device"]["floor"] is not None
            assert as_dict["device"]["floor"]["name"] == device_floor_name

        if device_labels is not None:
            assert as_dict["device"]["labels"] is not None
            assert as_dict["device"]["labels"] == device_labels

        assert {
            "source_entity": {
                "entity_id": entity_object_id,
                "entity_area_name": entity_area_name,
                "entity_floor_name": entity_floor_name,
                "entity_labels": entity_labels,
            },
            "flattened": as_flattened_dict,
            "source_device": {
                "device_name": device_name,
                "device_area_name": device_area_name,
                "device_floor_name": device_floor_name,
                "device_labels": device_labels,
            },
        } == snapshot


class Test_ExtendedDeviceEntry:
    """Test the ExtendedDeviceEntry class."""

    @pytest.fixture
    def extended_device_entry(
        self,
        hass,
        device,
        device_name,
        device_area_name,
        device_floor_name,
        device_labels,
    ):
        """Create an ExtendedDeviceEntry instance."""
        entry = ExtendedDeviceEntry(hass, device=device)

        assert entry.device is not None
        assert entry.device.id == device.id

        return entry

    def test_init(self, hass: HomeAssistant, device):
        """Test the init method."""
        new_entry = ExtendedDeviceEntry(hass, device)

        assert new_entry is not None
        assert new_entry.device is not None
        assert new_entry.device.id == device.id

        new_entry = ExtendedDeviceEntry(hass=hass, device_id=device.id)

        assert new_entry is not None
        assert new_entry.device is not None
        assert new_entry.device.id == device.id

    def test_init_failures(self, hass: HomeAssistant):
        """Test the init method."""
        with pytest.raises(ValueError):
            ExtendedDeviceEntry(hass=hass, device=None, device_id=None)

        with pytest.raises(ValueError):
            ExtendedDeviceEntry(hass=hass, device=None, device_id="nonexistent_device_id")

    def test_area_property(
        self,
        extended_device_entry: ExtendedRegistryEntry,
    ):
        """Test the area property getter."""
        assert hasattr(extended_device_entry, "area")
        assert extended_device_entry.area is not None
        assert extended_device_entry.area.name == const.TEST_DEVICE_AREA_NAME

    def test_floor_property(
        self,
        extended_device_entry: ExtendedRegistryEntry,
    ):
        """Test the floor property getter."""
        # Make sure the area is also present
        assert hasattr(extended_device_entry, "floor")
        assert extended_device_entry.floor is not None
        assert extended_device_entry.floor.name == const.TEST_DEVICE_FLOOR_NAME

    def test_labels_property(
        self,
        device_labels,
        extended_device_entry: ExtendedRegistryEntry,
    ):
        """Test the labels property getter."""
        assert hasattr(extended_device_entry, "labels")
        assert extended_device_entry.labels is not None

        # Verify our labels are not out of order
        assert extended_device_entry.labels == sorted(device_labels)
        assert sorted(extended_device_entry.labels) == extended_device_entry.labels

        assert extended_device_entry.labels == const.TEST_DEVICE_LABELS

    def test_to_dict(
        self,
        extended_device_entry: ExtendedRegistryEntry,
        snapshot,
    ):
        """Test the to_dict method."""

        assert extended_device_entry.to_dict() is not None

        assert trim_device_dict(extended_device_entry.to_dict()) == snapshot

    def test_to_flattened_dict(
        self,
        extended_device_entry: ExtendedRegistryEntry,
        snapshot,
    ):
        """Test to_dict with flatten and keep_keys method."""

        flattened = extended_device_entry.to_dict(flatten=True, keep_keys=KEYS_TO_KEEP)

        assert flattened is not None

        assert flattened == snapshot

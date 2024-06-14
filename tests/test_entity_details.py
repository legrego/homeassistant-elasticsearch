# type: ignore  # noqa: PGH003
"""Test Entity Details."""

import pytest
from homeassistant.helpers.area_registry import AreaEntry
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.floor_registry import FloorEntry

from custom_components.elasticsearch.const import CONST_ENTITY_DETAILS_TO_ES_DOCUMENT_KEYS as KEYS_TO_KEEP
from custom_components.elasticsearch.entity_details import (
    ExtendedDeviceEntry,
    ExtendedRegistryEntry,
    flatten_dict,
)
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


def test_flatten_dict():
    """Test the flatten_dict function."""
    # Test case 1: Flattening a nested dictionary with default separator
    nested_dict = {
        "a": 1,
        "b": {
            "c": 2,
            "d": {
                "e": 3,
            },
        },
        "f": 4,
    }
    expected_result = {
        "a": 1,
        "b.c": 2,
        "b.d.e": 3,
        "f": 4,
    }
    assert flatten_dict(nested_dict) == expected_result

    # Test case 2: Flattening a nested dictionary with specified keys to keep
    nested_dict = {
        "a": 1,
        "b": {
            "c": 2,
            "d": {
                "e": 3,
            },
        },
        "f": 4,
    }
    expected_result = {
        "a": 1,
        "b.c": 2,
        "f": 4,
    }
    assert flatten_dict(nested_dict, keep_keys=["a", "b.c", "f"]) == expected_result

    # Test case 3: Flattening a nested dictionary with lists, sets, and tuples in various locations
    nested_dict = {
        "a": 1,
        "b": {
            "c": [2, 3, 4],
            "d": {
                "e": (5, 6, 7),
            },
        },
        "f": {8, 9, 10},
    }

    expected_result = {
        "a": 1,
        "b.c": [2, 3, 4],
        "b.d.e": (5, 6, 7),
        "f": {8, 9, 10},
    }

    assert flatten_dict(nested_dict) == expected_result


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

    def test_device_property(self, device: DeviceEntry, extended_registry_entry: ExtendedRegistryEntry):
        """Test the device property getter."""
        assert hasattr(extended_registry_entry, "device")
        assert isinstance(extended_registry_entry.device, ExtendedDeviceEntry)
        assert extended_registry_entry.device is not None
        assert extended_registry_entry.device._device is not None
        assert extended_registry_entry.device._device == device

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

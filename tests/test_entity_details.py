# type: ignore  # noqa: PGH003
"""Test Entity Details."""

from unittest.mock import MagicMock, patch

import pytest
from custom_components.elasticsearch import const as compconst
from custom_components.elasticsearch import utils
from custom_components.elasticsearch.entity_details import (
    ExtendedDeviceEntry,
    ExtendedEntityDetails,
    ExtendedRegistryEntry,
)
from homeassistant.core import HomeAssistant

from tests import const as testconst


@pytest.fixture(name="mock_extended_registry")
async def mock_extended_registry_fixture():
    """Return a mock ExtendedRegistryEntry instance."""
    mock_extended_registry = MagicMock(spec=ExtendedRegistryEntry)

    with patch(
        "custom_components.elasticsearch.entity_details.ExtendedRegistryEntry",
        return_value=mock_extended_registry,
    ) as mock:
        yield mock


@pytest.fixture(name="details")
def details_fixture(hass: HomeAssistant, mock_logger):
    """Create an ExtendedEntityDetails instance."""
    return ExtendedEntityDetails(hass=hass, logger=mock_logger)


@pytest.fixture(name="extended_registry")
def extended_registry_fixture(entity_id, details):
    """Create an ExtendedRegistryEntry instance for the provided entity."""

    return details.async_get(entity_id)


class Test_ExtendedEntityDetails:
    """Test the ExtendedEntityDetails class."""

    async def test_init(self, hass: HomeAssistant, details):
        """Test the init method."""
        assert details is not None
        assert details._logger is not None
        assert details.area_registry is not None
        assert details.floor_registry is not None
        assert details.device_registry is not None
        assert details.entity_registry is not None

    @pytest.mark.parametrize("attach_device", [False])
    async def test_get_entity(self, entity, entity_id, details, mock_extended_registry):
        """Test retrieving extended details on an entity with no device."""
        details.async_get(entity_id)

        mock_extended_registry.assert_called_once_with(details=details, entity=entity, device=None)

    async def test_get_entity_with_device(self, entity, entity_id, device, details, mock_extended_registry):
        """Test retrieving extended details on an entity with a device attached."""
        details.async_get(entity_id)

        mock_extended_registry.assert_called_once_with(details=details, entity=entity, device=device)

    async def test_get_entity_with_missing_device(
        self, entity, entity_id, device, details, mock_extended_registry
    ):
        """Test retrieving extended details on an entity with an invalid device id."""
        details.device_registry.async_get = MagicMock(return_value=None)

        details.async_get(entity_id)

        details._logger.debug.assert_called_once_with(
            "Device id [%s] present for entity [%s] but device not found.",
            entity.device_id,
            entity_id,
        )

        mock_extended_registry.assert_called_once_with(details=details, entity=entity, device=None)

    async def test_get_entity_missing(self, details, mock_extended_registry):
        """Test retrieving extended details on an entity which is missing from the registry."""

        entity_id = "counter.nonexistent_entity"

        with pytest.raises(
            ValueError,
            match=f"Entity not found: {entity_id}",
        ):
            details.async_get(entity_id)


class Test_ExtendedRegistryEntry:
    """Test the ExtendedRegistryEntry class."""

    async def test_init(
        self,
        details,
        entity,
        entity_id,
        entity_object_id,
        entity_area_name,
        entity_area_id,
        entity_floor_name,
        entity_floor_id,
        entity_labels,
        device,
        device_id,
        device_name,
        device_area_name,
        device_area_id,
        device_floor_name,
        device_floor_id,
        device_labels,
    ):
        """Create an ExtendedRegistryEntry instance."""
        extended_entity = ExtendedRegistryEntry(details=details, entity=entity, device=device)

        assert extended_entity is not None
        assert extended_entity._entity == entity
        assert extended_entity.id == entity_id
        assert extended_entity.area.id == entity_area_id
        assert extended_entity.area.name == entity_area_name
        assert extended_entity.floor.floor_id == entity_floor_id
        assert extended_entity.floor.name == entity_floor_name
        assert extended_entity.labels == entity_labels

        assert extended_entity.device is not None
        assert extended_entity.device.id == device_id
        assert extended_entity.device.name == device_name
        assert extended_entity.device.area.id == device_area_id
        assert extended_entity.device.area.name == device_area_name
        assert extended_entity.device.floor.floor_id == device_floor_id
        assert extended_entity.device.floor.name == device_floor_name
        assert extended_entity.device.labels == device_labels

    async def test_init_entity_only(
        self,
        details,
        entity,
        entity_id,
        entity_object_id,
        entity_area_name,
        entity_area_id,
        entity_floor_name,
        entity_floor_id,
        entity_labels,
    ):
        """Create an ExtendedRegistryEntry instance."""
        extended_entity = ExtendedRegistryEntry(details=details, entity=entity)

        assert extended_entity is not None
        assert extended_entity._entity == entity
        assert extended_entity.id == entity_id
        assert extended_entity.area.id == entity_area_id
        assert extended_entity.area.name == entity_area_name
        assert extended_entity.floor.floor_id == entity_floor_id
        assert extended_entity.floor.name == entity_floor_name
        assert extended_entity.labels == entity_labels

        assert extended_entity.device is None

    async def test_init_entity_with_device(
        self,
        details,
        entity,
        entity_id,
        entity_name,
        entity_area_name,
        entity_area_id,
        entity_floor_name,
        entity_floor_id,
        entity_labels,
        device,
        device_id,
        device_name,
        device_area_name,
        device_area_id,
        device_floor_name,
        device_floor_id,
        device_labels,
    ):
        """Create an ExtendedRegistryEntry instance."""
        extended_entity = ExtendedRegistryEntry(details=details, entity=entity, device=device)

        assert extended_entity is not None
        assert extended_entity._entity == entity
        assert extended_entity.id == entity_id
        assert extended_entity.name == entity_name
        assert extended_entity.area.id == entity_area_id
        assert extended_entity.area.name == entity_area_name
        assert extended_entity.floor.name == entity_floor_name
        assert extended_entity.floor.floor_id == entity_floor_id
        assert extended_entity.labels == entity_labels

        assert extended_entity.device is not None
        assert extended_entity.device.id == device_id
        assert extended_entity.device.name == device_name
        assert extended_entity.device.area.id == device_area_id
        assert extended_entity.device.area.name == device_area_name
        assert extended_entity.device.floor.floor_id == device_floor_id
        assert extended_entity.device.floor.name == device_floor_name
        assert extended_entity.device.labels == device_labels

    async def test_to_dict(self, details, entity, device, snapshot):
        """Create an ExtendedRegistryEntry instance."""
        extended_entity = ExtendedRegistryEntry(details=details, entity=entity, device=device)

        assert extended_entity is not None

        assert extended_entity.to_dict() == snapshot

    @pytest.mark.parametrize(
        ("entity_original_name", "entity_name", "expected_name"),
        [
            ("Original", "New", "New"),
            ("Original", None, "Original"),
            (None, "New", "New"),
            (None, None, None),
        ],
        ids=[
            "Default name; updated by user",
            "Default name",
            "No default name; updated by user",
            "No default name",
        ],
    )
    async def test_name_handling(
        self,
        entity_registry,
        details,
        entity,
        entity_original_name,
        entity_name,
        expected_name,
    ):
        """Test our handling of the name and original_name properties."""

        extended_entity = ExtendedRegistryEntry(details=details, entity=entity, device=None)

        assert extended_entity._entity.original_name == entity_original_name
        assert extended_entity._entity.name == entity_name

        assert extended_entity.name == expected_name

    @pytest.mark.parametrize(
        (
            "entity_original_device_class",
            "entity_device_class",
            "expected_device_class",
        ),
        [
            ("Original", "New", "New"),
            ("Original", None, "Original"),
            (None, "New", "New"),
            (None, None, None),
        ],
        ids=[
            "Default device_class; updated by user",
            "Default device_class",
            "No default device_class; updated by user",
            "No default device_class",
        ],
    )
    async def test_device_class_handling(
        self,
        entity_registry,
        details,
        entity,
        entity_device_class,
        entity_original_device_class,
        expected_device_class,
    ):
        """Test our handling of the device_class and original_device_class properties."""

        extended_entity = ExtendedRegistryEntry(details=details, entity=entity, device=None)

        assert extended_entity._entity.original_device_class == entity_original_device_class
        assert extended_entity._entity.device_class == entity_device_class

        assert extended_entity.device_class == expected_device_class

    @pytest.mark.parametrize(*testconst.ENTITY_MATRIX_COMPREHENSIVE)
    @pytest.mark.parametrize(*testconst.DEVICE_MATRIX_COMPREHENSIVE)
    async def test_entity_device_combinations(
        self,
        details,
        entity,
        entity_object_id,
        entity_name,
        entity_area_name,
        entity_floor_name,
        entity_device_class,
        entity_domain: str,
        entity_labels,
        entity_platform,
        entity_unit_of_measurement,
        device,
        device_id,
        device_name,
        device_area_name,
        device_floor_name,
        device_labels,
    ):
        """Test the entity details edge cases."""
        entry_dict = ExtendedRegistryEntry(details=details, entity=entity, device=device).to_dict()

        document = utils.flatten_dict(entry_dict)

        def name_to_id(name):
            if name is None:
                return None
            return name.replace(" ", "_")

        # Entity details
        assert document.pop("name") is entity_name
        assert document.pop("id", None) == entity_domain + "." + entity_object_id
        assert document.pop("domain", None) == entity_domain
        assert document.pop("device_class", None) == entity_device_class
        assert document.pop("platform", None) == entity_platform
        assert document.pop("unit_of_measurement", None) == entity_unit_of_measurement

        # Floor will be pulled from area if present
        assert document.pop("area.name", None) == entity_area_name
        assert document.pop("area.id", None) == name_to_id(entity_area_name)
        assert document.pop("area.floor.name", None) == entity_floor_name
        assert document.pop("area.floor.id", None) == name_to_id(entity_floor_name)

        assert document.pop("labels", None) == entity_labels

        # Device details
        assert document.pop("device.name", None) == device_name
        assert document.pop("device.id", None) == testconst.DEVICE_ID
        assert document.pop("device.area.name", None) == device_area_name
        assert document.pop("device.area.id", None) == name_to_id(device_area_name)
        assert document.pop("device.area.floor.name", None) == device_floor_name
        assert document.pop("device.area.floor.id", None) == name_to_id(device_floor_name)
        assert document.pop("device.labels", None) == device_labels

        # Ensure that remaining keys are trimmable
        assert utils.skip_dict_values(document, skip_values=compconst.SKIP_VALUES) == {}


class Test_ExtendedDeviceEntry:
    """Test the ExtendedDeviceEntry class."""

    async def test_init(
        self,
        details,
        device,
        device_id,
        device_name,
        device_area_name,
        device_area_id,
        device_floor_name,
        device_floor_id,
        device_labels,
    ):
        """Create an ExtendedDeviceEntry instance."""
        extended_device = ExtendedDeviceEntry(details=details, device=device)

        assert extended_device is not None
        assert extended_device._device == device
        assert extended_device.id == device_id
        assert extended_device.name == device_name
        assert extended_device.area.id == device_area_id
        assert extended_device.area.name == device_area_name
        assert extended_device.floor.floor_id == device_floor_id
        assert extended_device.floor.name == device_floor_name
        assert extended_device.labels == device_labels

    async def test_to_dict(self, details, device, snapshot):
        """Create an ExtendedDeviceEntry instance."""
        extended_device = ExtendedDeviceEntry(details=details, device=device).to_dict()

        assert utils.flatten_dict(extended_device) == snapshot

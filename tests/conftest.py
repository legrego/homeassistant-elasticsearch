# pylint: disable=redefined-outer-name
"""Global fixtures for elastic integration."""

# Fixtures allow you to replace functions with a Mock object. You can perform
# many options via the Mock to reflect a particular behavior from the original
# function that you want to see without going through the function's actual logic.
# Fixtures can either be passed into tests as parameters, or if autouse=True, they
# will automatically be used across all tests.
#
# Fixtures that are defined in conftest.py are available across all tests. You can also
# define fixtures within a particular test file to scope them locally.
#
# pytest_homeassistant_custom_component provides some fixtures that are provided by
# Home Assistant core. You can find those fixture definitions here:
# https://github.com/MatthewFlamm/pytest-homeassistant-custom-component/blob/master/pytest_homeassistant_custom_component/common.py
#
# See here for more info: https://docs.pytest.org/en/latest/fixture.html (note that
# pytest includes fixtures OOB which you can use as defined on this page)
from __future__ import annotations

from asyncio import get_running_loop
from typing import TYPE_CHECKING
from unittest import mock
from unittest.mock import patch

import pytest
from aiohttp import ClientSession, TCPConnector
from custom_components.elasticsearch.config_flow import ElasticFlowHandler
from freezegun.api import FrozenDateTimeFactory

# import custom_components.elasticsearch  # noqa: F401
from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import json_dumps
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,  # noqa: F401
)
from pytest_homeassistant_custom_component.plugins import (  # noqa: F401
    aioclient_mock,
    skip_stop_scripts,
    snapshot,
    verify_cleanup,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from tests import const
from tests.test_util.es_mocker import es_mocker

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator
    from typing import Any

    from homeassistant.helpers.area_registry import AreaEntry, AreaRegistry
    from homeassistant.helpers.device_registry import DeviceRegistry
    from homeassistant.helpers.entity_registry import EntityRegistry
    from homeassistant.helpers.floor_registry import FloorEntry, FloorRegistry

MODULE = "custom_components.elasticsearch"


@pytest.fixture
async def integration_setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> Callable[[], Awaitable[bool]]:
    """Fixture to set up the integration."""
    config_entry.add_to_hass(hass)

    async def run() -> bool:
        result = await hass.config_entries.async_setup(config_entry.entry_id)

        await hass.async_block_till_done()

        return result

    return run


@pytest.fixture
def es_mock_builder() -> Generator[es_mocker, Any, None]:
    """Fixture to return a builder for mocking Elasticsearch calls."""

    mocker = AiohttpClientMocker()

    def create_session(*args, **kwargs):
        session = ClientSession(
            loop=get_running_loop(),
            json_serialize=json_dumps,
        )
        # Setting directly on `session` will raise deprecation warning
        object.__setattr__(session, "_request", mocker.match_request)
        return session

    # clean-up closed causes a task unfinished error for tests, so we disable it
    def create_tcpconnector(*args, **kwargs):
        return TCPConnector(force_close=True, enable_cleanup_closed=False)

    with (
        mock.patch(
            "elastic_transport._node._http_aiohttp.aiohttp.ClientSession",
            side_effect=create_session,
        ),
        mock.patch(
            "elastic_transport._node._http_aiohttp.aiohttp.TCPConnector",
            side_effect=create_tcpconnector,
        ),
    ):
        yield es_mocker(mocker)


@pytest.fixture
def freeze_time(freezer: FrozenDateTimeFactory):
    """Freeze time so we can properly assert on payload contents."""

    frozen_time = dt_util.parse_datetime(const.MOCK_NOON_APRIL_12TH_2023)
    if frozen_time is None:
        msg = "Invalid date string"
        raise ValueError(msg)

    freezer.move_to(frozen_time)

    return freezer


# This fixture enables loading custom integrations in all tests.
# Remove to enable selective use of this fixture
@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations) -> None:
    """Auto enable custom integrations."""
    return


# This fixture is used to prevent HomeAssistant from attempting to create and dismiss persistent
# notifications. These calls would fail without this fixture since the persistent_notification
# integration is never loaded during a test.
@pytest.fixture(name="skip_notifications", autouse=True)
def _skip_notifications_fixture() -> Generator[Any, Any, Any]:
    """Skip notification calls."""
    with (
        patch("homeassistant.components.persistent_notification.async_create"),
        patch("homeassistant.components.persistent_notification.async_dismiss"),
    ):
        yield


@pytest.fixture
async def data() -> dict:
    """Return a mock data dict."""
    return const.TEST_CONFIG_ENTRY_DEFAULT_DATA


@pytest.fixture
async def version() -> int:
    """Return a mock options dict."""
    return ElasticFlowHandler.VERSION


@pytest.fixture
async def options() -> dict:
    """Return a mock options dict."""
    return const.TEST_CONFIG_ENTRY_BASE_OPTIONS


@pytest.fixture
async def add_to_hass() -> bool:
    """Return whether to add the config entry to hass."""
    return True


@pytest.fixture(autouse=True)
def _fix_system_info():
    """Return a mock system info."""
    with mock.patch("custom_components.elasticsearch.es_publish_pipeline.SystemInfo") as system_info:
        system_info_instance = system_info.return_value
        system_info_instance.async_get_system_info = mock.AsyncMock(
            return_value=mock.Mock(
                version="1.0.0",
                arch="x86",
                os_name="Linux",
                hostname="my_es_host",
            ),
        )

        yield


@pytest.fixture(autouse=True)
async def _fix_location(hass: HomeAssistant):
    """Return whether to fix the location."""

    hass.config.latitude = 1.0
    hass.config.longitude = -1.0


@pytest.fixture
async def config_entry(
    hass: HomeAssistant,
    data: dict,
    options: dict,
    add_to_hass: bool,
    version: int,
):
    """Create a mock config entry and add it to hass."""

    entry = MockConfigEntry(
        title="ES Integration",
        domain="elasticsearch",
        data=data,
        options=options,
        version=version,
    )

    setattr(entry, "runtime_data", None)

    if add_to_hass:
        entry.add_to_hass(hass)

    try:
        yield entry
    finally:
        await hass.config_entries.async_remove(entry.entry_id)
    # Unload the config entry


# New Device Fixtures
@pytest.fixture
async def device_floor(floor_registry: FloorRegistry, device_floor_name: str):
    """Mock a floor."""
    if device_floor_name is None:
        return None

    if floor_registry.async_get_floor_by_name(device_floor_name) is not None:
        msg = f"Floor {device_floor_name} already exists"
        raise ValueError(msg)

    return floor_registry.async_create(device_floor_name)


@pytest.fixture
async def device_area_name():
    """Return an device area name."""
    return const.TEST_DEVICE_AREA_NAME


@pytest.fixture
async def device_floor_name():
    """Return an device floor name."""
    return const.TEST_DEVICE_FLOOR_NAME


@pytest.fixture
async def device_area(
    area_registry,
    device_floor: FloorEntry,
    device_area_name: str,
):
    """Mock an area."""

    if device_area_name is None:
        return None

    extra_settings: dict[str, Any] = {}
    if device_floor is not None:
        extra_settings["floor_id"] = device_floor.floor_id

    if area_registry.async_get_area_by_name(device_area_name) is not None:
        msg = f"Area {device_area_name} already exists"
        raise ValueError(msg)

    return area_registry.async_create(device_area_name, **extra_settings)


@pytest.fixture
async def device(
    config_entry: MockConfigEntry,
    device_registry: DeviceRegistry,
    device_name: str,
    device_area: AreaEntry,
    device_labels: list[str],
):
    """Mock a device."""

    device = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections=None,
        identifiers={
            (
                "device_name",
                device_name,
            ),
        },
        manufacturer=None,
        model=None,
        name=device_name,
    )

    if device_area is not None:
        device_registry.async_update_device(device_id=device.id, area_id=device_area.id)

    if device_labels is not None and len(device_labels) > 0:
        device_registry.async_update_device(device_id=device.id, labels={*device_labels})

    return device_registry.async_get(device.id)


@pytest.fixture
async def device_labels():
    """Mock device labels."""
    return const.TEST_DEVICE_LABELS


@pytest.fixture
async def device_name():
    """Return a device name."""
    return const.TEST_DEVICE_NAME


# Entity Fixtures


@pytest.fixture
async def entity_labels():
    """Mock entity labels."""
    return const.TEST_ENTITY_LABELS


@pytest.fixture
async def entity_id(entity_domain: str, entity_object_id: str):
    """Return an entity id."""
    return f"{entity_domain}.{entity_object_id}"


@pytest.fixture
async def entity_domain():
    """Return an entity domain."""
    return const.TEST_ENTITY_DOMAIN


@pytest.fixture
async def entity_object_id():
    """Return an entity name."""
    return const.TEST_ENTITY_OBJECT_ID_0


@pytest.fixture
async def entity_area_name():
    """Return an entity area name."""
    return const.TEST_ENTITY_AREA_NAME


@pytest.fixture
async def entity_floor_name():
    """Return an entity floor name."""
    return const.TEST_ENTITY_FLOOR_NAME


@pytest.fixture
async def entity_floor(
    floor_registry: FloorRegistry,
    entity_floor_name: str,
) -> FloorEntry | None:
    """Build a floor."""

    if entity_floor_name is None:
        return None

    if floor_registry.async_get_floor_by_name(entity_floor_name) is not None:
        msg = f"Floor {entity_floor_name} already exists"
        raise ValueError(msg)

    return floor_registry.async_create(name=entity_floor_name)


@pytest.fixture
async def entity_platform():
    """Return an entity platform."""
    return const.TEST_ENTITY_PLATFORM


@pytest.fixture
async def entity_area(
    area_registry: AreaRegistry,
    entity_area_name: str,
    entity_floor: FloorEntry,
) -> AreaEntry | None:
    """Build an area."""

    if entity_area_name is None:
        return None

    extra_settings = {}
    if entity_floor is not None:
        extra_settings["floor_id"] = entity_floor.floor_id

    if area_registry.async_get_area(entity_area_name) is not None:
        msg = f"Area {entity_area_name} already exists"
        raise ValueError(msg)

    return area_registry.async_create(name=entity_area_name, **extra_settings)


@pytest.fixture
async def attach_device():
    """Return whether to attach a device to an entity."""
    return True


@pytest.fixture
async def entity(
    config_entry: MockConfigEntry,
    entity_registry: EntityRegistry,
    entity_domain: str,
    entity_id: str,
    entity_object_id: str,
    entity_area: AreaEntry,
    entity_labels: list[str],
    entity_platform: str,
    device,
    attach_device: bool,
):
    """Mock an entity."""
    entity_registry.async_get_or_create(
        config_entry=config_entry,
        domain=entity_domain,
        unique_id=entity_id,
        suggested_object_id=entity_object_id,
        platform=entity_platform,
        original_device_class=const.TEST_ENTITY_DEVICE_CLASS,
    )

    if entity_labels is not None and len(entity_labels) > 0:
        entity_registry.async_update_entity(entity_id=entity_id, labels={*entity_labels})

    if entity_area is not None:
        entity_registry.async_update_entity(entity_id=entity_id, area_id=entity_area.id)

    if device is not None and attach_device:
        entity_registry.async_update_entity(entity_id=entity_id, device_id=device.id)

    return entity_registry.async_get(entity_id)


@pytest.fixture
async def state() -> str:
    """Return a state."""
    return const.TEST_ENTITY_STATE


@pytest.fixture
async def entity_state(
    entity_id: str,
    state: str,
    attributes: dict[str, Any],
    last_changed: str,
    last_updated: str,
) -> dict[str, Any]:
    """Return a state."""
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes,
        "last_changed": last_changed,
        "last_updated": last_updated,
    }

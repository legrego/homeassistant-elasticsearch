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
from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest import mock
from unittest.mock import patch

import pytest
from custom_components.elasticsearch.config_flow import ElasticFlowHandler
from custom_components.elasticsearch.const import DOMAIN as ES_DOMAIN
from custom_components.elasticsearch.es_gateway import (
    Elasticsearch7Gateway,
    Elasticsearch8Gateway,
)
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: F401
from pytest_homeassistant_custom_component.plugins import (  # noqa: F401
    aioclient_mock,
    enable_event_loop_debug,
    skip_stop_scripts,
    snapshot,
    verify_cleanup,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from tests import const

pytest_plugins = "pytest_homeassistant_custom_component"

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
    from typing import TYPE_CHECKING, Any

    from custom_components.elasticsearch.es_gateway import (
        ElasticsearchGateway,
    )
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.area_registry import AreaEntry, AreaRegistry
    from homeassistant.helpers.device_registry import DeviceRegistry
    from homeassistant.helpers.entity_registry import EntityRegistry
    from homeassistant.helpers.floor_registry import FloorEntry, FloorRegistry
    from homeassistant.loader import ComponentProtocol, Integration


@pytest.fixture(name="integration_setup")
async def mock_integration_setup(
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
async def running_integration(hass: HomeAssistant) -> Integration:
    """Set up the integration for testing."""

    return await async_get_integration(hass, ES_DOMAIN)


@pytest.fixture
async def component(hass: HomeAssistant, integration: Integration) -> ComponentProtocol:
    """Set up the component for testing."""

    return await integration.async_get_component()


# Archived Mocks


@contextmanager
def mock_es_aiohttp_client() -> Generator[AiohttpClientMocker, Any, Any]:
    """Context manager to mock aiohttp client."""
    mocker = AiohttpClientMocker()

    def create_session(*args, **kwargs):
        return mocker.create_session(get_running_loop())

    with mock.patch(
        "elasticsearch7._async.http_aiohttp.aiohttp.ClientSession",
        side_effect=create_session,
    ):
        yield mocker


@pytest.fixture
def es_aioclient_mock():
    """Fixture to mock aioclient calls."""
    with mock_es_aiohttp_client() as mock_session:
        yield mock_session


# This fixture enables loading custom integrations in all tests.
# Remove to enable selective use of this fixture
@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations) -> None:
    """Auto enable custom integrations."""
    return


# This fixture is used to prevent HomeAssistant from attempting to create and dismiss persistent
# notifications. These calls would fail without this fixture since the persistent_notification
# integration is never loaded during a test.
@pytest.fixture(name="skip_notifications", autouse=True)
def skip_notifications_fixture() -> Generator[Any, Any, Any]:
    """Skip notification calls."""
    with (
        patch("homeassistant.components.persistent_notification.async_create"),
        patch("homeassistant.components.persistent_notification.async_dismiss"),
    ):
        yield


@pytest.fixture
async def url() -> str:
    """Return a url."""
    return const.MOCK_ELASTICSEARCH_URL


@pytest.fixture
async def use_connection_monitor() -> bool:
    """Return whether to use the connection monitor."""
    return False


@pytest.fixture(params=[Elasticsearch7Gateway, Elasticsearch8Gateway])
async def uninitialized_gateway(
    hass: HomeAssistant,
    request: pytest.FixtureRequest,
    minimum_privileges: dict,
    use_connection_monitor: bool,
    url: str,
    username: str | None = None,
    password: str | None = None,
    api_key: str | None = None,
) -> AsyncGenerator[ElasticsearchGateway, Any]:
    """Return a gateway instance."""

    gateway_type: type[ElasticsearchGateway] = request.param

    # create an extra settings dict that only populates with username, password, or api_key when they are not None
    extra_settings: dict[str, Any] = {
        key: value
        for key, value in {
            "username": username,
            "password": password,
            "api_key": api_key,
        }.items()
        if value is not None
    }

    gateway = gateway_type(
        hass=hass,
        url=url,
        minimum_privileges=minimum_privileges,
        use_connection_monitor=use_connection_monitor,
        **extra_settings,
    )

    yield gateway

    if gateway._initialized:
        await gateway.stop()


@pytest.fixture
async def mock_cluster_info(
    major_version: int = 8,
    minor_version: int = 11,
):
    """Return a mock cluster info response body."""
    return getattr(const, f"CLUSTER_INFO_{major_version}DOT{minor_version}_RESPONSE_BODY")

@pytest.fixture
async def mock_test_connection():
    """Return whether to mock the test_connection method."""
    return True


@pytest.fixture
async def initialized_gateway(
    hass: HomeAssistant,
    request: pytest.FixtureRequest,
    minimum_privileges: dict,
    use_connection_monitor: bool,
    config_entry,
    mock_cluster_info: dict,
    uninitialized_gateway: ElasticsearchGateway,
    mock_test_connection: bool,
    url: str,
):
    """Return a gateway instance."""
    uninitialized_gateway._get_cluster_info = mock.AsyncMock(return_value=mock_cluster_info)

    if mock_test_connection:
        uninitialized_gateway.test_connection = mock.AsyncMock(return_value=True)

    await uninitialized_gateway.async_init(config_entry=config_entry)

    initialized_gateway = uninitialized_gateway

    return initialized_gateway  # noqa: RET504

    # We do not need to shutdown the gateway as it is shutdown by the uninitialized_gateway fixture


# @pytest.fixture
# async def initialized_integration(
#     hass: HomeAssistant,
#     config_entry: MockConfigEntry,
# ) -> MockConfigEntry:
#     """Set up the integration for testing."""
#     config_entry.add_to_hass(hass)

#     await hass.config_entries.async_setup(config_entry.entry_id)
#     await hass.async_block_till_done()

#     return config_entry


@pytest.fixture
async def uninitialized_integration(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> MockConfigEntry:
    """Set up the integration for testing."""
    config_entry.add_to_hass(hass)

    return config_entry


@pytest.fixture
async def data() -> dict:
    """Return a mock data dict."""
    return const.TEST_CONFIG_ENTRY_BASE_DATA


@pytest.fixture
async def options() -> dict:
    """Return a mock options dict."""
    return const.TEST_CONFIG_ENTRY_BASE_OPTIONS

@pytest.fixture
async def add_to_hass() -> bool:
    """Return whether to add the config entry to hass."""
    return True


@pytest.fixture
async def config_entry(
    hass: HomeAssistant,
    data: dict,
    options: dict,
    add_to_hass: bool,
    version: int = ElasticFlowHandler.VERSION,
) -> MockConfigEntry:
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

    return entry

    # Unload the config entry

    # await hass.config_entries.async_unload(entry.entry_id)


# Fixtures for a new_component
@pytest.fixture
async def new_component_domain() -> str:
    """Return a new component domain."""
    return const.TEST_ENTITY_DOMAIN


@pytest.fixture
async def new_component_config() -> dict:
    """Return a new component config."""
    return {
        const.TEST_ENTITY_DOMAIN: {
            const.TEST_ENTITY_OBJECT_ID_0: {},
            const.TEST_ENTITY_OBJECT_ID_1: {},
            const.TEST_ENTITY_OBJECT_ID_2: {},
            const.TEST_ENTITY_OBJECT_ID_3: {},
            const.TEST_ENTITY_OBJECT_ID_4: {},
        },
    }


@pytest.fixture
async def new_component(hass: HomeAssistant, new_component_domain: str, new_component_config: dict) -> None:
    """Mock a component in hass."""

    assert await async_setup_component(hass, new_component_domain, new_component_config)
    await hass.async_block_till_done()


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

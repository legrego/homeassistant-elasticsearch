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
from collections.abc import Generator
from contextlib import contextmanager, suppress
from http import HTTPStatus
from typing import TYPE_CHECKING
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientSession, TCPConnector, client_exceptions
from custom_components.elasticsearch.config_flow import ElasticFlowHandler
from custom_components.elasticsearch.const import DATASTREAM_METRICS_INDEX_TEMPLATE_NAME
from custom_components.elasticsearch.es_gateway_8 import Elasticsearch8Gateway, Gateway8Settings

# import custom_components.elasticsearch  # noqa: F401
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_URL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import json_dumps
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,  # noqa: F401
)
from pytest_homeassistant_custom_component.plugins import (  # noqa: F401
    aioclient_mock,
    # enable_event_loop_debug,
    skip_stop_scripts,
    snapshot,
    verify_cleanup,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from tests import const

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator
    from typing import Any

    from homeassistant.helpers.area_registry import AreaEntry, AreaRegistry
    from homeassistant.helpers.device_registry import DeviceRegistry
    from homeassistant.helpers.entity_registry import EntityRegistry
    from homeassistant.helpers.floor_registry import FloorEntry, FloorRegistry

MODULE = "custom_components.elasticsearch"


@pytest.fixture
def gateway_config() -> dict:
    """Mock Gateway configuration."""
    return {
        CONF_URL: const.TEST_CONFIG_ENTRY_DATA_URL,
        CONF_USERNAME: const.TEST_CONFIG_ENTRY_DATA_USERNAME,
        CONF_PASSWORD: const.TEST_CONFIG_ENTRY_DATA_PASSWORD,
        "verify_certs": True,
        "ca_certs": None,
        "request_timeout": 30,
        "minimum_version": None,
        "minimum_privileges": {},
    }


@pytest.fixture(
    params=[
        {
            "gateway_class": Elasticsearch8Gateway,
            "gateway_settings": Gateway8Settings,
        },
    ],
    ids=["es8"],
)
async def gateway(request, gateway_config):
    """Mock ElasticsearchGateway instance."""

    gateway_class = request.param["gateway_class"]
    gateway_settings_class = request.param["gateway_settings"]

    settings = gateway_settings_class(**gateway_config)

    gateway = gateway_class(gateway_settings=settings)

    with suppress(Exception):
        yield gateway

    await gateway.stop()


@pytest.fixture
async def initialized_gateway(gateway: Elasticsearch8Gateway):
    """Return an initialized ElasticsearchGateway."""
    gateway.ping = AsyncMock(return_value=True)
    gateway.info = AsyncMock(return_value=const.CLUSTER_INFO_8DOT14_RESPONSE_BODY)
    gateway.has_security = AsyncMock(return_value=True)
    gateway._has_required_privileges = AsyncMock(return_value=True)

    await gateway.async_init()

    if isinstance(gateway, Elasticsearch8Gateway):
        gateway.client._verified_elasticsearch = MagicMock(return_value=True)

    with suppress(Exception):
        yield gateway

    await gateway.stop()


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


@contextmanager
def mock_es_aiohttp_client():
    """Context manager to mock aiohttp client."""
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
        yield mocker


@pytest.fixture
def es_mock_builder() -> Generator[es_mocker, Any, None]:
    """Fixture to return a builder for mocking Elasticsearch calls."""
    with mock_es_aiohttp_client() as mock_session:
        yield es_mocker(mock_session)


@pytest.fixture
def es_aioclient_mock():
    """Fixture to mock aioclient calls."""
    with mock_es_aiohttp_client() as mock_session:
        yield mock_session


class es_mocker:
    """Mock builder for Elasticsearch integration tests."""

    mocker: AiohttpClientMocker
    base_url: str = const.TEST_CONFIG_ENTRY_DATA_URL

    def __init__(self, mocker):
        """Initialize the mock builder."""
        self.mocker = mocker

    def reset(self):
        """Reset the mock builder."""
        self.mocker.clear_requests()

        return self

    def get_calls(self):
        """Return the calls."""
        # each mock_call is a tuple of method, url, body, and headers

        return self.mocker.mock_calls

    def clear(self):
        """Clear the requests."""
        self.mocker.mock_calls.clear()

        return self

    def with_server_error(self, status, exc=None):
        """Mock Elasticsearch being unreachable."""
        if exc is None:
            self.mocker.get(f"{const.TEST_CONFIG_ENTRY_DATA_URL}", status=status)
        else:
            self.mocker.get(f"{const.TEST_CONFIG_ENTRY_DATA_URL}", exc=exc)

        return self

    def with_server_timeout(self):
        """Mock Elasticsearch being unreachable."""
        self.mocker.get(f"{const.TEST_CONFIG_ENTRY_DATA_URL}", exc=client_exceptions.ServerTimeoutError())
        return self

    def _add_fail_after(
        self, success: AiohttpClientMockResponse, failure: AiohttpClientMockResponse, fail_after
    ):
        if fail_after is None:
            self.mocker.request(
                url=success.url,
                method=success.method,
                status=success.status,
                content=success.response,
                headers=success.headers,
                exc=success.exc,
            )
            return self

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= fail_after:
                return failure

            return success

        self.mocker.request(success.method, f"{success.url}", side_effect=side_effect)

        return self

    def _as_elasticsearch_stateful(
        self, version_response: dict[str, Any], with_security: bool = True, fail_after=None
    ) -> es_mocker:
        """Mock Elasticsearch version."""

        self.base_url = (
            const.TEST_CONFIG_ENTRY_DATA_URL if with_security else const.TEST_CONFIG_ENTRY_DATA_URL_INSECURE
        )

        self._add_fail_after(
            success=AiohttpClientMockResponse(
                method="GET",
                url=self.base_url,
                headers={"x-elastic-product": "Elasticsearch"},
                json=version_response,
            ),
            failure=AiohttpClientMockResponse(
                method="GET",
                url=self.base_url,
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            ),
            fail_after=fail_after,
        )

        self.mocker.get(
            url=f"{self.base_url}/_xpack/usage",
            json={
                "security": {"available": True, "enabled": with_security},
            },
        )

        return self

    def as_elasticsearch_8_0(self, with_security: bool = True) -> es_mocker:
        """Mock Elasticsearch 8.0."""
        return self._as_elasticsearch_stateful(const.CLUSTER_INFO_8DOT0_RESPONSE_BODY, with_security)

    def as_elasticsearch_8_17(self, with_security: bool = True, fail_after=None) -> es_mocker:
        """Mock Elasticsearch 8.17."""
        return self._as_elasticsearch_stateful(
            const.CLUSTER_INFO_8DOT17_RESPONSE_BODY, with_security, fail_after=fail_after
        )

    def as_elasticsearch_8_14(self, with_security: bool = True):
        """Mock Elasticsearch 8.14."""

        return self._as_elasticsearch_stateful(const.CLUSTER_INFO_8DOT14_RESPONSE_BODY, with_security)

    def as_elasticsearch_serverless(self) -> es_mocker:
        """Mock Elasticsearch version."""

        self.base_url = const.TEST_CONFIG_ENTRY_DATA_URL

        self.mocker.get(
            f"{self.base_url}",
            status=200,
            json=const.CLUSTER_INFO_SERVERLESS_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
        )

        self.mocker.get(url=f"{self.base_url}/_xpack/usage", status=401)

        return self

    def with_incorrect_permissions(self):
        """Mock the user being properly authenticated."""
        self.mocker.post(
            f"{self.base_url}/_security/user/_has_privileges",
            status=200,
            json={
                "has_all_requested": False,
            },
        )

        return self

    def with_correct_permissions(self):
        """Mock the user being properly authenticated."""

        self.mocker.post(
            f"{self.base_url}/_security/user/_has_privileges",
            status=200,
            json={
                "has_all_requested": True,
            },
        )

        return self

    def with_untrusted_certificate(self):
        """Mock the user being properly authenticated."""

        class MockTLSError(client_exceptions.ClientConnectorCertificateError):
            """Mocks an TLS error caused by an untrusted certificate.

            This is imperfect, but gets the job done for now.
            """

            def __init__(self) -> None:
                self._conn_key = MagicMock()
                self._certificate_error = Exception("AHHHH")

        self.mocker.get(
            f"{self.base_url}",
            exc=MockTLSError,
        )

        return self

    def with_index_template(self, version=2):
        """Mock the user being properly authenticated."""

        # Mock index template setup
        self.mocker.get(
            f"{self.base_url}/_index_template/{DATASTREAM_METRICS_INDEX_TEMPLATE_NAME}",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={
                "index_templates": [{"name": "datastream_metrics", "index_template": {"version": version}}]
            },
        )

        return self

    def without_index_template(self):
        """Mock the user being properly authenticated."""

        # Mock index template setup
        self.mocker.get(
            f"{self.base_url}/_index_template/{DATASTREAM_METRICS_INDEX_TEMPLATE_NAME}",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={},
        )

        self.mocker.put(
            f"{self.base_url}/_index_template/{DATASTREAM_METRICS_INDEX_TEMPLATE_NAME}",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={},
        )
        return self

    def with_datastreams(self):
        """Mock the user being properly authenticated."""

        self.mocker.get(
            f"{self.base_url}/_data_stream/metrics-homeassistant.*",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={
                "data_streams": [
                    {
                        "name": "metrics-homeassistant.sensor-default",
                    },
                    {
                        "name": "metrics-homeassistant.counter-default",
                    },
                ]
            },
        )

        self.mocker.put(
            f"{self.base_url}/_data_stream/metrics-homeassistant.counter-default/_rollover",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={},
        )
        self.mocker.put(
            f"{self.base_url}/_data_stream/metrics-homeassistant.sensor-default/_rollover",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={},
        )

        return self

    def respond_to_bulk(self, status=200, fail_after=None):
        """Mock the user being properly authenticated."""

        self._add_fail_after(
            success=AiohttpClientMockResponse(
                method="PUT",
                url=f"{self.base_url}/_bulk",
                headers={"x-elastic-product": "Elasticsearch"},
                json={"errors": status == 200, "items": [], "took": 7},
            ),
            failure=AiohttpClientMockResponse(
                method="PUT",
                url=f"{self.base_url}/_bulk",
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            ),
            fail_after=fail_after,
        )

        return self


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
    return const.TEST_CONFIG_ENTRY_BASE_DATA


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

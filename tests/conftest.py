# type: ignore  # noqa: PGH003
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

import contextlib
from asyncio import get_running_loop
from collections.abc import AsyncGenerator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from unittest import mock
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import (  # noqa: F401
    MockConfigEntry,
    mock_config_flow,
    mock_integration,  # https://github.com/home-assistant/core/blob/dbd3147c9b5fa4c05bf9280133d3fa8824a9d934/tests/components/hardkernel/test_config_flow.py#L12
)

# We need to import these to make sure the fixtures are registered
from pytest_homeassistant_custom_component.plugins import (  # noqa: F401
    aioclient_mock,
    device_registry,
    enable_event_loop_debug,
    entity_registry,
    floor_registry,
    hass,
    hass_client,
    issue_registry,
    label_registry,
    skip_stop_scripts,
    snapshot,
    verify_cleanup,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.elasticsearch.config_flow import ElasticFlowHandler
from custom_components.elasticsearch.es_gateway import (
    Elasticsearch7Gateway,
    Elasticsearch8Gateway,
    ElasticsearchGateway,
)
from tests import const

pytest_plugins = "pytest_homeassistant_custom_component"


@contextmanager
def mock_es_aiohttp_client():
    """Context manager to mock aiohttp client."""
    mocker = AiohttpClientMocker()

    def create_session(*args, **kwargs):
        print(args)
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
def skip_notifications_fixture():
    """Skip notification calls."""
    with (
        patch("homeassistant.components.persistent_notification.async_create"),
        patch("homeassistant.components.persistent_notification.async_dismiss"),
    ):
        yield


class MockEntityState(State):
    """Mock entity state."""

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        state: str,
        attributes: map | None = None,
        last_changed: datetime | None = None,
        last_updated: datetime | None = None,
        validate_entity_id: bool | None = False,
    ) -> None:
        """Initialize the mock entity state."""
        if last_changed is None:
            last_changed = datetime.now()  # noqa: DTZ005

        if last_updated is None:
            last_updated = datetime.now()  # noqa: DTZ005

        self.hass = hass

        super().__init__(
            entity_id=entity_id,
            state=state,
            attributes=attributes,
            last_changed=last_changed,
            last_updated=last_updated,
            validate_entity_id=validate_entity_id,
        )

    def as_dict(self):
        """Return a dict representation of the State.

        Async friendly.

        To be used for JSON serialization.
        Ensures: state == State.from_dict(state.as_dict())
        """
        last_changed_isoformat = self.last_changed.isoformat()
        if self.last_changed == self.last_updated:
            last_updated_isoformat = last_changed_isoformat
        else:
            last_updated_isoformat = self.last_updated.isoformat()
        return {
            "entity_id": self.entity_id,
            "state": self.state,
            "attributes": self.attributes,
            "last_changed": last_changed_isoformat,
            "last_updated": last_updated_isoformat,
        }

    def to_publish(self):
        """Return a dict to publish."""
        return {
            "entity_id": self.entity_id,
            "new_state": self.state,
            "attributes": self.attributes,
        }

    async def add_to_hass(self):
        """Add the state to Homeassistant."""
        self.hass.states.async_set(**(self.to_publish()))

        await self.hass.async_block_till_done()



def mock_entity_state(hass: HomeAssistant) -> MockEntityState:
    """Mock an entity state in the state machine."""
    return MockEntityState()


def mock_gateway(hass: HomeAssistant) -> Elasticsearch7Gateway:
    """Mock an Elasticsearch gateway."""
    return mock.create_autospec(Elasticsearch7Gateway)


@pytest.fixture(params=[Elasticsearch7Gateway, Elasticsearch8Gateway])
async def uninitialized_gateway(
    hass: HomeAssistant,
    request: pytest.FixtureRequest,
    minimum_privileges: dict,
    username: str | None = None,
    password: str | None = None,
    api_key: str | None = None,
    use_connection_monitor: bool = False,
    url: str = "http://localhost:9200",
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
async def initialized_gateway(
    hass: HomeAssistant,
    request: pytest.FixtureRequest,
    minimum_privileges: dict,
    use_connection_monitor: bool,
    mock_config_entry,
    mock_cluster_info: dict,
    uninitialized_gateway: ElasticsearchGateway,
    mock_test_connection: bool = True,
    url: str = "http://localhost:9200",
):
    """Return a gateway instance."""
    with (
        mock.patch.object(
            uninitialized_gateway,
            "_get_cluster_info",
            return_value=mock_cluster_info,
        ),
        # Conditionally mock the connection test
        mock.patch.object(uninitialized_gateway, "test_connection", return_value=True)
        if mock_test_connection
        else contextlib.nullcontext(),
    ):
        await uninitialized_gateway.async_init(config_entry=mock_config_entry)

    initialized_gateway = uninitialized_gateway

    return initialized_gateway  # noqa: RET504

    # We do not need to shutdown the gateway as it is shutdown by the uninitialized_gateway fixture


@pytest.fixture
async def initialized_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> MockConfigEntry:
    """Set up the IPP integration for testing."""
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    return mock_config_entry


@pytest.fixture
async def uninitialized_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> MockConfigEntry:
    """Set up the IPP integration for testing."""
    mock_config_entry.add_to_hass(hass)

    return mock_config_entry


@pytest.fixture
async def data() -> AsyncGenerator[dict, Any]:
    """Return a mock data dict."""
    return {}


@pytest.fixture
async def options() -> AsyncGenerator[dict, Any]:
    """Return a mock options dict."""
    return {}


@pytest.fixture
async def mock_config_entry(
    hass: HomeAssistant,
    data: dict | None,
    options: dict | None,
    version: int = ElasticFlowHandler.VERSION,
    add_to_hass: bool = True,
) -> AsyncGenerator[MockConfigEntry, Any]:
    """Create a mock config entry and add it to hass."""

    if data is None:
        data = {}

    if options is None:
        options = {}

    entry = MockConfigEntry(
        title="ES Integration",
        domain="elasticsearch",
        data=data,
        options=options,
        version=version,
    )

    if add_to_hass:
        entry.add_to_hass(hass)

    yield entry

    # Unload the config entry
    del hass.config_entries._entries[entry.entry_id]

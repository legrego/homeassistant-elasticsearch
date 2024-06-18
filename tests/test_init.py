"""Tests for the Elasticsearch integration initialization."""

from collections.abc import Awaitable, Callable
from unittest import mock
from unittest.mock import AsyncMock

import custom_components.elasticsearch  # noqa: F401
import pytest
from custom_components.elasticsearch import (
    async_migrate_entry,
    async_setup_entry,
    async_unload_entry,
    migrate_data_and_options_to_version,
)
from custom_components.elasticsearch.config_flow import ElasticFlowHandler
from custom_components.elasticsearch.const import DOMAIN as ELASTIC_DOMAIN
from custom_components.elasticsearch.es_integration import ElasticIntegration
from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigFlow
from homeassistant.core import HomeAssistant
from homeassistant.loader import ComponentProtocol, Integration
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
)
from pytest_homeassistant_custom_component.common import mock_component as new_mock_component
from pytest_homeassistant_custom_component.common import (
    mock_config_flow as new_mock_config_flow,
)
from pytest_homeassistant_custom_component.common import mock_integration as new_mock_integration
from pytest_homeassistant_custom_component.common import (
    mock_platform as new_mock_platform,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from syrupy.assertion import SnapshotAssertion

from tests import const

MODULE = "custom_components.elasticsearch"


@pytest.fixture
def module():
    """Return the module."""
    return custom_components.elasticsearch


@pytest.fixture
async def mock_module(hass: HomeAssistant) -> MockModule:
    """Return a mock module useful for initializing a mock integration."""

    setup = {
        "domain": ELASTIC_DOMAIN,
        "async_setup_entry": AsyncMock(wraps=async_setup_entry),
        "async_unload_entry": AsyncMock(wraps=async_unload_entry),
        "async_migrate_entry": AsyncMock(wraps=async_migrate_entry),
    }

    return MockModule(**setup)


@pytest.fixture
async def mock_integration(hass: HomeAssistant, mock_module: MockModule, mock_config_flow) -> Integration:
    """Mock an integration which has the same root methods but does not have a config_flow.

    Use this to simplify mocking of the root methods of __init__.py.
    """

    return new_mock_integration(hass, mock_module, False)


@pytest.fixture
async def mock_platform(hass: HomeAssistant):
    """Set up the platform for testing."""
    return new_mock_platform(hass, f"{ELASTIC_DOMAIN}.config_flow")


class MockFlow(ConfigFlow):
    """Test flow."""


@pytest.fixture
async def mock_config_flow(hass: HomeAssistant, mock_platform):
    """Set up the config flow for testing."""

    with new_mock_config_flow(ELASTIC_DOMAIN, MockFlow):
        yield


@pytest.fixture
async def mock_component(hass: HomeAssistant, mock_integration: Integration) -> ComponentProtocol:
    """Set up the component for testing."""
    new_mock_component(hass, ELASTIC_DOMAIN)

    return await mock_integration.async_get_component()


class Test_Config_Migration:
    """Test the Elasticsearch integration configuration migrations."""

    def _test_config_data_options_migration_to_version(
        self,
        before_version: int,
        before_data: dict,
        before_options: dict,
        after_version: int,
        after_data: dict,
        after_options: dict,
        snapshot: SnapshotAssertion,
    ) -> bool:
        mock_entry = MockConfigEntry(
            unique_id="mock migration",
            domain=ELASTIC_DOMAIN,
            version=before_version,
            data=before_data,
            options=before_options,
            title="ES Config",
        )

        migrated_data, migrated_options, end_version = migrate_data_and_options_to_version(
            mock_entry,
            desired_version=after_version,
        )

        assert mock_entry

        assert migrated_data == after_data
        assert migrated_options == after_options

        assert end_version == after_version

        assert {
            "before_data": dict(mock_entry.data),
            "before_options": dict(mock_entry.options),
            "before_version": mock_entry.version,
            "after_data": dict(migrated_data),
            "after_options": dict(migrated_options),
            "after_version": end_version,
        } == snapshot

        return True

    @pytest.mark.asyncio
    async def test_config_migration_v1tov2(
        self,
        hass: HomeAssistant,
        snapshot: SnapshotAssertion,
    ):
        """Test config migration from v1."""

        assert self._test_config_data_options_migration_to_version(
            before_version=1,
            before_options={},
            before_data={
                "url": "http://migration-test:9200",
                "only_publish_changed": True,
            },
            after_version=2,
            snapshot=snapshot,
            after_options={},
            after_data={
                "url": "http://migration-test:9200",
                "publish_mode": "Any changes",
            },
        )

    @pytest.mark.asyncio
    async def test_config_migration_v2tov3(
        self,
        snapshot: SnapshotAssertion,
    ):
        """Test config migration from v2."""

        assert self._test_config_data_options_migration_to_version(
            before_version=2,
            before_options={},
            before_data={
                "url": "http://migration-test:9200",
                "health_sensor_enabled": True,
            },
            after_version=3,
            snapshot=snapshot,
            after_options={},
            after_data={"url": "http://migration-test:9200"},
        )

    @pytest.mark.asyncio
    async def test_config_migration_v3tov4(
        self,
        hass: HomeAssistant,
        snapshot: SnapshotAssertion,
    ):
        """Test config migration from v3."""

        assert self._test_config_data_options_migration_to_version(
            before_version=3,
            before_options={},
            before_data={
                "url": "http://migration-test:9200",
                "ilm_max_size": "10gb",
                "ilm_delete_after": "30d",
            },
            after_options={},
            after_data={
                "url": "http://migration-test:9200",
                "index_mode": "index",
            },
            after_version=4,
            snapshot=snapshot,
        )

    @pytest.mark.asyncio
    async def test_config_migration_v4tov5(
        self,
        hass: HomeAssistant,
        snapshot: SnapshotAssertion,
    ):
        """Test config migration from v4."""

        assert self._test_config_data_options_migration_to_version(
            before_version=4,
            before_options={},
            before_data={
                "url": "http://migration-test:9200",
                "publish_enabled": True,
                "publish_frequency": 60,
                "publish_mode": "Any changes",
                "excluded_domains": [],
                "excluded_entities": [],
                "included_domains": [],
                "included_entities": [],
                "datastream_name_prefix": "homeassistant",
                "datastream_namespace": "default",
                "datastream_type": "metrics",
            },
            after_options={
                "publish_mode": "Any changes",
                "excluded_domains": [],
                "excluded_entities": [],
                "included_domains": [],
                "included_entities": [],
                "publish_enabled": True,
                "publish_frequency": 60,
            },
            after_data={
                "url": "http://migration-test:9200",
            },
            after_version=5,
            snapshot=snapshot,
        )

    @pytest.mark.asyncio
    async def test_config_migration_v5tov6(
        self,
        hass: HomeAssistant,
        snapshot: SnapshotAssertion,
    ):
        """Test config migration from v4."""

        assert self._test_config_data_options_migration_to_version(
            before_version=5,
            before_options={
                "publish_mode": "All",
                "excluded_domains": [],
                "excluded_entities": [],
                "included_domains": [],
                "included_entities": [],
                "publish_enabled": True,
                "publish_frequency": 60,
                "ilm_enabled": True,
                "ilm_policy_name": "test policy",
                "index_format": "test format",
                "index_mode": "index",
            },
            before_data={
                "url": "http://migration-test:9200",
            },
            after_options={
                "excluded_domains": [],
                "excluded_entities": [],
                "included_domains": [],
                "included_entities": [],
                "publish_frequency": 60,
                "polling_frequency": 60,
                "change_detection_type": ["STATE", "ATTRIBUTE"],
            },
            after_data={
                "url": "http://migration-test:9200",
            },
            after_version=6,
            snapshot=snapshot,
        )

    @pytest.mark.asyncio
    async def test_config_migration_v1tov5(
        self,
        hass: HomeAssistant,
        snapshot: SnapshotAssertion,
    ):
        """Test config migration from v1."""

        assert self._test_config_data_options_migration_to_version(
            before_version=1,
            before_options={},
            before_data={
                "url": "http://migration-test:9200",
                "ilm_max_size": "10gb",
                "ilm_delete_after": "30d",
                "health_sensor_enabled": True,
                "only_publish_changed": True,
                "publish_enabled": True,
                "publish_frequency": 60,
                "excluded_domains": [],
                "excluded_entities": [],
                "included_domains": [],
                "included_entities": [],
                "publish_mode": "Any changes",
            },
            after_options={
                "publish_enabled": True,
                "publish_frequency": 60,
                "publish_mode": "Any changes",
                "excluded_domains": [],
                "excluded_entities": [],
                "included_domains": [],
                "included_entities": [],
            },
            after_data={
                "url": "http://migration-test:9200",
                "index_mode": "index",
            },
            after_version=5,
            snapshot=snapshot,
        )


class Test_Setup:
    """Test the Elasticsearch integration setup."""

    async def test_no_config_entry(self, hass: HomeAssistant) -> None:
        """Test initialization with no config entry."""

        assert await async_setup_component(hass, ELASTIC_DOMAIN, {}) is True

        assert ELASTIC_DOMAIN in hass.config.components

        await hass.async_block_till_done()


class Test_Public_Methods:
    """Test the public methods of the Elasticsearch integration initialization."""

    @pytest.fixture
    def block_async_init(self):
        """Block async init."""
        with mock.patch(
            f"{MODULE}.es_integration.ElasticIntegration.async_init",
            return_value=True,
        ):
            yield

    @pytest.fixture
    def block_init_async_init(self):
        """Block async init."""
        with (
            mock.patch(
                f"{MODULE}.es_integration.ElasticIntegration.__init__",
                return_value=None,
            ),
            mock.patch(
                f"{MODULE}.es_integration.ElasticIntegration.async_init",
                return_value=True,
            ),
        ):
            yield

    @pytest.fixture
    def block_shutdown(self):
        """Block async shutdown."""
        with mock.patch(
            f"{MODULE}.es_integration.ElasticIntegration.async_shutdown",
            return_value=True,
        ):
            yield

    @pytest.fixture(autouse=True)
    def add_to_hass(self):
        """Do not add to HASS so we can do it ourselves in these tests."""
        return False

    async def test_isolate_async_setup_entry(
        self,
        hass: HomeAssistant,
        mock_integration: Integration,
        integration_setup: Callable[[], Awaitable[bool]],
        config_entry: ConfigEntry,
    ) -> None:
        """Test setting up the integration."""

        assert config_entry.state is ConfigEntryState.NOT_LOADED

        assert len(config_entry.update_listeners) == 0

        # Mock the module to only test setup
        component: ComponentProtocol = mock_integration.get_component()

        component.async_unload_entry = AsyncMock(return_value=True)
        component.async_migrate_entry = AsyncMock(return_value=True)
        with (
            mock.patch(
                f"{MODULE}.es_integration.ElasticIntegration.__init__",
                return_value=None,
            ) as mock_integration_init,
            mock.patch(
                f"{MODULE}.es_integration.ElasticIntegration.async_init",
                return_value=True,
            ) as mock_integration_async_init,
        ):
            # Perform setup
            assert await integration_setup()

            # Ensure we loaded successfully
            assert config_entry.state is ConfigEntryState.LOADED

            # Ensure it attempted to initialize the integration
            assert mock_integration_init.called
            assert mock_integration_async_init.called

    async def test_async_setup_entry_no_init(
        self,
        hass: HomeAssistant,
        integration_setup: Callable[[], Awaitable[bool]],
        config_entry: ConfigEntry,
        block_init_async_init,
        block_shutdown,
    ) -> None:
        """Test setting up the integration."""
        assert config_entry.state is ConfigEntryState.NOT_LOADED

        assert await integration_setup()
        assert config_entry.state is ConfigEntryState.LOADED

        # Ensure the integration is saved into runtime_data
        assert config_entry.runtime_data is not None
        assert isinstance(config_entry.runtime_data, ElasticIntegration)

        assert await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()

        assert config_entry.state is ConfigEntryState.NOT_LOADED

    async def test_async_setup_entry_no_async_init(
        self,
        hass: HomeAssistant,
        integration_setup: Callable[[], Awaitable[bool]],
        config_entry: ConfigEntry,
        block_init_async_init,
        block_shutdown,
    ) -> None:
        """Test setting up the integration."""
        assert config_entry.state is ConfigEntryState.NOT_LOADED

        assert await integration_setup()
        assert config_entry.state is ConfigEntryState.LOADED

        # Ensure the integration is saved into runtime_data
        assert config_entry.runtime_data is not None
        assert isinstance(config_entry.runtime_data, ElasticIntegration)

        assert await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()

    async def test_isolate_async_unload_entry(
        self,
        hass: HomeAssistant,
        mock_integration: Integration,
        integration_setup: Callable[[], Awaitable[bool]],
        config_entry: MockConfigEntry,
    ) -> None:
        """Test unloading a mock integration through the registered config_entry."""

        # Mock the module to only test unload
        component: ComponentProtocol = mock_integration.get_component()

        component.async_setup_entry = AsyncMock(return_value=True)
        component.async_migrate_entry = AsyncMock(return_value=True)

        # Perform setup
        assert await integration_setup()

        assert config_entry.state is ConfigEntryState.LOADED

        # Mock the ES Integration Object stored in runtime_data
        setattr(config_entry, "runtime_data", AsyncMock(spec=ElasticIntegration))

        with mock.patch.object(
            config_entry.runtime_data, "async_shutdown", return_value=True
        ) as mock_shutdown:
            await hass.config_entries.async_unload(config_entry.entry_id)
            # assert await component.async_unload_entry(hass, config_entry)

            assert mock_shutdown.called

    async def test_isolate_async_migrate_entry_no_update(
        self,
        hass: HomeAssistant,
        mock_integration: Integration,
        integration_setup: Callable[[], Awaitable[bool]],
        config_entry: MockConfigEntry,
    ) -> None:
        """Test setting up the integration."""

        # Mock the module to only test unload
        component: ComponentProtocol = mock_integration.get_component()

        component.async_setup_entry = AsyncMock(return_value=True)
        component.async_unload_entry = AsyncMock(return_value=True)

        assert config_entry.state is ConfigEntryState.NOT_LOADED

        assert config_entry.version == ElasticFlowHandler.VERSION

        # Mock migrate_data_and_options_to_version and make sure it wasn't called during setup
        with mock.patch(
            f"{MODULE}.migrate_data_and_options_to_version", return_value=True
        ) as mock_migrate_config:
            # Perform setup
            assert await integration_setup()

            assert mock_migrate_config.called is False

            assert config_entry.state is ConfigEntryState.LOADED

            assert config_entry.version == ElasticFlowHandler.VERSION

    async def test_async_migrate_entry_failure(
        self,
        hass: HomeAssistant,
        mock_integration: Integration,
        integration_setup: Callable[[], Awaitable[bool]],
        config_entry: MockConfigEntry,
    ) -> None:
        """Test setting up the integration."""

        # Mock the module to only test unload
        component: ComponentProtocol = mock_integration.get_component()

        component.async_setup_entry = AsyncMock(return_value=True)
        component.async_unload_entry = AsyncMock(return_value=True)

        assert config_entry.state is ConfigEntryState.NOT_LOADED

        config_entry.version = ElasticFlowHandler.VERSION - 1

        # Mock migrate_data_and_options_to_version and make sure it wasn't called during setup
        with (
            mock.patch(
                f"{MODULE}.migrate_to_version_6",  # raise exception
                side_effect=Exception("Test Exception"),
            ) as mock_migrate_config_to_6,
            mock.patch.object(
                hass.config_entries,
                "async_update_entry",
                wraps=hass.config_entries.async_update_entry,
            ) as mock_async_update_entry,
        ):
            assert await integration_setup() is False

            mock_async_update_entry.assert_not_called()
            assert mock_migrate_config_to_6.called

            updated_config_entry = hass.config_entries.async_get_entry(config_entry.entry_id)
            assert updated_config_entry is not None

            assert updated_config_entry.state is ConfigEntryState.MIGRATION_ERROR

            assert updated_config_entry.version == config_entry.version

    async def test_async_migrate_entry_update(
        self,
        hass: HomeAssistant,
        mock_integration: Integration,
        integration_setup: Callable[[], Awaitable[bool]],
        config_entry: MockConfigEntry,
    ) -> None:
        """Test setting up the integration."""

        # Mock the module to only test unload
        component: ComponentProtocol = mock_integration.get_component()

        component.async_setup_entry = AsyncMock(return_value=True)
        component.async_unload_entry = AsyncMock(return_value=True)

        assert config_entry.state is ConfigEntryState.NOT_LOADED

        config_entry.version = ElasticFlowHandler.VERSION - 1

        # Mock migrate_data_and_options_to_version and make sure it wasn't called during setup
        with (
            mock.patch(
                f"{MODULE}.migrate_data_and_options_to_version",
                return_value=(config_entry.data, config_entry.options, ElasticFlowHandler.VERSION),
            ) as mock_migrate_config,
            mock.patch.object(
                hass.config_entries,
                "async_update_entry",
                wraps=hass.config_entries.async_update_entry,
            ) as mock_async_update_entry,
        ):
            assert await integration_setup()

            assert mock_async_update_entry.called
            assert mock_migrate_config.called

            updated_config_entry = hass.config_entries.async_get_entry(config_entry.entry_id)
            assert updated_config_entry is not None

            assert updated_config_entry.state is ConfigEntryState.LOADED

            assert updated_config_entry.version == ElasticFlowHandler.VERSION


class Test_Private_Methods:
    """Test the private methods of the Elasticsearch integration initialization."""

    @pytest.mark.parametrize("minimum_privileges", [None, {}])
    async def test_build_gateway_parameters(self, hass: HomeAssistant, minimum_privileges: dict | None):
        """Test build_gateway_parameters."""
        hass = mock.Mock()
        config_entry = mock.Mock()
        config_entry.data = {
            "url": "http://my_es_host:9200",
            "username": "admin",
            "password": "password",
            "verify_ssl": True,
            "ca_certs": "/path/to/ca_certs",
            "timeout": 30,
        }
        """ Test build_gateway_parameters."""

        parameters = ElasticIntegration.build_gateway_parameters(
            hass=hass,
            config_entry=config_entry,
            minimum_privileges=minimum_privileges,
        )

        assert parameters["hass"] == hass
        assert parameters["url"] == "http://my_es_host:9200"
        assert parameters["username"] == "admin"
        assert parameters["password"] == "password"  # noqa: S105
        assert parameters["verify_certs"] is True
        assert parameters["ca_certs"] == "/path/to/ca_certs"
        assert parameters["request_timeout"] == 30
        assert parameters["minimum_privileges"] == minimum_privileges


class Test_Common_Failures_e2e:
    """Test the common failures that users run into when initializing the integration."""

    async def test_unsupported_es_version(
        self, hass: HomeAssistant, integration_setup, es_aioclient_mock: AiohttpClientMocker, config_entry
    ):
        """Test the scenario where the Elasticsearch version is unsupported."""

        es_aioclient_mock.get(
            f"{const.MOCK_ELASTICSEARCH_URL}/",
            status=200,
            json=const.CLUSTER_INFO_UNSUPPORTED_RESPONSE_BODY,
        )

        assert config_entry.state is ConfigEntryState.NOT_LOADED

        # Load the Config Entry
        assert await integration_setup() is False

        assert config_entry.version == ElasticFlowHandler.VERSION

        assert config_entry.state is ConfigEntryState.SETUP_RETRY
        assert config_entry.reason == "Unsupported version of Elasticsearch"

    async def test_authentication_failure(
        self, hass: HomeAssistant, integration_setup, es_aioclient_mock: AiohttpClientMocker, config_entry
    ):
        """Test the scenario where the Elasticsearch version is unsupported."""

        es_aioclient_mock.get(
            f"{const.MOCK_ELASTICSEARCH_URL}/",
            status=401,
        )

        assert config_entry.state is ConfigEntryState.NOT_LOADED

        # Load the Config Entry
        assert await integration_setup() is False

        assert config_entry.version == ElasticFlowHandler.VERSION

        assert config_entry.state is ConfigEntryState.SETUP_ERROR
        assert config_entry.reason == "Error connecting to Elasticsearch"

    async def test_connection_failure(
        self, hass: HomeAssistant, integration_setup, es_aioclient_mock: AiohttpClientMocker, config_entry
    ):
        """Test the scenario where the Elasticsearch version is unsupported."""

        es_aioclient_mock.get(
            f"{const.MOCK_ELASTICSEARCH_URL}/",
            status=500,
        )

        assert config_entry.state is ConfigEntryState.NOT_LOADED

        # Load the Config Entry
        assert await integration_setup() is False

        assert config_entry.version == ElasticFlowHandler.VERSION

        assert config_entry.state is ConfigEntryState.SETUP_RETRY
        assert config_entry.reason == "Error connecting to Elasticsearch"


# Replace the following old tests


# @pytest.mark.asyncio
# async def test_unsupported_version(hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker) -> None:
#     """Test component setup with an unsupported version."""
#     es_url = "http://unsupported-version:9200"

#     mock_es_initialization(es_aioclient_mock, url=es_url, mock_unsupported_version=True)

#     mock_entry = MockConfigEntry(
#         unique_id="test_unsupported_version",
#         domain=ELASTIC_DOMAIN,
#         version=3,
#         data={"url": es_url, "use_connection_monitor": False},
#         options=build_new_options(),
#         title="ES Config",
#     )

#     entry = await _setup_config_entry(hass, mock_entry)

#     assert entry.state == ConfigEntryState.SETUP_RETRY
#     assert entry.reason == "Unsupported Elasticsearch version detected"


# async def test_reauth_setup_entry(hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker) -> None:
#     """Test reauth flow triggered by setup entry."""

#     es_url = "http://authentication-error:9200"

#     mock_es_initialization(
#         es_aioclient_mock,
#         url=es_url,
#         mock_authentication_error=True,
#     )

#     mock_entry = MockConfigEntry(
#         unique_id="test_authentication_error",
#         domain=ELASTIC_DOMAIN,
#         version=3,
#         data={
#             "url": es_url,
#             "username": "username",
#             "password": "password",
#         },
#         options=build_new_options(),
#         title="ES Config",
#     )

#     entry = await _setup_config_entry(hass, mock_entry)

#     assert entry.state == ConfigEntryState.SETUP_ERROR
#     assert entry.reason == "Missing or invalid credentials"

#     flows = hass.config_entries.flow.async_progress()
#     assert len(flows) == 1

#     flow = flows[0]
#     assert flow.get("step_id") == "basic_auth"
#     assert flow.get("handler") == ELASTIC_DOMAIN

#     assert "context" in flow
#     assert flow["context"].get("source") == SOURCE_REAUTH
#     assert flow["context"].get("entry_id") == entry.entry_id


# @pytest.mark.asyncio
# async def test_connection_error(hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker) -> None:
#     """Test component setup with an unsupported version."""
#     es_url = "http://connection-error:9200"

#     mock_es_initialization(es_aioclient_mock, url=es_url, mock_connection_error=True)

#     mock_entry = MockConfigEntry(
#         unique_id="test_connection_error",
#         domain=ELASTIC_DOMAIN,
#         version=5,
#         data={"url": es_url, "use_connection_monitor": False},
#         title="ES Config",
#     )

#     entry = await _setup_config_entry(hass, mock_entry)

#     assert entry.state == ConfigEntryState.SETUP_RETRY
#     assert entry.reason == "Exception during component initialization"

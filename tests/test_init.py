"""Tests for the Elasticsearch integration initialization."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock
from unittest.mock import AsyncMock

import pytest
from custom_components.elasticsearch import (
    async_migrate_entry,
    async_setup_entry,
    async_unload_entry,
    migrate_data_and_options_to_version,
)
from custom_components.elasticsearch.config_flow import ElasticFlowHandler
from custom_components.elasticsearch.const import DATASTREAM_METRICS_INDEX_TEMPLATE_NAME
from custom_components.elasticsearch.const import DOMAIN as ELASTIC_DOMAIN
from custom_components.elasticsearch.es_integration import ElasticIntegration
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState, ConfigFlow
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,  # noqa: F401
    MockModule,
)
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

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.loader import ComponentProtocol, Integration

MODULE = "custom_components.elasticsearch"


@pytest.fixture
async def flow():
    """Set up the config flow for testing."""

    class MockFlow(ConfigFlow):
        """Test flow."""

    return MockFlow


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
async def mock_platform(hass: HomeAssistant):
    """Set up the platform for testing."""
    return new_mock_platform(hass, f"{ELASTIC_DOMAIN}.config_flow")


@pytest.fixture
def config_flow(mock_platform, flow):
    """Set up the Elastic Integration config flow."""
    with new_mock_config_flow(ELASTIC_DOMAIN, flow):
        yield


@pytest.fixture
async def mock_integration(hass: HomeAssistant, config_flow, mock_module: MockModule) -> Integration:
    """Mock an integration which has the same root methods but does not have a config_flow.

    Use this to simplify mocking of the root methods of __init__.py.
    """

    return new_mock_integration(hass, mock_module, False)


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
        """Test config migration from v5."""

        # Publishing On
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

        # Polling Off, State Changes only
        assert self._test_config_data_options_migration_to_version(
            before_version=5,
            before_options={
                "publish_mode": "State changes",
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
                "polling_frequency": 0,
                "change_detection_type": ["STATE"],
            },
            after_data={
                "url": "http://migration-test:9200",
            },
            after_version=6,
            snapshot=snapshot,
        )

    @pytest.mark.asyncio
    async def test_config_migration_v6tov7(
        self,
        hass: HomeAssistant,
        snapshot: SnapshotAssertion,
    ):
        """Test config migration from v6."""

        assert self._test_config_data_options_migration_to_version(
            before_version=6,
            before_options={
                "excluded_domains": [],
                "excluded_entities": [],
                "included_domains": [],
                "included_entities": [],
                "publish_frequency": 60,
                "polling_frequency": 0,
                "change_detection_type": ["STATE"],
            },
            before_data={
                "url": "http://migration-test:9200",
            },
            after_options={
                "include_targets": False,
                "exclude_targets": False,
                "targets_to_include": {},
                "targets_to_exclude": {},
                "publish_frequency": 60,
                "tags": [],
                "polling_frequency": 0,
                "change_detection_type": ["state"],
            },
            after_data={
                "url": "http://migration-test:9200",
            },
            after_version=7,
            snapshot=snapshot,
        )

        # Migrate Exclusions
        assert self._test_config_data_options_migration_to_version(
            before_version=6,
            before_options={
                "excluded_domains": [],
                "excluded_entities": ["tomato"],
                "included_domains": [],
                "included_entities": ["potato"],
                "publish_frequency": 60,
                "polling_frequency": 0,
                "change_detection_type": ["STATE"],
            },
            before_data={
                "url": "http://migration-test:9200",
            },
            after_options={
                "include_targets": True,
                "exclude_targets": True,
                "targets_to_include": {"entity_id": ["potato"]},
                "targets_to_exclude": {"entity_id": ["tomato"]},
                "publish_frequency": 60,
                "polling_frequency": 0,
                "tags": [],
                "change_detection_type": ["state"],
            },
            after_data={
                "url": "http://migration-test:9200",
            },
            after_version=7,
            snapshot=snapshot,
        )

    @pytest.mark.asyncio
    async def test_config_migration_v1tov7(
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
                "include_targets": False,
                "exclude_targets": False,
                "targets_to_include": {},
                "targets_to_exclude": {},
                "publish_frequency": 60,
                "tags": [],
                "polling_frequency": 0,
                "change_detection_type": ["state", "attribute"],
            },
            after_data={
                "url": "http://migration-test:9200",
            },
            after_version=7,
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

        config_entry.version = 5

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


class Test_Common_e2e:
    """Test a full integration setup and execution."""

    @pytest.fixture
    async def options(self) -> dict:
        """Return a mock options dict."""
        return const.TEST_CONFIG_ENTRY_DEFAULT_OPTIONS

    @pytest.fixture(autouse=True)
    def fix_system_info(self):
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

    @pytest.fixture
    def freeze_time(self, freezer: FrozenDateTimeFactory):
        """Freeze time so we can properly assert on payload contents."""

        frozen_time = dt_util.parse_datetime(const.MOCK_NOON_APRIL_12TH_2023)
        if frozen_time is None:
            msg = "Invalid date string"
            raise ValueError(msg)

        freezer.move_to(frozen_time)

        return freezer

    async def test_setup_to_publish(
        self,
        hass: HomeAssistant,
        integration_setup,
        es_aioclient_mock: AiohttpClientMocker,
        config_entry,
        entity,
        device,
        freeze_time,
        snapshot: SnapshotAssertion,
    ):
        """Test the full integration setup and execution."""

        # Mock cluster checks
        es_aioclient_mock.get(
            f"{const.TEST_CONFIG_ENTRY_DATA_URL}/",
            json=const.CLUSTER_INFO_8DOT14_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
        )

        # Mock the user has the required privileges
        es_aioclient_mock.post(
            const.TEST_CONFIG_ENTRY_DATA_URL + "/_security/user/_has_privileges",
            json={"has_all_requested": True},
        )

        # Mock index template setup
        es_aioclient_mock.get(
            f"{const.TEST_CONFIG_ENTRY_DATA_URL}/_index_template/{DATASTREAM_METRICS_INDEX_TEMPLATE_NAME}",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={},
        )

        es_aioclient_mock.put(
            f"{const.TEST_CONFIG_ENTRY_DATA_URL}/_index_template/{DATASTREAM_METRICS_INDEX_TEMPLATE_NAME}",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={},
        )

        # Mock the bulk request
        es_aioclient_mock.put(
            const.TEST_CONFIG_ENTRY_DATA_URL + "/_bulk",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={
                "took": 7,
                "errors": False,
                "items": [],
            },
        )

        # Load the Config Entry
        assert await integration_setup() is True

        assert config_entry.state is ConfigEntryState.LOADED

        # Queue an entity state change
        hass.states.async_set(entity.entity_id, "value")

        # Wait for the publish task to run
        await hass.async_block_till_done()

        es_aioclient_mock.mock_calls.clear()

        # Manually invoke a publish
        await config_entry.runtime_data._pipeline_manager._publish()

        # Ensure the bulk request was made (and a ping was performed)
        assert es_aioclient_mock.call_count == 2

        ping = es_aioclient_mock.mock_calls[0]
        assert ping[0] == "GET"

        bulk_call = es_aioclient_mock.mock_calls[1]
        assert bulk_call[0] == "PUT"
        assert bulk_call[2] == snapshot

    class Test_Config_Migration:
        """TEst config migration e2e."""

        @pytest.fixture
        def version(self) -> int:
            """Return the version to migrate from."""
            return 1

        def data(self) -> dict:
            """Return the data to migrate from."""
            return {
                "url": "http://migration-test:9200",
                "only_publish_changed": True,
            }

        def options(self) -> dict:
            """Return the options to migrate from."""
            return {}

        async def test_setup_v1_to_publish(
            self,
            hass: HomeAssistant,
            integration_setup,
            es_aioclient_mock: AiohttpClientMocker,
            data,
            options,
            version,
            config_entry,
            entity,
            device,
            freeze_time,
            snapshot: SnapshotAssertion,
        ):
            """Test the full integration setup and execution."""

            # Mock cluster checks
            es_aioclient_mock.get(
                f"{const.TEST_CONFIG_ENTRY_DATA_URL}/",
                json=const.CLUSTER_INFO_8DOT14_RESPONSE_BODY,
                headers={"x-elastic-product": "Elasticsearch"},
            )

            # Mock the user has the required privileges
            es_aioclient_mock.post(
                const.TEST_CONFIG_ENTRY_DATA_URL + "/_security/user/_has_privileges",
                json={"has_all_requested": True},
            )

            # Mock index template setup
            es_aioclient_mock.get(
                f"{const.TEST_CONFIG_ENTRY_DATA_URL}/_index_template/{DATASTREAM_METRICS_INDEX_TEMPLATE_NAME}",
                status=200,
                headers={"x-elastic-product": "Elasticsearch"},
                json={},
            )

            es_aioclient_mock.put(
                f"{const.TEST_CONFIG_ENTRY_DATA_URL}/_index_template/{DATASTREAM_METRICS_INDEX_TEMPLATE_NAME}",
                status=200,
                headers={"x-elastic-product": "Elasticsearch"},
                json={},
            )

            # Mock the bulk request
            es_aioclient_mock.put(
                const.TEST_CONFIG_ENTRY_DATA_URL + "/_bulk",
                status=200,
                headers={"x-elastic-product": "Elasticsearch"},
                json={"errors": False, "items": []},
            )

            # Load the Config Entry
            assert await integration_setup() is True

            assert config_entry.state is ConfigEntryState.LOADED

            assert {
                "data": config_entry.data,
                "options": config_entry.options,
            } == snapshot

            # Queue an entity state change
            hass.states.async_set(entity.entity_id, "value")

            # Wait for the publish task to run
            await hass.async_block_till_done()

            es_aioclient_mock.mock_calls.clear()

            # Manually invoke a publish
            await config_entry.runtime_data._pipeline_manager._publish()

            # Ensure the bulk request was made (and a ping was performed)
            assert es_aioclient_mock.call_count == 2

            ping = es_aioclient_mock.mock_calls[0]
            assert ping[0] == "GET"

            bulk_call = es_aioclient_mock.mock_calls[1]
            assert bulk_call[0] == "PUT"
            assert bulk_call[2] == snapshot

    class Test_Pipeline_Settings:
        """Test Pipeline Settings."""

        @pytest.fixture
        def block_async_init(self):
            """Block async init."""
            with mock.patch(
                f"{MODULE}.es_integration.ElasticIntegration.async_init",
                return_value=True,
            ):
                yield

        @pytest.fixture(autouse=True)
        async def options(self) -> dict:
            """Return a mock options dict."""
            return {
                const.CONF_CHANGE_DETECTION_ENABLED: True,
                const.CONF_CHANGE_DETECTION_TYPE: ["STATE", "ATTRIBUTE"],
                const.CONF_TAGS: ["tags"],
                const.CONF_POLLING_FREQUENCY: 60,
                const.CONF_PUBLISH_FREQUENCY: 60,
                const.CONF_INCLUDE_TARGETS: True,
                const.CONF_EXCLUDE_TARGETS: True,
                const.CONF_TARGETS_TO_INCLUDE: {
                    "entity_id": [
                        "sensor.include_100b_baker_st_2g",
                        "sensor.include_u6_enterprise_entryway_memory_utilization",
                    ],
                    "device_id": ["include_cd454a1722a83415862249840b60b981"],
                    "area_id": ["include_bedroom"],
                    "label_id": ["include_test_label"],
                },
                const.CONF_TARGETS_TO_EXCLUDE: {
                    "entity_id": [
                        "sensor.exclude_100b_baker_st_2g",
                        "sensor.exclude_u6_enterprise_entryway_memory_utilization",
                    ],
                    "device_id": ["exclude_cd454a1722a83415862249840b60b981"],
                    "area_id": ["exclude_bedroom"],
                    "label_id": ["exclude_test_label"],
                },
            }

        async def test_config_entry_to_pipeline_settings(
            self,
            hass: HomeAssistant,
            block_async_init,
            integration_setup,
            es_aioclient_mock: AiohttpClientMocker,
            options,
            config_entry,
            snapshot: SnapshotAssertion,
        ):
            """Test the full integration setup and execution."""

            # Mock cluster checks
            es_aioclient_mock.get(
                f"{const.TEST_CONFIG_ENTRY_DATA_URL}/",
                json=const.CLUSTER_INFO_8DOT14_RESPONSE_BODY,
                headers={"x-elastic-product": "Elasticsearch"},
            )

            # Mock the user has the required privileges
            es_aioclient_mock.post(
                const.TEST_CONFIG_ENTRY_DATA_URL + "/_security/user/_has_privileges",
                json={"has_all_requested": True},
            )

            # Load the Config Entry
            assert await integration_setup() is True

            assert config_entry.state is ConfigEntryState.LOADED

            # Ensure the pipeline settings are correct
            updated_config_entry = hass.config_entries.async_get_entry(config_entry.entry_id)

            if updated_config_entry is None:
                raise ValueError("Config Entry not found")

            pipeline_settings = updated_config_entry.runtime_data._pipeline_manager._settings

            assert pipeline_settings == snapshot


class Test_Common_Failures_e2e:
    """Test the common failures that users run into when initializing the integration."""

    async def test_authentication_failure(
        self, hass: HomeAssistant, integration_setup, es_aioclient_mock: AiohttpClientMocker, config_entry
    ):
        """Test the scenario where we fail authentication."""

        es_aioclient_mock.get(
            f"{const.TEST_CONFIG_ENTRY_DATA_URL}/",
            status=401,
        )

        assert config_entry.state is ConfigEntryState.NOT_LOADED

        # Load the Config Entry
        assert await integration_setup() is False

        assert config_entry.version == ElasticFlowHandler.VERSION

        assert config_entry.state is ConfigEntryState.SETUP_ERROR

    async def test_connection_failure(
        self, hass: HomeAssistant, integration_setup, es_aioclient_mock: AiohttpClientMocker, config_entry
    ):
        """Test the scenario where we fail to connect to Elasticsearch."""

        es_aioclient_mock.get(
            f"{const.TEST_CONFIG_ENTRY_DATA_URL}/",
            status=500,
            headers={"x-elastic-product": "Elasticsearch"},
        )

        assert config_entry.state is ConfigEntryState.NOT_LOADED

        # Load the Config Entry
        assert await integration_setup() is False

        assert config_entry.version == ElasticFlowHandler.VERSION

        assert config_entry.state is ConfigEntryState.SETUP_RETRY
        assert config_entry.reason == "Error connecting to Elasticsearch: 500"

    async def test_unsupported_version(
        self, hass: HomeAssistant, integration_setup, es_aioclient_mock: AiohttpClientMocker, config_entry
    ):
        """Test the scenario where the Elasticsearch version is unsupported."""

        es_aioclient_mock.get(
            f"{const.TEST_CONFIG_ENTRY_DATA_URL}/",
            json=const.CLUSTER_INFO_8DOT0_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
        )

        assert config_entry.state is ConfigEntryState.NOT_LOADED

        # Load the Config Entry
        assert await integration_setup() is False

        assert config_entry.version == ElasticFlowHandler.VERSION

        assert config_entry.state is ConfigEntryState.SETUP_RETRY
        assert config_entry.reason == "Elasticsearch version is not supported. Minimum version: (8, 14)"

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
from custom_components.elasticsearch.const import DOMAIN as ELASTIC_DOMAIN
from custom_components.elasticsearch.errors import (
    CannotConnect,
    ESIntegrationException,
    InvalidCACertificate,
    UnsupportedVersion,
)
from custom_components.elasticsearch.es_integration import ElasticIntegration
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState, ConfigFlow
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,  # noqa: F401
    MockModule,
)
from pytest_homeassistant_custom_component.common import (
    mock_config_flow as new_mock_config_flow,
)
from pytest_homeassistant_custom_component.common import (
    mock_integration as new_mock_integration,
)
from pytest_homeassistant_custom_component.common import (
    mock_platform as new_mock_platform,
)
from syrupy.assertion import SnapshotAssertion

from tests import const

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.loader import ComponentProtocol, Integration

MODULE = "custom_components.elasticsearch"


@pytest.fixture(name="mock_flow")
async def flow_fixture():
    """Set up the config flow for testing."""

    class MockFlow(ConfigFlow):
        """Test flow."""

        # Home Assistant refuses to set up entries newer than the handler's version.
        VERSION = ElasticFlowHandler.VERSION

    return MockFlow


@pytest.fixture(name="mock_module")
async def mock_module_fixture(hass: HomeAssistant) -> MockModule:
    """Return a mock module useful for initializing a mock integration."""

    setup = {
        "domain": ELASTIC_DOMAIN,
        "async_setup_entry": AsyncMock(wraps=async_setup_entry),
        "async_unload_entry": AsyncMock(wraps=async_unload_entry),
        "async_migrate_entry": AsyncMock(wraps=async_migrate_entry),
    }

    return MockModule(**setup)


@pytest.fixture(name="mock_platform")
async def mock_platform_fixture(hass: HomeAssistant):
    """Set up the platform for testing."""
    return new_mock_platform(hass, f"{ELASTIC_DOMAIN}.config_flow")


@pytest.fixture
def _config_flow(mock_platform, mock_flow):
    """Set up the Elastic Integration config flow."""
    with new_mock_config_flow(ELASTIC_DOMAIN, mock_flow):
        yield


@pytest.fixture(name="mock_integration")
async def mock_integration_fixture(hass: HomeAssistant, _config_flow, mock_module: MockModule) -> Integration:
    """Mock an integration which has the same root methods but does not have a config_flow.

    Use this to simplify mocking of the root methods of __init__.py.
    """

    return new_mock_integration(hass, mock_module, False)


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
        """Test config data and options migration scenarios."""
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

        assert snapshot == {
            "before_data": dict(mock_entry.data),
            "before_options": dict(mock_entry.options),
            "before_version": mock_entry.version,
            "after_data": dict(migrated_data),
            "after_options": dict(migrated_options),
            "after_version": end_version,
        }

        return True

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
                "api_key": "",
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

        # Polling Off, State Changes only
        assert self._test_config_data_options_migration_to_version(
            before_version=5,
            before_options={
                "publish_mode": None,
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
                "change_detection_type": ["STATE", "ATTRIBUTE"],
            },
            after_data={
                "url": "http://migration-test:9200",
            },
            after_version=6,
            snapshot=snapshot,
        )

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

        assert self._test_config_data_options_migration_to_version(
            before_version=1,
            before_options={},
            before_data={
                "url": "http://migration-test:9200",
                "ilm_max_size": "10gb",
                "ilm_delete_after": "30d",
                "health_sensor_enabled": True,
                "only_publish_changed": False,
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
                "polling_frequency": 60,
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


async def test_floor_targets_reach_pipeline_settings(hass: HomeAssistant) -> None:
    """Test that floor targets from the config entry end up in the pipeline settings."""
    config_entry = MockConfigEntry(
        domain=ELASTIC_DOMAIN,
        options={
            **const.CONFIG_ENTRY_DEFAULT_OPTIONS,
            "targets_to_include": {"floor_id": ["included_floor"]},
            "targets_to_exclude": {"floor_id": ["excluded_floor"]},
        },
    )

    parameters = ElasticIntegration.build_pipeline_manager_parameters(
        hass=hass, gateway=mock.MagicMock(), config_entry=config_entry
    )

    assert parameters["settings"].included_floors == ["included_floor"]
    assert parameters["settings"].excluded_floors == ["excluded_floor"]


class Test_Public_Methods:
    """Test the public methods of the Elasticsearch integration initialization."""

    @pytest.fixture
    def _block_async_init(self):
        """Block async init."""
        with mock.patch(
            f"{MODULE}.es_integration.ElasticIntegration.async_init",
            return_value=True,
        ):
            yield

    @pytest.fixture
    def _block_init_async_init(self):
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
    def _block_shutdown(self):
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
        _block_init_async_init,
        _block_shutdown,
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
        _block_init_async_init,
        _block_shutdown,
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

    async def test_async_setup_entry_async_init_integration_exception(
        self,
        hass: HomeAssistant,
        integration_setup: Callable[[], Awaitable[bool]],
        config_entry: ConfigEntry,
        _block_shutdown,
    ) -> None:
        """Test setting up the integration."""
        with (
            mock.patch(
                f"{MODULE}.es_integration.ElasticIntegration.__init__",
                return_value=None,
            ),
            mock.patch(
                f"{MODULE}.es_integration.ElasticIntegration.async_init",
                side_effect=ESIntegrationException,
            ),
        ):
            assert config_entry.state is ConfigEntryState.NOT_LOADED

            assert await integration_setup() is False

            assert config_entry.state is ConfigEntryState.SETUP_RETRY

    async def test_async_setup_entry_async_init_exception(
        self,
        hass: HomeAssistant,
        integration_setup: Callable[[], Awaitable[bool]],
        config_entry: ConfigEntry,
        _block_shutdown,
    ) -> None:
        """Test setting up the integration."""
        with (
            mock.patch(
                f"{MODULE}.es_integration.ElasticIntegration.__init__",
                return_value=None,
            ),
            mock.patch(
                f"{MODULE}.es_integration.ElasticIntegration.async_init",
                side_effect=Exception,
            ),
        ):
            assert config_entry.state is ConfigEntryState.NOT_LOADED

            assert await integration_setup() is False

            assert config_entry.state is ConfigEntryState.SETUP_ERROR

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
        hass.config_entries.async_update_entry(config_entry, version=5)

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

        hass.config_entries.async_update_entry(config_entry, version=ElasticFlowHandler.VERSION - 1)

        # Mock migrate_data_and_options_to_version and make sure it wasn't called during setup
        with (
            mock.patch(
                f"{MODULE}.migrate_data_and_options_to_version",
                return_value=(
                    config_entry.data,
                    config_entry.options,
                    ElasticFlowHandler.VERSION,
                ),
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

    @pytest.fixture(autouse=True, name="freeze_time")
    def auto_freeze_time_fixture(self, freeze_time: FrozenDateTimeFactory):
        """Freeze time so we can properly assert on payload contents."""
        return freeze_time

    class Test_Pipeline_Settings:
        """Test Pipeline Settings."""

        @pytest.fixture
        def _block_async_init(self):
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

        # We want to test config entry to pipeline settings without initializing the integration
        async def test_config_entry_to_pipeline_settings(self, hass, options, config_entry, snapshot):
            """Test the full integration setup and execution."""
            integration = ElasticIntegration(hass, config_entry)

            assert snapshot == {
                "gateway": integration._gateway.settings.to_dict(),
                "pipeline": integration._pipeline_manager._settings,
            }


class Test_Gateway_Parameters:
    """Test how a config entry's TLS settings reach the gateway."""

    def test_verification_defaults_to_on(self):
        """Test that an entry without TLS settings verifies the server's certificate and hostname."""
        entry = MockConfigEntry(domain=ELASTIC_DOMAIN, data={"url": const.CONFIG_ENTRY_DATA_URL})

        settings = ElasticIntegration.build_gateway_parameters(entry)

        assert settings.verify_certs is True
        assert settings.verify_hostname is True

    def test_saved_settings_are_used(self):
        """Test that an entry's TLS settings are passed on unchanged."""
        entry = MockConfigEntry(
            domain=ELASTIC_DOMAIN,
            data={
                "url": const.CONFIG_ENTRY_DATA_URL,
                "verify_ssl": False,
                "ssl_verify_hostname": False,
                "ssl_ca_path": "/ssl/ca.crt",
            },
        )

        settings = ElasticIntegration.build_gateway_parameters(entry)

        assert settings.verify_certs is False
        assert settings.verify_hostname is False
        assert settings.ca_certs == "/ssl/ca.crt"


class Test_Setup_Failures:
    """Test how failures during setup are reported to Home Assistant."""

    @pytest.fixture
    def entry(self, hass):
        """Return a config entry that is ready to be set up."""
        entry = MockConfigEntry(
            domain=ELASTIC_DOMAIN,
            version=ElasticFlowHandler.VERSION,
            data=const.CONFIG_ENTRY_BASE_DATA,
            options=const.CONFIG_ENTRY_DEFAULT_OPTIONS,
        )
        entry.add_to_hass(hass)
        return entry

    @pytest.mark.parametrize(
        ("exception", "expected_state"),
        [
            (CannotConnect, ConfigEntryState.SETUP_RETRY),
            (ESIntegrationException, ConfigEntryState.SETUP_RETRY),
            (UnsupportedVersion, ConfigEntryState.SETUP_ERROR),
            (InvalidCACertificate, ConfigEntryState.SETUP_ERROR),
            (RuntimeError, ConfigEntryState.SETUP_ERROR),
        ],
    )
    async def test_setup_failure_state(self, hass, entry, exception, expected_state):
        """Test that only temporary failures are retried."""
        with mock.patch(f"{MODULE}.es_integration.ElasticIntegration.async_init", side_effect=exception):
            await hass.config_entries.async_setup(entry.entry_id)

        assert entry.state is expected_state

    async def test_unexpected_failure_closes_the_gateway(self, hass, entry):
        """Test that the client is closed when setup fails unexpectedly."""
        integration = ElasticIntegration(hass, entry)
        integration._gateway = mock.AsyncMock(spec=integration._gateway, cluster_uuid=None)
        integration._datastream_manager = mock.AsyncMock(spec=integration._datastream_manager)
        integration._datastream_manager.async_init.side_effect = RuntimeError

        with pytest.raises(RuntimeError):
            await integration.async_init()

        integration._gateway.stop.assert_awaited_once()


class Test_Unique_Id_Backfill:
    """Test giving existing config entries a unique ID."""

    @pytest.fixture
    def entry(self, hass):
        """Return a config entry created before unique IDs were assigned."""
        entry = MockConfigEntry(
            domain=ELASTIC_DOMAIN,
            data=const.CONFIG_ENTRY_BASE_DATA,
            options=const.CONFIG_ENTRY_DEFAULT_OPTIONS,
            title="this entry",
        )
        entry.add_to_hass(hass)
        return entry

    @staticmethod
    def backfill(hass, entry, cluster_uuid, log=None):
        """Run the backfill against a gateway connected to the given cluster."""
        integration = ElasticIntegration(hass, entry, log) if log else ElasticIntegration(hass, entry)
        integration._gateway = mock.MagicMock(cluster_uuid=cluster_uuid)
        integration._backfill_unique_id()

    async def test_backfill(self, hass, entry):
        """Test that an entry with no unique ID takes the UUID of its cluster."""
        self.backfill(hass, entry, const.CLUSTER_UUID)

        assert entry.unique_id == const.CLUSTER_UUID

    async def test_backfill_unknown_uuid(self, hass, entry):
        """Test that nothing changes when the cluster can't report a UUID."""
        self.backfill(hass, entry, None)

        assert entry.unique_id is None

    async def test_backfill_keeps_existing_unique_id(self, hass):
        """Test that an entry's unique ID is never replaced."""
        entry = MockConfigEntry(
            domain=ELASTIC_DOMAIN,
            unique_id="existing",
            data=const.CONFIG_ENTRY_BASE_DATA,
            options=const.CONFIG_ENTRY_DEFAULT_OPTIONS,
        )
        entry.add_to_hass(hass)

        self.backfill(hass, entry, const.CLUSTER_UUID)

        assert entry.unique_id == "existing"

    async def test_backfill_existing_duplicate_keeps_working(self, hass, entry):
        """Test that the second entry for a cluster warns and is left without a unique ID."""
        other = MockConfigEntry(domain=ELASTIC_DOMAIN, unique_id=const.CLUSTER_UUID, title="other entry")
        other.add_to_hass(hass)
        log = mock.MagicMock()

        self.backfill(hass, entry, const.CLUSTER_UUID, log)

        assert entry.unique_id is None
        assert other.unique_id == const.CLUSTER_UUID
        log.warning.assert_called_once()

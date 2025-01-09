"""Tests for the Elasticsearch integration initialization."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock

import pytest
from custom_components.elasticsearch.config_flow import ElasticFlowHandler
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,  # noqa: F401
)
from syrupy.assertion import SnapshotAssertion

from tests import const

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

MODULE = "custom_components.elasticsearch"


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
def freeze_time(freezer: FrozenDateTimeFactory):
    """Freeze time so we can properly assert on payload contents."""

    frozen_time = dt_util.parse_datetime(const.MOCK_NOON_APRIL_12TH_2023)
    if frozen_time is None:
        msg = "Invalid date string"
        raise ValueError(msg)

    freezer.move_to(frozen_time)

    return freezer


class Test_Common_e2e:
    """Test a full integration setup and execution."""

    class Test_Normal_Configuration:
        """Test a full integration setup and execution."""

        @pytest.fixture
        async def options(self) -> dict:
            """Return a mock options dict."""
            return const.TEST_CONFIG_ENTRY_DEFAULT_OPTIONS

        async def test_setup_to_publish(
            self,
            hass: HomeAssistant,
            integration_setup,
            config_entry,
            entity,
            device,
            es_mock_builder,
            snapshot: SnapshotAssertion,
        ):
            """Test the full integration setup and execution."""

            es_mock_builder.as_elasticsearch_8_17().with_correct_permissions().without_index_template().respond_to_bulk(
                status=200
            )

            # Queue an entity state change
            hass.states.async_set(entity.entity_id, "value")

            # Load the Config Entry
            assert await integration_setup() is True
            assert config_entry.state is ConfigEntryState.LOADED

            assert es_mock_builder.mocker.call_count == 9
            assert es_mock_builder.mocker.mock_calls == snapshot

        @pytest.mark.parametrize("status_code", [403, 404, 500])
        async def test_setup_to_publish_error(
            self,
            hass: HomeAssistant,
            integration_setup,
            config_entry,
            entity,
            device,
            es_mock_builder,
            status_code,
            snapshot: SnapshotAssertion,
        ):
            """Test the full integration setup and execution."""

            es_mock_builder.as_elasticsearch_8_17().with_correct_permissions().without_index_template().respond_to_bulk(
                status=status_code
            )

            # Queue an entity state change
            hass.states.async_set(entity.entity_id, "value")

            # Load the Config Entry
            assert await integration_setup() is True
            assert config_entry.state is ConfigEntryState.LOADED

            assert es_mock_builder.mocker.call_count == 9
            assert es_mock_builder.mocker.mock_calls == snapshot

        async def test_setup_authentication_failure(
            self, hass: HomeAssistant, integration_setup, es_mock_builder, config_entry
        ):
            """Test the scenario where we fail authentication during setup."""

            es_mock_builder.as_elasticsearch_8_17().with_incorrect_permissions()

            assert await integration_setup() is False

            assert config_entry.version == ElasticFlowHandler.VERSION

            assert config_entry.state is ConfigEntryState.SETUP_ERROR
            assert config_entry.reason == "could not authenticate"

        async def test_setup_server_error(
            self, hass: HomeAssistant, integration_setup, es_mock_builder, config_entry
        ):
            """Test the scenario where we fail a connection during setup."""

            es_mock_builder.with_server_error(status=500)

            assert await integration_setup() is False

            assert config_entry.version == ElasticFlowHandler.VERSION

            assert config_entry.state is ConfigEntryState.SETUP_RETRY
            assert config_entry.reason == "Error connecting to Elasticsearch: 500"

        async def test_setup_server_timeout(
            self, hass: HomeAssistant, integration_setup, es_mock_builder, config_entry
        ):
            """Test the scenario where we fail a connection during setup."""

            es_mock_builder.with_server_timeout()

            assert await integration_setup() is False

            assert config_entry.version == ElasticFlowHandler.VERSION

            assert config_entry.state is ConfigEntryState.SETUP_RETRY
            assert config_entry.reason == "Connection timeout connecting to Elasticsearch"

        async def test_setup_tls_error(
            self, hass: HomeAssistant, integration_setup, es_mock_builder, config_entry
        ):
            """Test the scenario where we fail a connection during setup."""

            es_mock_builder.with_untrusted_certificate()

            assert await integration_setup() is False

            assert config_entry.version == ElasticFlowHandler.VERSION

            assert config_entry.state is ConfigEntryState.SETUP_RETRY
            assert config_entry.reason == "Untrusted certificate connecting to Elasticsearch"

        async def test_setup_unsupported_error(
            self, hass: HomeAssistant, integration_setup, es_mock_builder, config_entry
        ):
            """Test the scenario where we fail a connection during setup."""

            es_mock_builder.as_elasticsearch_8_0()

            assert await integration_setup() is False

            assert config_entry.version == ElasticFlowHandler.VERSION

            assert config_entry.state is ConfigEntryState.SETUP_RETRY
            assert config_entry.reason == "Elasticsearch version is not supported. Minimum version: (8, 14)"

    class Test_Publish_Disabled:
        """Test a full integration setup and execution with publishing disabled."""

        @pytest.fixture
        async def options(self) -> dict:
            """Return a mock options dict."""
            return const.TEST_CONFIG_ENTRY_BASE_OPTIONS

        async def test_setup_to_publish_disabled(
            self,
            hass: HomeAssistant,
            integration_setup,
            config_entry,
            entity,
            device,
            es_mock_builder,
            snapshot: SnapshotAssertion,
        ):
            """Test the full integration setup and execution."""

            es_mock_builder.as_elasticsearch_8_17().with_correct_permissions().without_index_template().respond_to_bulk(
                status=200
            )

            # Queue an entity state change
            hass.states.async_set(entity.entity_id, "value")

            # Load the Config Entry
            assert await integration_setup() is True
            assert config_entry.state is ConfigEntryState.LOADED

            assert es_mock_builder.mocker.call_count == 7

    class Test_Legacy_To_Current:
        """Test config migration e2e."""

        @pytest.fixture
        def version(self) -> int:
            """Return the version to migrate from."""
            return 1

        @pytest.fixture
        def data(self) -> dict:
            """Return the data to migrate from."""
            return {
                "url": const.TEST_CONFIG_ENTRY_DATA_URL,
                "only_publish_changed": False,
                "publish_mode": "Any changes",
                "publish_frequency": 60,
            }

        @pytest.fixture
        def options(self) -> dict:
            """Return the options to migrate from."""
            return {}

        async def test_setup_v1_to_publish(
            self,
            hass: HomeAssistant,
            integration_setup,
            es_mock_builder,
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

            es_mock_builder.as_elasticsearch_8_17().with_correct_permissions().without_index_template().respond_to_bulk(
                status=200
            )

            # Queue an entity state change
            hass.states.async_set(entity.entity_id, "value")

            # Load the Config Entry
            assert await integration_setup() is True
            assert config_entry.state is ConfigEntryState.LOADED

            assert es_mock_builder.mocker.call_count == 9

            assert snapshot == {
                "data": config_entry.data,
                "options": config_entry.options,
                "mock_calls": es_mock_builder.mocker.mock_calls,
            }

    # async def test_setup_to_publish_ping_500_error(
    #     self,
    #     hass: HomeAssistant,
    #     integration_setup,
    #     es_aioclient_mock: AiohttpClientMocker,
    #     config_entry,
    #     entity,
    #     device,
    #     freeze_time,
    #     snapshot: SnapshotAssertion,
    # ):
    #     """Test the full integration setup and execution."""

    #     # Mock cluster checks
    #     es_aioclient_mock.get(
    #         f"{const.TEST_CONFIG_ENTRY_DATA_URL}/",
    #         json=const.CLUSTER_INFO_8DOT14_RESPONSE_BODY,
    #         headers={"x-elastic-product": "Elasticsearch"},
    #     )

    #     es_aioclient_mock.get(
    #         url=f"{const.TEST_CONFIG_ENTRY_DATA_URL}/_xpack/usage",
    #         json={
    #             "security": {"available": True, "enabled": True},
    #         },
    #     )

    #     # Mock the user has the required privileges
    #     es_aioclient_mock.post(
    #         const.TEST_CONFIG_ENTRY_DATA_URL + "/_security/user/_has_privileges",
    #         json={"has_all_requested": True},
    #     )

    #     # Mock index template setup
    #     es_aioclient_mock.get(
    #         f"{const.TEST_CONFIG_ENTRY_DATA_URL}/_index_template/{DATASTREAM_METRICS_INDEX_TEMPLATE_NAME}",
    #         status=200,
    #         headers={"x-elastic-product": "Elasticsearch"},
    #         json={},
    #     )

    #     es_aioclient_mock.put(
    #         f"{const.TEST_CONFIG_ENTRY_DATA_URL}/_index_template/{DATASTREAM_METRICS_INDEX_TEMPLATE_NAME}",
    #         status=200,
    #         headers={"x-elastic-product": "Elasticsearch"},
    #         json={},
    #     )

    #     # Load the Config Entry
    #     assert await integration_setup() is True

    #     assert config_entry.state is ConfigEntryState.LOADED

    #     # Queue an entity state change
    #     hass.states.async_set(entity.entity_id, "value")

    #     # Wait for the publish task to run
    #     await hass.async_block_till_done()

    #     es_aioclient_mock.mock_calls.clear()

    #     # Mock cluster checks
    #     es_aioclient_mock.get(
    #         f"{const.TEST_CONFIG_ENTRY_DATA_URL}/",
    #         status=500,
    #         headers={"x-elastic-product": "Elasticsearch"},
    #     )

    #     # Manually invoke a publish
    #     config_entry.runtime_data._pipeline_manager._logger.debug = mock.Mock()
    #     await config_entry.runtime_data._pipeline_manager._publish()

    #     # Ensure the bulk request was made (and a ping was performed)
    #     assert es_aioclient_mock.call_count == 1

    #     ping = es_aioclient_mock.mock_calls[0]
    #     assert ping[0] == "GET"

    #     config_entry.runtime_data._pipeline_manager._logger.debug.assert_called_with(
    #         "Unknown error while publishing documents.",
    #         exc_info=True,
    #     )

"""Tests for the Elasticsearch integration initialization."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock
from unittest.mock import MagicMock

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


def strip_headers_from_mock_calls(mock_calls):
    """Strip headers from mock calls."""
    # mock calls are a 4 item tuple, return a 3 item tuple

    return [(call[0], call[1], call[2]) for call in mock_calls]


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
            return const.TEST_CONFIG_ENTRY_FAST_PUBLISH_OPTIONS

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
            assert strip_headers_from_mock_calls(es_mock_builder.mocker.mock_calls) == snapshot

            # Queue an entity state change and check that it is published with item level reporting
            hass.states.async_set(entity.entity_id, "value2")

            config_entry.runtime_data._gateway._logger.error = MagicMock()
            config_entry.runtime_data._gateway._logger.info = MagicMock()
            await config_entry.runtime_data._pipeline_manager._publisher.publish()

            assert es_mock_builder.mocker.call_count == 11
            config_entry.runtime_data._gateway._logger.error.assert_not_called()

            assert {
                "request": strip_headers_from_mock_calls(es_mock_builder.mocker.mock_calls),
                "info": config_entry.runtime_data._gateway._logger.info.call_args.args,
            } == snapshot

        async def test_setup_to_publish_ping_error(
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

            # create an async side effect function that returns

            es_mock_builder.as_elasticsearch_8_17(
                fail_after=5
            ).with_correct_permissions().without_index_template().respond_to_bulk(status=200)

            # Queue an entity state change
            hass.states.async_set(entity.entity_id, "value")

            # Load the Config Entry
            assert await integration_setup() is True
            assert config_entry.state is ConfigEntryState.LOADED

            assert es_mock_builder.mocker.call_count == 9

            await config_entry.runtime_data._pipeline_manager._publisher.publish()

            assert es_mock_builder.mocker.call_count == 10

            assert strip_headers_from_mock_calls(es_mock_builder.mocker.mock_calls) == snapshot

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
            assert strip_headers_from_mock_calls(es_mock_builder.mocker.mock_calls) == snapshot

        async def test_setup_to_bulk_item_level_error(
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

            es_mock_builder.as_elasticsearch_8_17().with_correct_permissions().without_index_template().respond_to_bulk_with_item_level_error()

            # Queue an entity state change
            hass.states.async_set(entity.entity_id, "value")

            # Load the Config Entry
            assert await integration_setup() is True
            assert config_entry.state is ConfigEntryState.LOADED

            config_entry.runtime_data._gateway._logger.error = MagicMock()
            config_entry.runtime_data._gateway._logger.info = MagicMock()

            es_mock_builder.clear()

            # Queue an entity state change
            hass.states.async_set(entity.entity_id, "value2")

            # invoke a publish
            await config_entry.runtime_data._pipeline_manager._publisher.publish()

            config_entry.runtime_data._gateway._logger.info.assert_not_called()
            assert {
                "request": strip_headers_from_mock_calls(es_mock_builder.mocker.mock_calls),
                "error": config_entry.runtime_data._gateway._logger.error.call_args.args,
            } == snapshot

        async def test_setup_missing_authentication(
            self, hass: HomeAssistant, integration_setup, es_mock_builder, config_entry
        ):
            """Test the scenario where we fail authentication during setup."""

            es_mock_builder.without_authentication()

            assert await integration_setup() is False

            assert config_entry.version == ElasticFlowHandler.VERSION

            assert config_entry.state is ConfigEntryState.SETUP_ERROR
            assert (
                config_entry.reason
                == "Error retrieving cluster info from Elasticsearch. Authentication error connecting to Elasticsearch (type=security_exception; reason=missing authentication credentials for REST request [/?pretty])"
            )

        async def test_setup_authorization_failure(
            self, hass: HomeAssistant, integration_setup, es_mock_builder, config_entry
        ):
            """Test the scenario where we fail authorization during setup."""

            es_mock_builder.as_elasticsearch_8_17().with_incorrect_permissions()

            assert await integration_setup() is False

            assert config_entry.version == ElasticFlowHandler.VERSION

            assert config_entry.state is ConfigEntryState.SETUP_ERROR
            assert config_entry.reason == "could not authenticate"

        async def test_setup_fake_elasticsearch_error(
            self, hass: HomeAssistant, integration_setup, es_mock_builder, config_entry
        ):
            """Test the scenario where we are not connecting to an authentic Elasticsearch endpoint."""

            es_mock_builder.as_fake_elasticsearch()

            assert await integration_setup() is False

            assert config_entry.version == ElasticFlowHandler.VERSION

            assert config_entry.state is ConfigEntryState.SETUP_RETRY
            assert (
                config_entry.reason
                == "Error retrieving cluster info from Elasticsearch. Unsupported product error connecting to Elasticsearch"
            )

        async def test_setup_server_error(
            self, hass: HomeAssistant, integration_setup, es_mock_builder, config_entry
        ):
            """Test the scenario where we fail a connection during setup."""

            es_mock_builder.with_server_error(status=500)

            assert await integration_setup() is False

            assert config_entry.version == ElasticFlowHandler.VERSION

            assert config_entry.state is ConfigEntryState.SETUP_RETRY
            assert (
                config_entry.reason
                == "Error retrieving cluster info from Elasticsearch. Error in request to Elasticsearch: 500"
            )

        async def test_setup_server_timeout(
            self, hass: HomeAssistant, integration_setup, es_mock_builder, config_entry
        ):
            """Test the scenario where we fail a connection during setup."""

            es_mock_builder.with_server_timeout()

            assert await integration_setup() is False

            assert config_entry.version == ElasticFlowHandler.VERSION

            assert config_entry.state is ConfigEntryState.SETUP_RETRY
            assert (
                config_entry.reason
                == "Error retrieving cluster info from Elasticsearch. Connection timeout connecting to Elasticsearch"
            )

        async def test_setup_tls_error(
            self, hass: HomeAssistant, integration_setup, es_mock_builder, config_entry
        ):
            """Test the scenario where we fail a connection during setup."""

            es_mock_builder.with_selfsigned_certificate()

            assert await integration_setup() is False

            assert config_entry.version == ElasticFlowHandler.VERSION

            assert config_entry.state is ConfigEntryState.SETUP_RETRY
            assert (
                config_entry.reason
                == "Error retrieving cluster info from Elasticsearch. Could not complete TLS Handshake. Cannot connect to host mock_es_integration:9200 ssl:True [SSLCertVerificationError: ()]"
            )

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
                "mock_calls": strip_headers_from_mock_calls(es_mock_builder.mocker.mock_calls),
            }

"""Test Config Flow."""
from unittest.mock import MagicMock

import aiohttp
import pytest
from homeassistant import data_entry_flow
from homeassistant.config_entries import SOURCE_USER
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.elasticsearch.const import DOMAIN
from tests.conftest import mock_es_aiohttp_client
from tests.test_util.es_startup_mocks import mock_es_initialization


@pytest.mark.asyncio
async def test_no_auth_flow(hass: HomeAssistantType, es_aioclient_mock):
    """Test user config flow with minimum fields."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_MENU
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"next_step_id": "no_auth"}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "no_auth"

    es_url = "http://minimum-fields:9200"

    mock_es_initialization(
        es_aioclient_mock,
        url=es_url,
        mock_health_check=True,
        mock_index_creation=True,
        mock_template_setup=True,
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": es_url}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result["title"] == es_url
    assert result["data"]["url"] == es_url
    assert result["data"]["username"] is None
    assert result["data"]["password"] is None
    assert result["data"]["ssl_ca_path"] is None
    assert result["data"]["verify_ssl"] is True
    assert result["data"]["publish_enabled"] is True
    assert "health_sensor_enabled" not in result["data"]


@pytest.mark.asyncio
async def test_no_auth_flow_unsupported_version(hass: HomeAssistantType, es_aioclient_mock):
    """Test user config flow with minimum fields."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_MENU
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"next_step_id": "no_auth"}
    )

    es_url = "http://minimum-fields:9200"

    mock_es_initialization(es_aioclient_mock, url=es_url, mock_unsupported_version=True)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": es_url}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "no_auth"
    assert result["errors"]["base"] == "unsupported_version"


@pytest.mark.asyncio
async def test_no_auth_flow_with_tls_error(hass: HomeAssistantType, es_aioclient_mock):
    """Test user config flow with config that forces TLS configuration."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_MENU
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"next_step_id": "no_auth"}
    )

    es_url = "https://untrusted-connection:9200"

    class MockSSLError(aiohttp.client_exceptions.ClientConnectorCertificateError):
        """Mocks an SSL error caused by an untrusted certificate.

        This is imperfect, but gets the job done for now.
        """

        def __init__(self):
            self._conn_key = MagicMock()
            self._certificate_error = Exception("AHHHH")
            return

    es_aioclient_mock.get(es_url, exc=MockSSLError)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": es_url}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"]["base"] == "untrusted_connection"
    assert result["step_id"] == "no_auth"
    assert "data" not in result


@pytest.mark.asyncio
async def test_flow_fails_es_unavailable(hass: HomeAssistantType, es_aioclient_mock):
    """Test user config flow fails if connection cannot be established."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_MENU
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"next_step_id": "no_auth"}
    )

    es_url = "http://unavailable-host:9200"

    es_aioclient_mock.get(es_url, exc=aiohttp.ClientError)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": es_url}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"]["base"] == "cannot_connect"
    assert result["step_id"] == "no_auth"
    assert "data" not in result


@pytest.mark.asyncio
async def test_flow_fails_unauthorized(hass: HomeAssistantType, es_aioclient_mock):
    """Test user config flow fails if connection cannot be established."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_MENU
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"next_step_id": "no_auth"}
    )

    es_url = "http://needs-auth:9200"

    es_aioclient_mock.get(es_url, status=401)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": es_url}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"]["base"] == "invalid_basic_auth"
    assert result["step_id"] == "no_auth"
    assert "data" not in result

@pytest.mark.asyncio
async def test_basic_auth_flow(hass: HomeAssistantType, es_aioclient_mock):
    """Test user config flow with minimum fields."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_MENU
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"next_step_id": "basic_auth"}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "basic_auth"

    es_url = "http://basic-auth-flow:9200"

    mock_es_initialization(
        es_aioclient_mock,
        url=es_url,
        mock_health_check=True,
        mock_index_creation=True,
        mock_template_setup=True,
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": es_url, "username": "hass_writer", "password": "changeme"}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result["title"] == es_url
    assert result["data"]["url"] == es_url
    assert result["data"]["username"] == "hass_writer"
    assert result["data"]["password"] == "changeme"
    assert result["data"]["api_key"] is None
    assert result["data"]["ssl_ca_path"] is None
    assert result["data"]["verify_ssl"] is True
    assert result["data"]["publish_enabled"] is True
    assert "health_sensor_enabled" not in result["data"]

@pytest.mark.asyncio
async def test_api_key_flow(hass: HomeAssistantType, es_aioclient_mock):
    """Test user config flow with minimum fields."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_MENU
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"next_step_id": "api_key"}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "api_key"

    es_url = "http://api_key-flow:9200"

    mock_es_initialization(
        es_aioclient_mock,
        url=es_url,
        mock_health_check=True,
        mock_index_creation=True,
        mock_template_setup=True,
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": es_url, "api_key": "ABC123=="}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result["title"] == es_url
    assert result["data"]["url"] == es_url
    assert result["data"]["username"] is None
    assert result["data"]["password"] is None
    assert result["data"]["api_key"] == "ABC123=="
    assert result["data"]["ssl_ca_path"] is None
    assert result["data"]["verify_ssl"] is True
    assert result["data"]["publish_enabled"] is True
    assert "health_sensor_enabled" not in result["data"]

@pytest.mark.asyncio
async def test_api_key_flow_fails_unauthorized(hass: HomeAssistantType, es_aioclient_mock):
    """Test user config flow fails if connection cannot be established."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_MENU
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"next_step_id": "api_key"}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "api_key"

    es_url = "http://api_key-unauthorized-flow:9200"

    es_aioclient_mock.get(es_url, status=401)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": es_url, "api_key": "ABC123=="}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"]["base"] == "invalid_api_key"
    assert result["step_id"] == "api_key"
    assert "data" not in result

@pytest.mark.asyncio
async def test_config_migration_v1(hass: HomeAssistantType, es_aioclient_mock):
    """Test config migration from v1."""
    es_url = "http://migration-v1-test:9200"

    mock_es_initialization(
        es_aioclient_mock,
        url=es_url,
        mock_health_check=True,
        mock_index_creation=True,
        mock_template_setup=True,
    )

     # Create mock entry with version 1
    mock_entry = MockConfigEntry(
        unique_id="mock unique id v1",
        domain=DOMAIN,
        version=1,
        data={
            "url": es_url,
            "only_publish_changed": True
        },
        title="ES Config",
    )

    # Set it up
    mock_entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {}) is True
    await hass.async_block_till_done()

    # Verify publish mode has been set correctly

    expected_config = {
        "url": es_url,
        "publish_mode": "Any changes"
    }

    updated_entry = hass.config_entries.async_get_entry(mock_entry.entry_id)
    assert updated_entry
    assert updated_entry.version == 3
    assert updated_entry.data == expected_config

@pytest.mark.asyncio
async def test_config_migration_v2(hass: HomeAssistantType, es_aioclient_mock):
    """Test config migration from v2."""
    es_url = "http://migration-v2-test:9200"

    mock_es_initialization(
        es_aioclient_mock,
        url=es_url,
        mock_health_check=True,
        mock_index_creation=True,
        mock_template_setup=True,
    )

     # Create mock entry with version 1
    mock_entry = MockConfigEntry(
        unique_id="mock unique id v2",
        domain=DOMAIN,
        version=2,
        data={
            "url": es_url,
            "health_sensor_enabled": True
        },
        title="ES Config",
    )

    # Set it up
    mock_entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {}) is True
    await hass.async_block_till_done()

    # Verify health sensor has been removed

    expected_config = {
        "url": es_url,
    }

    updated_entry = hass.config_entries.async_get_entry(mock_entry.entry_id)
    assert updated_entry
    assert updated_entry.version == 3
    assert updated_entry.data == expected_config

@pytest.mark.asyncio
async def test_options_flow(
    hass: HomeAssistantType, es_aioclient_mock, event_loop
) -> None:
    """Test options config flow."""

    es_url = "http://localhost:9200"

    mock_es_initialization(
        es_aioclient_mock,
        url=es_url,
        mock_health_check=True,
        mock_index_creation=True,
        mock_template_setup=True,
        mock_ilm_setup=True,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data={}
    )
    await hass.async_block_till_done()
    assert result["type"] == data_entry_flow.RESULT_TYPE_MENU
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"next_step_id": "no_auth"}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "no_auth"

    mock_es_initialization(
        es_aioclient_mock,
        url=es_url,
        mock_health_check=True,
        mock_index_creation=True,
        mock_template_setup=True,
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": es_url}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    entry = result["result"]

    options_result = await hass.config_entries.options.async_init(entry.entry_id, data=None)

    assert options_result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert options_result["step_id"] == "publish_options"

    options_result = await hass.config_entries.options.async_configure(
        options_result["flow_id"], user_input={}
    )

    assert options_result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert options_result["step_id"] == "ilm_options"

    options_result = await hass.config_entries.options.async_configure(
        options_result["flow_id"], user_input={}
    )

    assert options_result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY

"""Test Config Flow."""
from unittest.mock import MagicMock

import aiohttp
import pytest
from homeassistant import data_entry_flow
from homeassistant.config_entries import SOURCE_USER
from homeassistant.helpers.typing import HomeAssistantType

from custom_components.elasticsearch.const import DOMAIN
from tests.test_util.es_startup_mocks import mock_es_initialization


@pytest.mark.asyncio
async def test_no_auth_flow(hass: HomeAssistantType, aioclient_mock):
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
        aioclient_mock,
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
async def test_no_auth_flow_unsupported_version(hass: HomeAssistantType, aioclient_mock):
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

    mock_es_initialization(aioclient_mock, url=es_url, mock_unsupported_version=True)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": es_url}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "no_auth"
    assert result["errors"]["base"] == "unsupported_version"


@pytest.mark.asyncio
async def test_no_auth_flow_with_tls_error(hass: HomeAssistantType, aioclient_mock):
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

    aioclient_mock.get(es_url, exc=MockSSLError)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": es_url}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"]["base"] == "untrusted_connection"
    assert result["step_id"] == "no_auth"
    assert "data" not in result


@pytest.mark.asyncio
async def test_flow_fails_es_unavailable(hass: HomeAssistantType, aioclient_mock):
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

    aioclient_mock.get(es_url, exc=aiohttp.ClientError)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": es_url}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"]["base"] == "cannot_connect"
    assert result["step_id"] == "no_auth"
    assert "data" not in result


@pytest.mark.asyncio
async def test_flow_fails_unauthorized(hass: HomeAssistantType, aioclient_mock):
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

    aioclient_mock.get(es_url, status=401)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": es_url}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"]["base"] == "invalid_basic_auth"
    assert result["step_id"] == "no_auth"
    assert "data" not in result

@pytest.mark.asyncio
async def test_basic_auth_flow(hass: HomeAssistantType, aioclient_mock):
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
        aioclient_mock,
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
async def test_api_key_flow(hass: HomeAssistantType, aioclient_mock):
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
        aioclient_mock,
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


@pytest.mark.skip(
    reason="Struggling to prevent real network requests. Something is not honoring our aioclient mock."
)
async def test_options_flow(
    hass: HomeAssistantType, aioclient_mock, event_loop
) -> None:
    """Test options config flow."""

    es_url = "http://localhost:9200"

    mock_es_initialization(
        aioclient_mock,
        url=es_url,
        mock_health_check=True,
        mock_index_creation=True,
        mock_template_setup=True,
        mock_ilm_setup=True,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data={"url": es_url}
    )
    await hass.async_block_till_done()
    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    entry = result["result"]

    result = await hass.config_entries.options.async_init(entry.entry_id, data=None)

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "publish_options"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "ilm_options"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "health_options"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY

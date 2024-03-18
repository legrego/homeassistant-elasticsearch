"""Test Config Flow."""

from unittest.mock import MagicMock

import aiohttp
import pytest
from homeassistant import data_entry_flow
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.const import CONF_API_KEY, CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.elasticsearch.const import CONF_INDEX_MODE, DOMAIN
from tests.conftest import mock_config_entry
from tests.test_util.es_startup_mocks import mock_es_initialization


async def _setup_config_entry(hass: HomeAssistant, mock_entry: mock_config_entry):
    mock_entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {}) is True
    await hass.async_block_till_done()

    config_entries = hass.config_entries.async_entries(DOMAIN)
    assert len(config_entries) == 1
    entry = config_entries[0]

    return entry


@pytest.mark.asyncio
async def test_no_auth_flow_isolate(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
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
        mock_ilm_setup=True,
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
async def test_no_auth_flow_unsupported_version(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
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
async def test_no_auth_flow_with_tls_error(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
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
async def test_flow_fails_es_unavailable(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
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
async def test_flow_fails_unauthorized(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
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
async def test_basic_auth_flow(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
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
        result["flow_id"],
        user_input={"url": es_url, "username": "hass_writer", "password": "changeme"},
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
async def test_basic_auth_flow_unauthorized(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test user config flow with minimum fields, with bad credentials."""

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

    es_aioclient_mock.get(es_url, status=401)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"url": es_url, "username": "hass_writer", "password": "changeme"},
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"]["base"] == "invalid_basic_auth"
    assert result["step_id"] == "basic_auth"
    assert "data" not in result


@pytest.mark.asyncio
async def test_basic_auth_flow_missing_index_privilege(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test user config flow with minimum fields, with insufficient index privileges."""

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
        es_aioclient_mock, url=es_url, mock_index_authorization_error=True
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"url": es_url, "username": "hass_writer", "password": "changeme"},
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"]["base"] == "insufficient_privileges"
    assert result["step_id"] == "basic_auth"
    assert "data" not in result


@pytest.mark.asyncio
async def test_reauth_flow_basic(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test reauth flow with basic credentials."""
    es_url = "http://test_reauth_flow_basic:9200"

    mock_es_initialization(es_aioclient_mock, url=es_url)

    mock_entry = MockConfigEntry(
        unique_id="test_reauth_flow_basic",
        domain=DOMAIN,
        version=3,
        data={"url": es_url, "username": "elastic", "password": "changeme"},
        title="ES Config",
    )

    entry = await _setup_config_entry(hass, mock_entry)

    # Simulate authorization error (403)
    es_aioclient_mock.clear_requests()
    mock_es_initialization(
        es_aioclient_mock, url=es_url, mock_index_authorization_error=True
    )

    # Start reauth flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"

    # New creds valid, but privileges still insufficient
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "other_user",
            CONF_PASSWORD: "other_password",
        },
    )
    await hass.async_block_till_done()
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "insufficient_privileges"}

    # Simulate authentication error (401)
    es_aioclient_mock.clear_requests()
    mock_es_initialization(
        es_aioclient_mock, url=es_url, mock_authentication_error=True
    )

    # New creds invalid
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "other_user",
            CONF_PASSWORD: "other_password",
        },
    )
    await hass.async_block_till_done()
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_basic_auth"}

    # Simulate success
    es_aioclient_mock.clear_requests()
    mock_es_initialization(es_aioclient_mock, url=es_url)

    # Success
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "successful_user",
            CONF_PASSWORD: "successful_password",
        },
    )
    await hass.async_block_till_done()
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert entry.data.copy() == {
        CONF_URL: es_url,
        CONF_USERNAME: "successful_user",
        CONF_PASSWORD: "successful_password",
        CONF_INDEX_MODE: "index",
    }


@pytest.mark.asyncio
async def test_reauth_flow_api_key(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test reauth flow with API Key credentials."""
    es_url = "http://test_reauth_flow_api_key:9200"

    mock_es_initialization(es_aioclient_mock, url=es_url)

    mock_entry = MockConfigEntry(
        unique_id="test_reauth_flow_basic",
        domain=DOMAIN,
        version=3,
        data={"url": es_url, "api_key": "abc123"},
        title="ES Config",
    )

    entry = await _setup_config_entry(hass, mock_entry)

    # Simulate authorization error (403)
    es_aioclient_mock.clear_requests()
    mock_es_initialization(
        es_aioclient_mock, url=es_url, mock_index_authorization_error=True
    )

    # Start reauth flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"

    # New creds valid, but privileges still insufficient
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_KEY: "plo312"},
    )
    await hass.async_block_till_done()
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "insufficient_privileges"}

    # Simulate authentication error (401)
    es_aioclient_mock.clear_requests()
    mock_es_initialization(
        es_aioclient_mock, url=es_url, mock_authentication_error=True
    )

    # New creds invalid
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_API_KEY: "xyc321",
        },
    )
    await hass.async_block_till_done()
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_api_key"}

    # Simulate success
    es_aioclient_mock.clear_requests()
    mock_es_initialization(es_aioclient_mock, url=es_url)

    # Success
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_API_KEY: "good456",
        },
    )
    await hass.async_block_till_done()
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert entry.data.copy() == {
        CONF_URL: es_url,
        CONF_API_KEY: "good456",
        CONF_INDEX_MODE: "index",
    }


@pytest.mark.asyncio
async def test_step_import_already_exist(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test that errors are shown when duplicates are added."""
    es_url = "http://test_step_import_already_exist:9200"

    mock_es_initialization(es_aioclient_mock, url=es_url)

    mock_entry = MockConfigEntry(
        unique_id="test_step_import_already_exist",
        domain=DOMAIN,
        version=3,
        data={"url": es_url, "api_key": "abc123"},
        title="ES Config",
    )

    await _setup_config_entry(hass, mock_entry)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "import"},
        data={"url": "http://other-url:9200", "username": "xyz321", "password": "123"},
    )
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


@pytest.mark.asyncio
async def test_step_import_update_existing(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test that yml config is reflected in existing config entry."""
    es_url = "http://test_step_import_update_existing:9200"

    mock_es_initialization(es_aioclient_mock, url=es_url)

    mock_entry = MockConfigEntry(
        unique_id="test_step_import_update_existing",
        domain=DOMAIN,
        version=3,
        data={"url": es_url, "username": "original_user", "password": "abc123"},
        title="ES Config",
    )

    await _setup_config_entry(hass, mock_entry)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "import"},
        data={
            "url": es_url,
            "username": "new_user",
            "password": "xyz321",
            CONF_INDEX_MODE: "index",
        },
    )
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "updated_entry"


@pytest.mark.asyncio
async def test_legacy_index_mode_flow(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test user config flow with explicit choice of legacy index mode."""

    es_url = "http://legacy_index_mode-flow:9200"
    mock_es_initialization(es_aioclient_mock, url=es_url, mock_v88_cluster=True)

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

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": es_url, "api_key": "ABC123=="}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "index_mode"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"index_mode": "index"}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result["title"] == es_url
    assert result["data"]["url"] == es_url
    assert result["data"]["index_mode"] == "index"


@pytest.mark.asyncio
async def test_api_key_flow(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
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

    mock_es_initialization(es_aioclient_mock, url=es_url)

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
async def test_api_key_flow_fails_unauthorized(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
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
async def test_options_flow(hass: HomeAssistant, es_aioclient_mock) -> None:
    """Test options config flow."""

    es_url = "http://localhost:9200"

    mock_es_initialization(es_aioclient_mock, url=es_url)

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

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": es_url}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    entry = result["result"]

    options_result = await hass.config_entries.options.async_init(
        entry.entry_id, data=None
    )

    assert options_result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert options_result["step_id"] == "publish_options"

    options_result = await hass.config_entries.options.async_configure(
        options_result["flow_id"], user_input={}
    )

    assert options_result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert options_result["step_id"] == "ilm_options"

    # this last step *might* attempt to use a real connection instead of our mock...

    options_result = await hass.config_entries.options.async_configure(
        options_result["flow_id"], user_input={}
    )

    assert options_result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY

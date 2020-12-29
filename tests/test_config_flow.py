import pytest
from custom_components.elastic.const import DOMAIN
from homeassistant import data_entry_flow
from homeassistant.config_entries import SOURCE_USER
from homeassistant.helpers.typing import HomeAssistantType
from tests.common import MockESGateway, MockESIntegration

from .async_mock import patch


@pytest.mark.asyncio
@patch("custom_components.elastic.es_gateway.ElasticsearchGateway", MockESGateway)
@patch("custom_components.elastic.ElasticIntegration", MockESIntegration)
async def test_user_flow_minimum_fields(hass: HomeAssistantType, event_loop):
    """ Test user config flow with minimum fields. """

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": "http://localhost:9200"}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result["title"] == "http://localhost:9200"
    assert result["data"]["url"] == "http://localhost:9200"
    assert result["data"]["username"] is None
    assert result["data"]["password"] is None
    assert result["data"]["ssl_ca_path"] is None
    assert result["data"]["verify_ssl"] is True
    assert result["data"]["publish_enabled"] is True
    assert result["data"]["health_sensor_enabled"] is True


@pytest.mark.asyncio
@patch("custom_components.elastic.es_gateway.ElasticsearchGateway", MockESGateway)
async def test_user_flow_to_tls_flow(hass: HomeAssistantType, event_loop):
    """ Test user config flow with config that forces TLS configuration. """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": "https://localhost:9200"}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"]["base"] == "untrusted_connection"
    assert result["step_id"] == "tls"
    assert "data" not in result


@pytest.mark.asyncio
@patch("custom_components.elastic.es_gateway.ElasticsearchGateway", MockESGateway)
async def test_flow_fails_es_unavailable(hass: HomeAssistantType):
    """ Test user config flow fails if connection cannot be established. """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": "http://unavailable-host:9200"}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"]["base"] == "cannot_connect"
    assert result["step_id"] == "user"
    assert "data" not in result


@pytest.mark.asyncio
@patch("custom_components.elastic.es_gateway.ElasticsearchGateway", MockESGateway)
async def test_flow_fails_unauthorized(hass: HomeAssistantType):
    """ Test user config flow fails if connection cannot be established. """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"url": "http://needs-auth:9200"}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"]["base"] == "invalid_auth"
    assert result["step_id"] == "user"
    assert "data" not in result

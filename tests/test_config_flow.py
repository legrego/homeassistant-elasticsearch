import pytest
from homeassistant import data_entry_flow
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.config_entries import (
    SOURCE_IGNORE,
    SOURCE_IMPORT,
    SOURCE_USER,
    SOURCE_ZEROCONF,
)

from custom_components.elastic.const import DOMAIN
from unittest.mock import patch
from tests.common import MockESGateway


@pytest.mark.asyncio
@patch("custom_components.elastic.es_gateway.ElasticsearchGateway", MockESGateway)
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
    assert result["data"]["username"] == None
    assert result["data"]["password"] == None
    assert result["data"]["ssl_ca_path"] == None
    assert result["data"]["verify_ssl"] == True


@pytest.mark.asyncio
@patch("custom_components.elastic.es_gateway.ElasticsearchGateway", MockESGateway)
async def test_user_flow_to_tls_flow(hass: HomeAssistantType, event_loop):
    """ Test user config flow with config that forces TLS configuration. """
    patch("custom_components.elastic.es_gateway.ElasticsearchGateway", MockESGateway)
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

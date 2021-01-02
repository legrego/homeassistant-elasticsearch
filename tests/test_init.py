"""Tests for Elastic init."""
import pytest
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import CONF_URL
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.setup import async_setup_component

from custom_components.elastic.const import DOMAIN as ELASTIC_DOMAIN
from tests.common import MockESGateway
from tests.const import MOCK_LEGACY_CONFIG
from tests.test_util.es_startup_mocks import mock_es_initialization

from .async_mock import patch


@pytest.mark.asyncio
@patch("custom_components.elastic.es_gateway.ElasticsearchGateway", MockESGateway)
@patch("custom_components.elastic.es_integration.ElasticsearchGateway", MockESGateway)
async def test_setup_component(hass: HomeAssistantType, aioclient_mock) -> None:
    """Test component setup."""
    mock_es_initialization(aioclient_mock, url=MOCK_LEGACY_CONFIG.get(CONF_URL))

    assert await async_setup_component(
        hass, ELASTIC_DOMAIN, {ELASTIC_DOMAIN: MOCK_LEGACY_CONFIG}
    )
    await hass.async_block_till_done()
    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 0

    config_entries = hass.config_entries.async_entries(ELASTIC_DOMAIN)
    assert len(config_entries) == 1
    # todo assert config entry


# TODO: Test load and unload via config flows

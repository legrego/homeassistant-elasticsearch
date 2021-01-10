"""Tests for Elastic init."""
import pytest
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import CONF_URL
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.setup import async_setup_component

from custom_components.elasticsearch.const import DOMAIN as ELASTIC_DOMAIN
from custom_components.elasticsearch.utils import get_merged_config
from tests.const import MOCK_COMPLEX_LEGACY_CONFIG, MOCK_MINIMAL_LEGACY_CONFIG
from tests.test_util.es_startup_mocks import mock_es_initialization


@pytest.mark.asyncio
async def test_minimal_setup_component(hass: HomeAssistantType, aioclient_mock) -> None:
    """Test component setup via legacy yml-based configuration."""
    mock_es_initialization(aioclient_mock, url=MOCK_MINIMAL_LEGACY_CONFIG.get(CONF_URL))

    assert await async_setup_component(
        hass, ELASTIC_DOMAIN, {ELASTIC_DOMAIN: MOCK_MINIMAL_LEGACY_CONFIG}
    )
    await hass.async_block_till_done()
    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 0

    config_entries = hass.config_entries.async_entries(ELASTIC_DOMAIN)
    assert len(config_entries) == 1

    merged_config = get_merged_config(config_entries[0])

    expected_config = {
        "alias": "active-hass-index",
        "health_sensor_enabled": True,
        "ilm_enabled": True,
        "publish_enabled": True,
        "excluded_domains": [],
        "excluded_entities": [],
        "index_format": "hass-events",
        "only_publish_changed": False,
        "publish_frequency": 60,
        "timeout": 30,
        "username": None,
        "password": None,
        "verify_ssl": True,
        "ssl_ca_path": None,
        "ilm_delete_after": "365d",
        "ilm_max_size": "30gb",
        "ilm_policy_name": "home-assistant",
        **MOCK_MINIMAL_LEGACY_CONFIG,
    }

    assert merged_config == expected_config


@pytest.mark.asyncio
async def test_complex_setup_component(hass: HomeAssistantType, aioclient_mock) -> None:
    """Test component setup via legacy yml-based configuration."""
    mock_es_initialization(aioclient_mock, url=MOCK_COMPLEX_LEGACY_CONFIG.get(CONF_URL))

    assert await async_setup_component(
        hass, ELASTIC_DOMAIN, {ELASTIC_DOMAIN: MOCK_COMPLEX_LEGACY_CONFIG}
    )
    await hass.async_block_till_done()
    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 0

    config_entries = hass.config_entries.async_entries(ELASTIC_DOMAIN)
    assert len(config_entries) == 1

    merged_config = get_merged_config(config_entries[0])

    expected_config = {
        "excluded_domains": ["sensor", "weather"],
        "excluded_entities": ["switch.my_switch"],
        "ssl_ca_path": None,
        **MOCK_COMPLEX_LEGACY_CONFIG,
    }

    del expected_config["exclude"]

    assert merged_config == expected_config

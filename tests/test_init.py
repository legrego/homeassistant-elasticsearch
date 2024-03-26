"""Tests for Elastic init."""

import pytest
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_ALIAS, CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.elasticsearch.const import (
    CONF_EXCLUDED_DOMAINS,
    CONF_ILM_POLICY_NAME,
    CONF_INDEX_FORMAT,
)
from custom_components.elasticsearch.const import DOMAIN as ELASTIC_DOMAIN
from custom_components.elasticsearch.utils import get_merged_config
from tests.const import MOCK_COMPLEX_LEGACY_CONFIG, MOCK_MINIMAL_LEGACY_CONFIG
from tests.test_util.es_startup_mocks import mock_es_initialization


async def _setup_config_entry(hass: HomeAssistant, mock_entry: MockConfigEntry):
    mock_entry.add_to_hass(hass)
    assert await async_setup_component(hass, ELASTIC_DOMAIN, {}) is True
    await hass.async_block_till_done()

    config_entries = hass.config_entries.async_entries(ELASTIC_DOMAIN)
    assert len(config_entries) == 1
    entry = config_entries[0]

    return entry


@pytest.mark.asyncio
async def test_minimal_setup_component(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
) -> None:
    """Test component setup via legacy yml-based configuration."""
    mock_es_initialization(
        es_aioclient_mock, url=MOCK_MINIMAL_LEGACY_CONFIG.get(CONF_URL)
    )

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
        "ilm_enabled": True,
        "publish_enabled": True,
        "excluded_domains": [],
        "excluded_entities": [],
        "included_domains": [],
        "included_entities": [],
        "index_format": "hass-events",
        "index_mode": "index",
        "datastream_name_prefix": "homeassistant",
        "datastream_namespace": "default",
        "datastream_type": "metrics",
        "publish_mode": "Any changes",
        "publish_frequency": 60,
        "timeout": 30,
        "username": None,
        "password": None,
        "api_key": None,
        "verify_ssl": True,
        "ssl_ca_path": None,
        "ilm_delete_after": "365d",
        "ilm_max_size": "30gb",
        "ilm_policy_name": "home-assistant",
        **MOCK_MINIMAL_LEGACY_CONFIG,
    }

    assert merged_config == expected_config


@pytest.mark.asyncio
async def test_complex_setup_component(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
) -> None:
    """Test component setup via legacy yml-based configuration."""
    mock_es_initialization(
        es_aioclient_mock,
        url=MOCK_COMPLEX_LEGACY_CONFIG.get(CONF_URL),
        alias_name=MOCK_COMPLEX_LEGACY_CONFIG.get(CONF_ALIAS),
        index_format=MOCK_COMPLEX_LEGACY_CONFIG.get(CONF_INDEX_FORMAT),
        ilm_policy_name=MOCK_COMPLEX_LEGACY_CONFIG.get(CONF_ILM_POLICY_NAME),
    )

    assert await async_setup_component(
        hass, ELASTIC_DOMAIN, {ELASTIC_DOMAIN: MOCK_COMPLEX_LEGACY_CONFIG}
    )
    await hass.async_block_till_done()
    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 0

    config_entries = hass.config_entries.async_entries(ELASTIC_DOMAIN)
    assert len(config_entries) == 1

    merged_config = get_merged_config(config_entries[0])

    expected_config = {
        "index_mode": "index",
        "datastream_name_prefix": "homeassistant",
        "datastream_namespace": "default",
        "datastream_type": "metrics",
        "excluded_domains": ["sensor", "weather"],
        "excluded_entities": ["switch.my_switch"],
        "included_domains": [],
        "included_entities": [],
        "ssl_ca_path": None,
        "publish_mode": "Any changes",
        "api_key": None,
        **MOCK_COMPLEX_LEGACY_CONFIG,
    }

    del expected_config["exclude"]
    del expected_config["only_publish_changed"]
    del expected_config["health_sensor_enabled"]

    assert merged_config == expected_config


@pytest.mark.asyncio
async def test_update_entry(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
) -> None:
    """Test component entry update."""

    es_url = "http://update-entry:9200"

    mock_es_initialization(es_aioclient_mock, url=es_url)

    mock_entry = MockConfigEntry(
        unique_id="test_update_entry",
        domain=ELASTIC_DOMAIN,
        version=3,
        data={"url": es_url},
        title="ES Config",
    )

    entry = await _setup_config_entry(hass, mock_entry)

    assert hass.config_entries.async_update_entry(
        entry=entry, options={CONF_EXCLUDED_DOMAINS: ["sensor", "weather"]}
    )

    await hass.async_block_till_done()

    config_entries = hass.config_entries.async_entries(ELASTIC_DOMAIN)
    assert len(config_entries) == 1

    updated_entry = config_entries[0]
    merged_config = get_merged_config(updated_entry)

    expected_config = {
        "url": es_url,
        "excluded_domains": ["sensor", "weather"],
        "index_mode": "index",
    }

    assert merged_config == expected_config


@pytest.mark.asyncio
async def test_unsupported_version(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
) -> None:
    """Test component setup with an unsupported version."""
    es_url = "http://unsupported-version:9200"

    mock_es_initialization(es_aioclient_mock, url=es_url, mock_unsupported_version=True)

    mock_entry = MockConfigEntry(
        unique_id="test_unsupported_version",
        domain=ELASTIC_DOMAIN,
        version=3,
        data={"url": es_url},
        title="ES Config",
    )

    entry = await _setup_config_entry(hass, mock_entry)

    assert entry.state == ConfigEntryState.SETUP_RETRY
    assert entry.reason == "Unsupported Elasticsearch version detected"


@pytest.mark.asyncio
async def test_reauth_setup_entry(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
) -> None:
    """Test reauth flow triggered by setup entry."""

    es_url = "http://authentication-error:9200"

    mock_es_initialization(
        es_aioclient_mock, url=es_url, mock_authentication_error=True
    )

    mock_entry = MockConfigEntry(
        unique_id="test_authentication_error",
        domain=ELASTIC_DOMAIN,
        version=3,
        data={"url": es_url},
        title="ES Config",
    )

    entry = await _setup_config_entry(hass, mock_entry)

    assert entry.state == ConfigEntryState.SETUP_ERROR
    assert entry.reason == "Missing or invalid credentials"

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1

    flow = flows[0]
    assert flow.get("step_id") == "reauth_confirm"
    assert flow.get("handler") == ELASTIC_DOMAIN

    assert "context" in flow
    assert flow["context"].get("source") == SOURCE_REAUTH
    assert flow["context"].get("entry_id") == entry.entry_id


@pytest.mark.asyncio
async def test_connection_error(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
) -> None:
    """Test component setup with an unsupported version."""
    es_url = "http://connection-error:9200"

    mock_es_initialization(es_aioclient_mock, url=es_url, mock_connection_error=True)

    mock_entry = MockConfigEntry(
        unique_id="test_connection_error",
        domain=ELASTIC_DOMAIN,
        version=3,
        data={"url": es_url},
        title="ES Config",
    )

    entry = await _setup_config_entry(hass, mock_entry)

    assert entry.state == ConfigEntryState.SETUP_RETRY
    assert entry.reason == "Exception during component initialization"


@pytest.mark.asyncio
async def test_config_migration_v1(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test config migration from v1."""
    es_url = "http://migration-v1-test:9200"

    mock_es_initialization(es_aioclient_mock, url=es_url)

    # Create mock entry with version 1
    mock_entry = MockConfigEntry(
        unique_id="mock unique id v1",
        domain=ELASTIC_DOMAIN,
        version=1,
        data={"url": es_url, "only_publish_changed": True},
        title="ES Config",
    )

    # Set it up
    mock_entry.add_to_hass(hass)
    assert await async_setup_component(hass, ELASTIC_DOMAIN, {}) is True
    await hass.async_block_till_done()

    # Verify publish mode and index mode have been set correctly

    expected_config = {
        "url": es_url,
        "publish_mode": "Any changes",
        "index_mode": "index",
    }

    updated_entry = hass.config_entries.async_get_entry(mock_entry.entry_id)
    assert updated_entry
    assert updated_entry.version == 4
    assert updated_entry.data == expected_config


@pytest.mark.asyncio
async def test_config_migration_v2(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test config migration from v2."""
    es_url = "http://migration-v2-test:9200"

    mock_es_initialization(es_aioclient_mock, url=es_url)

    # Create mock entry with version 2
    mock_entry = MockConfigEntry(
        unique_id="mock unique id v2",
        domain=ELASTIC_DOMAIN,
        version=2,
        data={"url": es_url, "health_sensor_enabled": True},
        title="ES Config",
    )

    # Set it up
    mock_entry.add_to_hass(hass)
    assert await async_setup_component(hass, ELASTIC_DOMAIN, {}) is True
    await hass.async_block_till_done()

    # Verify health sensor has been removed, and index mode has been configured

    expected_config = {"url": es_url, "index_mode": "index"}

    updated_entry = hass.config_entries.async_get_entry(mock_entry.entry_id)
    assert updated_entry
    assert updated_entry.version == 4
    assert updated_entry.data == expected_config

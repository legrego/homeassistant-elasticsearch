"""Tests for Elastic init."""

import pytest
from elasticsearch import migrate_data_and_options_to_version
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


def _test_config_data_options_migration_to_version(
    Before_Version, Before_Data, After_Version, After_Data
):
    mock_entry = MockConfigEntry(
        unique_id="mock migration",
        domain=ELASTIC_DOMAIN,
        version=Before_Version,
        data=Before_Data,
        title="ES Config",
    )

    migrate_data_and_options_to_version(mock_entry, desired_version=After_Version)

    assert mock_entry
    assert mock_entry.data == After_Data
    assert mock_entry.version == After_Version

    return True


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
async def test_config_migration_v1tov2(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test config migration from v1."""

    Before_Version = 1
    Before_Data = {"url": "http://migration-test:9200", "only_publish_changed": True}

    After_Version = 2
    After_Data = {"url": "http://migration-test:9200", "publish_mode": "Any changes"}

    assert _test_config_data_options_migration_to_version(
        Before_Version, Before_Data, After_Version, After_Data
    )


@pytest.mark.asyncio
async def test_config_migration_v2tov3(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test config migration from v2."""

    Before_Version = 2
    Before_Data = {"url": "http://migration-test:9200", "health_sensor_enabled": True}
    After_Version = 3
    After_Data = {"url": "http://migration-test:9200"}

    assert _test_config_data_options_migration_to_version(
        Before_Version, Before_Data, After_Version, After_Data
    )


@pytest.mark.asyncio
async def test_config_migration_v3tov4(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test config migration from v3."""

    Before_Version = 3
    Before_Data = {
        "url": "http://migration-test:9200",
        "ilm_max_size": "10gb",
        "ilm_delete_after": "30d",
    }
    After_Data = {
        "url": "http://migration-test:9200",
        "index_mode": "index",
    }
    After_Version = 4

    assert _test_config_data_options_migration_to_version(
        Before_Version, Before_Data, After_Version, After_Data
    )


@pytest.mark.asyncio
async def test_config_migration_v4tov5(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test config migration from v4."""

    Before_Version = 4
    Before_Data = {
        "url": "http://migration-test:9200",
        "publish_enabled": True,
        "publish_frequency": 60,
        "publish_mode": "Any changes",
        "excluded_domains": [],
        "excluded_entities": [],
        "included_domains": [],
        "included_entities": [],
    }
    After_Data = {
        "url": "http://migration-test:9200",
        "auth_type": "no_auth",
    }

    After_Version = 5

    assert _test_config_data_options_migration_to_version(
        Before_Version, Before_Data, After_Version, After_Data
    )


@pytest.mark.asyncio
async def test_config_migration_v1tov5(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test config migration from v1."""

    Before_Version = 1
    Before_Data = {
        "url": "http://migration-test:9200",
        "ilm_max_size": "10gb",
        "ilm_delete_after": "30d",
        "health_sensor_enabled": True,
        "only_publish_changed": True,
        "publish_enabled": True,
        "publish_frequency": 60,
        "excluded_domains": [],
        "excluded_entities": [],
        "included_domains": [],
        "included_entities": [],
    }

    After_Version = 4
    After_Data = {
        "url": "http://migration-test:9200",
        "index_mode": "index",
        "publish_mode": "Any changes",
        "auth_type": "no_auth",
    }

    mock_entry = MockConfigEntry(
        unique_id="mock migration",
        domain=ELASTIC_DOMAIN,
        version=Before_Version,
        data=Before_Data,
        title="ES Config",
    )

    mock_entry.add_to_hass(hass)
    assert await async_setup_component(hass, ELASTIC_DOMAIN, {}) is True
    await hass.async_block_till_done()

    updated_entry = hass.config_entries.async_get_entry(mock_entry.entry_id)

    assert updated_entry
    assert updated_entry.version == After_Version
    assert updated_entry.data == After_Data

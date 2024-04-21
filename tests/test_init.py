"""Tests for Elastic init."""

from elasticsearch.config_flow import build_new_options
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
    before_version,
    before_data,
    before_options,
    after_version,
    after_data,
    after_options,
):
    mock_entry = MockConfigEntry(
        unique_id="mock migration",
        domain=ELASTIC_DOMAIN,
        version=before_version,
        data=before_data,
        options=before_options,
        title="ES Config",
    )

    migrated_data, migrated_options, end_version = migrate_data_and_options_to_version(
        mock_entry, desired_version=after_version
    )

    assert mock_entry

    assert migrated_data == after_data
    assert migrated_options == after_options

    assert end_version == after_version

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
        "auth_method": "no_auth",
        "ilm_enabled": True,
        "publish_enabled": True,
        "excluded_domains": [],
        "excluded_entities": [],
        "included_domains": [],
        "included_entities": [],
        "index_format": "hass-events",
        "index_mode": "datastream",
        "publish_mode": "Any changes",
        "publish_frequency": 60,
        "timeout": 30,
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
        "auth_method": "basic_auth",
        "url": "https://my-complex-es:9200",
        "timeout": 60,
        "verify_ssl": False,
        "ssl_ca_path": None,
        "index_mode": "datastream",
        "username": "username",
        "password": "changeme",
        "publish_enabled": True,
        "publish_frequency": 60,
        "publish_mode": "Any changes",
        "alias": "active-hass-index",
        "index_format": "hass-events",
        "ilm_policy_name": "home-assistant",
        "ilm_enabled": True,
        "excluded_domains": [],
        "excluded_entities": [],
        "included_domains": [],
        "included_entities": [],
    }

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
        "auth_method": "no_auth",
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
        options=build_new_options(),
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
        data={
            "url": es_url,
            "auth_method": "basic_auth",
            "username": "username",
            "password": "password",
        },
        options=build_new_options(),
        title="ES Config",
    )

    entry = await _setup_config_entry(hass, mock_entry)

    assert entry.state == ConfigEntryState.SETUP_ERROR
    assert entry.reason == "Missing or invalid credentials"

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1

    flow = flows[0]
    assert flow.get("step_id") == "basic_auth"
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

    assert _test_config_data_options_migration_to_version(
        before_version=1,
        before_options={},
        before_data={
            "url": "http://migration-test:9200",
            "only_publish_changed": True,
        },
        after_version=2,
        after_options={},
        after_data={
            "url": "http://migration-test:9200",
            "publish_mode": "Any changes",
        },
    )


@pytest.mark.asyncio
async def test_config_migration_v2tov3(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test config migration from v2."""

    assert _test_config_data_options_migration_to_version(
        before_version=2,
        before_options={},
        before_data={
            "url": "http://migration-test:9200",
            "health_sensor_enabled": True,
        },
        after_version=3,
        after_options={},
        after_data={"url": "http://migration-test:9200"},
    )


@pytest.mark.asyncio
async def test_config_migration_v3tov4(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test config migration from v3."""

    assert _test_config_data_options_migration_to_version(
        before_version=3,
        before_options={},
        before_data={
            "url": "http://migration-test:9200",
            "ilm_max_size": "10gb",
            "ilm_delete_after": "30d",
        },
        after_options={},
        after_data={
            "url": "http://migration-test:9200",
            "index_mode": "index",
        },
        after_version=4,
    )


@pytest.mark.asyncio
async def test_config_migration_v4tov5(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test config migration from v4."""

    assert _test_config_data_options_migration_to_version(
        before_version=4,
        before_options={},
        before_data={
            "url": "http://migration-test:9200",
            "publish_enabled": True,
            "publish_frequency": 60,
            "publish_mode": "Any changes",
            "excluded_domains": [],
            "excluded_entities": [],
            "included_domains": [],
            "included_entities": [],
            "datastream_name_prefix": "homeassistant",
            "datastream_namespace": "default",
            "datastream_type": "metrics",
        },
        after_options={
            "publish_mode": "Any changes",
            "excluded_domains": [],
            "excluded_entities": [],
            "included_domains": [],
            "included_entities": [],
            "publish_enabled": True,
            "publish_frequency": 60,
        },
        after_data={
            "url": "http://migration-test:9200",
            "auth_method": "no_auth",
        },
        after_version=5,
    )


@pytest.mark.asyncio
async def test_config_migration_v1tov5(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test config migration from v1."""

    before_version = 1
    before_options = {}
    before_data = {
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
        "publish_mode": "Any changes",
    }

    after_version = 5
    after_options = {
        "publish_enabled": True,
        "publish_frequency": 60,
        "publish_mode": "Any changes",
        "excluded_domains": [],
        "excluded_entities": [],
        "included_domains": [],
        "included_entities": [],
    }
    after_data = {
        "url": "http://migration-test:9200",
        "index_mode": "index",
        "auth_method": "no_auth",
    }

    mock_entry = MockConfigEntry(
        unique_id="mock migration",
        domain=ELASTIC_DOMAIN,
        version=before_version,
        data=before_data,
        title="ES Config",
    )

    mock_entry.add_to_hass(hass)
    assert await async_setup_component(hass, ELASTIC_DOMAIN, {}) is True
    await hass.async_block_till_done()

    updated_entry = hass.config_entries.async_get_entry(mock_entry.entry_id)

    assert updated_entry
    assert updated_entry.version == after_version
    assert updated_entry.data == after_data

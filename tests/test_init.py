"""Tests for Elastic init."""

import pytest
from elasticsearch import migrate_data_and_options_to_version
from elasticsearch.config_flow import build_new_options
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from syrupy.extensions.json import JSONSnapshotExtension

from custom_components.elasticsearch.const import (
    CONF_EXCLUDED_DOMAINS,
)
from custom_components.elasticsearch.const import DOMAIN as ELASTIC_DOMAIN
from custom_components.elasticsearch.utils import get_merged_config
from tests.test_util.es_startup_mocks import mock_es_initialization


@pytest.fixture(autouse=True)
def snapshot(snapshot):
    """Provide a pre-configured snapshot object."""

    return snapshot.with_defaults(extension_class=JSONSnapshotExtension)


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
    snapshot,
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

    assert {
        "before_data": mock_entry.data,
        "before_options": mock_entry.options,
        "before_version": mock_entry.version,
        "after_data": migrated_data,
        "after_options": migrated_options,
        "after_version": end_version,
    } == snapshot

    return True


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
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker, snapshot
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
        snapshot=snapshot,
        after_options={},
        after_data={
            "url": "http://migration-test:9200",
            "publish_mode": "Any changes",
        },
    )


@pytest.mark.asyncio
async def test_config_migration_v2tov3(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker, snapshot
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
        snapshot=snapshot,
        after_options={},
        after_data={"url": "http://migration-test:9200"},
    )


@pytest.mark.asyncio
async def test_config_migration_v3tov4(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker, snapshot
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
        snapshot=snapshot,
    )


@pytest.mark.asyncio
async def test_config_migration_v4tov5(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker, snapshot
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
        },
        after_version=5,
        snapshot=snapshot,
    )


@pytest.mark.asyncio
async def test_config_migration_v1tov5(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker, snapshot
):
    """Test config migration from v1."""

    assert _test_config_data_options_migration_to_version(
        before_version=1,
        before_options={},
        before_data={
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
        },
        after_options={
            "publish_enabled": True,
            "publish_frequency": 60,
            "publish_mode": "Any changes",
            "excluded_domains": [],
            "excluded_entities": [],
            "included_domains": [],
            "included_entities": [],
        },
        after_data={
            "url": "http://migration-test:9200",
            "index_mode": "index",
        },
        after_version=5,
        snapshot=snapshot,
    )

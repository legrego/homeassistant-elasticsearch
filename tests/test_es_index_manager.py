"""Testing for Elasticsearch Index Manager."""

import pytest
from elasticsearch7.exceptions import ElasticsearchException
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.elasticsearch.config_flow import build_full_config
from custom_components.elasticsearch.const import (
    CONF_INDEX_MODE,
    DATASTREAM_METRICS_INDEX_TEMPLATE_NAME,
    DOMAIN,
    INDEX_MODE_DATASTREAM,
    INDEX_MODE_LEGACY,
    LEGACY_TEMPLATE_NAME,
)
from custom_components.elasticsearch.errors import ElasticException
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from custom_components.elasticsearch.es_index_manager import IndexManager
from tests.conftest import mock_config_entry
from tests.test_util.aioclient_mock_utils import (
    extract_es_ilm_template_requests,
    extract_es_legacy_index_template_requests,
    extract_es_modern_index_template_requests,
)
from tests.test_util.es_startup_mocks import mock_es_initialization


async def _setup_config_entry(hass: HomeAssistant, mock_entry: mock_config_entry):
    mock_entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {}) is True
    await hass.async_block_till_done()

    config_entries = hass.config_entries.async_entries(DOMAIN)
    assert len(config_entries) == 1
    entry = config_entries[0]

    return entry


@pytest.fixture()
async def legacy_index_manager(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Fixture for IndexManager."""

    es_url = "http://localhost:9200"

    mock_es_initialization(es_aioclient_mock, es_url, mock_template_setup=True)

    config = build_full_config({"url": es_url, CONF_INDEX_MODE: INDEX_MODE_LEGACY})

    mock_entry = MockConfigEntry(
        unique_id="test_legacy_index_manager",
        domain=DOMAIN,
        version=4,
        data=config,
        title="ES Config",
    )

    entry = mock_entry  # entry = await _setup_config_entry(hass, mock_entry)

    gateway = ElasticsearchGateway(entry)

    await gateway.async_init()

    index_manager = IndexManager(hass, entry, gateway)

    return index_manager


@pytest.fixture()
async def modern_index_manager(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Fixture for IndexManager."""

    es_url = "http://localhost:9200"

    mock_es_initialization(
        es_aioclient_mock,
        es_url,
        mock_template_setup=True,
        mock_v88_cluster=True,
        mock_modern_template_setup=True,
    )

    config = build_full_config({"url": es_url, CONF_INDEX_MODE: INDEX_MODE_DATASTREAM})

    mock_entry = MockConfigEntry(
        unique_id="test_modern_index_manager",
        domain=DOMAIN,
        version=4,
        data=config,
        title="ES Config",
    )

    entry = mock_entry  # entry = await _setup_config_entry(hass, mock_entry)

    gateway = ElasticsearchGateway(entry)

    await gateway.async_init()

    index_manager = IndexManager(hass, entry, gateway)

    return index_manager


@pytest.mark.asyncio
async def test_legacy_index_mode_setup(
    legacy_index_manager: legacy_index_manager, es_aioclient_mock: AiohttpClientMocker
):
    """Test for legacy index mode setup."""
    legacy_template_requests = extract_es_legacy_index_template_requests(
        es_aioclient_mock
    )

    assert len(legacy_template_requests) == 0

    await legacy_index_manager.async_setup()

    legacy_template_requests = extract_es_legacy_index_template_requests(
        es_aioclient_mock
    )

    assert len(legacy_template_requests) == 1

    assert legacy_template_requests[0].url.path == "/_template/" + LEGACY_TEMPLATE_NAME

    assert legacy_template_requests[0].method == "PUT"

    ilm_template_requests = extract_es_ilm_template_requests(es_aioclient_mock)

    assert len(ilm_template_requests) == 1


@pytest.mark.asyncio
async def test_modern_index_mode_setup(
    modern_index_manager: modern_index_manager, es_aioclient_mock: AiohttpClientMocker
):
    """Test for modern index mode setup."""

    modern_template_requests = extract_es_modern_index_template_requests(
        es_aioclient_mock
    )

    assert len(modern_template_requests) == 0

    await modern_index_manager.async_setup()

    modern_template_requests = extract_es_modern_index_template_requests(
        es_aioclient_mock
    )

    assert len(modern_template_requests) == 1

    assert (
        modern_template_requests[0].url.path
        == "/_index_template/" + DATASTREAM_METRICS_INDEX_TEMPLATE_NAME
    )

    assert modern_template_requests[0].method == "PUT"

    ilm_template_requests = extract_es_ilm_template_requests(es_aioclient_mock)

    assert len(ilm_template_requests) == 0


@pytest.mark.asyncio
async def test_invalid_index_mode_setup(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test for invalid index mode configuration value."""

    es_url = "http://localhost:9200"

    mock_es_initialization(
        es_aioclient_mock,
        es_url,
        mock_template_setup=True,
        mock_v88_cluster=True,
        mock_modern_template_setup=True,
    )

    config = build_full_config({"url": es_url, CONF_INDEX_MODE: "garbage"})
    mock_entry = MockConfigEntry(
        unique_id="test_invalid_index_mode_setup",
        domain=DOMAIN,
        version=4,
        data=config,
        title="ES Config",
    )

    entry = mock_entry  # entry = await _setup_config_entry(hass, mock_entry)

    gateway = ElasticsearchGateway(entry)

    await gateway.async_init()

    with pytest.raises(ElasticException):
        indexmanager = IndexManager(hass, entry, gateway)
        await indexmanager.async_setup()

    await gateway.async_stop_gateway()


async def test_invalid_legacy_with_serverless(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test for legacy index mode setup with unsupported serverless version."""
    es_url = "http://localhost:9200"

    mock_es_initialization(
        es_aioclient_mock,
        es_url,
        mock_template_setup=True,
        mock_serverless_version=True,
        mock_index_creation=True,
    )

    config = build_full_config({"url": es_url, CONF_INDEX_MODE: INDEX_MODE_LEGACY})
    mock_entry = MockConfigEntry(
        unique_id="test_invalid_legacy_with_serverless",
        domain=DOMAIN,
        version=4,
        data=config,
        title="ES Config",
    )

    entry = mock_entry  # entry = await _setup_config_entry(hass, mock_entry)

    gateway = ElasticsearchGateway(entry)

    await gateway.async_init()

    with pytest.raises(ElasticsearchException):
        indexmanager = IndexManager(hass, entry, gateway)
        await indexmanager.async_setup()

    await gateway.async_stop_gateway()

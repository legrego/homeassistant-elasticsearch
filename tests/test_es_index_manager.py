"""Testing for Elasticsearch Index Manager."""

import pytest
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
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from custom_components.elasticsearch.es_index_manager import IndexManager
from tests.conftest import mock_config_entry
from tests.test_util.aioclient_mock_utils import (
    extract_es_legacy_index_template_requests,
    extract_es_modern_index_template_requests,
    extract_es_ilm_template_requests,
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

    mock_entry = MockConfigEntry(
        unique_id="test_legacy_index_manager",
        domain=DOMAIN,
        version=4,
        data=build_full_config({"url": es_url, CONF_INDEX_MODE: INDEX_MODE_LEGACY}),
        title="ES Config",
    )

    entry = await _setup_config_entry(hass, mock_entry)

    config = entry.data
    gateway = ElasticsearchGateway(config)
    index_manager = IndexManager(hass, config, gateway)

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

    mock_entry = MockConfigEntry(
        unique_id="test_modern_index_manager",
        domain=DOMAIN,
        version=4,
        data=build_full_config({"url": es_url, CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}),
        title="ES Config",
    )

    entry = await _setup_config_entry(hass, mock_entry)

    config = entry.data
    gateway = ElasticsearchGateway(config)
    index_manager = IndexManager(hass, config, gateway)

    return index_manager


@pytest.mark.asyncio
async def test_legacy_index_mode_setup(
    legacy_index_manager: legacy_index_manager, es_aioclient_mock: AiohttpClientMocker
):
    """Test for legacy index mode setup."""

    legacy_template_requests = extract_es_legacy_index_template_requests(
        es_aioclient_mock
    )

    assert len(legacy_template_requests) == 1

    assert legacy_template_requests[0].url.path == "/_template/" + LEGACY_TEMPLATE_NAME

    assert legacy_template_requests[0].method == "PUT"

    ilm_template_requests = extract_es_ilm_template_requests(es_aioclient_mock)

    assert len(ilm_template_requests) == 1


async def test_modern_index_mode_setup(
    modern_index_manager: modern_index_manager, es_aioclient_mock: AiohttpClientMocker
):
    """Test for modern index mode setup."""

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

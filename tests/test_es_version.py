"""Test Elasticsearch Version."""

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.elasticsearch.config_flow import (
    build_new_data,
    build_new_options,
)
from custom_components.elasticsearch.const import (
    DOMAIN,
)
from custom_components.elasticsearch.es_gateway import (
    Elasticsearch7Gateway,
)
from tests.test_util.es_startup_mocks import mock_es_initialization


@pytest.mark.asyncio
async def test_serverless_true(hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker):
    """Verify serverless instances are detected."""

    es_url = "http://test_serverless_true:9200"

    mock_es_initialization(es_aioclient_mock, es_url, mock_serverless_version=True)

    mock_entry = MockConfigEntry(
        unique_id="test_index_manager",
        domain=DOMAIN,
        version=5,
        data=build_new_data({"url": es_url}),
        options=build_new_options(),
        title="ES Config",
    )

    gateway = Elasticsearch7Gateway(**Elasticsearch7Gateway.build_gateway_parameters(hass, mock_entry))
    await gateway.async_init()

    assert gateway.es_version.is_serverless() is True

    await gateway.close()


@pytest.mark.asyncio
async def test_serverless_false(hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker):
    """Verify non-serverless instances are detected."""

    es_url = "http://test_serverless_false:9200"

    mock_es_initialization(es_aioclient_mock, es_url, mock_serverless_version=False)

    mock_entry = MockConfigEntry(
        unique_id="test_index_manager",
        domain=DOMAIN,
        version=5,
        data=build_new_data({"url": es_url}),
        options=build_new_options(),
        title="ES Config",
    )

    mock_entry.add_to_hass(hass)

    gateway = Elasticsearch7Gateway(**Elasticsearch7Gateway.build_gateway_parameters(hass, mock_entry))
    await gateway.async_init()

    assert gateway.es_version.is_serverless() is False

    await gateway.close()


@pytest.mark.asyncio
async def test_fails_minimum_version(hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker):
    """Verify minimum version function works."""

    es_url = "http://test_serverless_false:9200"

    mock_es_initialization(es_aioclient_mock, es_url, mock_v88_cluster=True)
    mock_entry = MockConfigEntry(
        unique_id="test_index_manager",
        domain=DOMAIN,
        version=5,
        data=build_new_data({"url": es_url}),
        options=build_new_options(),
        title="ES Config",
    )

    mock_entry.add_to_hass(hass)

    gateway = Elasticsearch7Gateway(**Elasticsearch7Gateway.build_gateway_parameters(hass, mock_entry))
    await gateway.async_init()

    assert gateway.es_version.meets_minimum_version(8, 10) is False

    await gateway.close()


@pytest.mark.asyncio
async def test_passes_minimum_version(hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker):
    """Verify minimum version function works."""

    es_url = "http://test_serverless_false:9200"

    mock_es_initialization(es_aioclient_mock, es_url, mock_v88_cluster=True)

    mock_entry = MockConfigEntry(
        unique_id="test_index_manager",
        domain=DOMAIN,
        version=5,
        data=build_new_data({"url": es_url}),
        options=build_new_options(),
        title="ES Config",
    )

    gateway = Elasticsearch7Gateway(**Elasticsearch7Gateway.build_gateway_parameters(hass, mock_entry))
    await gateway.async_init()

    assert gateway.es_version.meets_minimum_version(7, 10) is True

    await gateway.close()

"""Test Elasticsearch Version."""

import pytest
from homeassistant.helpers.typing import HomeAssistantType
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.elasticsearch.config_flow import build_full_config
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from tests.test_util.es_startup_mocks import mock_es_initialization


@pytest.mark.asyncio
async def test_serverless_true(hass: HomeAssistantType, es_aioclient_mock: AiohttpClientMocker):
    """Verify serverless instances are detected."""

    es_url = "http://test_serverless_true:9200"

    mock_es_initialization(
        es_aioclient_mock,
        es_url,
        mock_serverless_version=True
    )
    config = build_full_config({
        "url": es_url
    })
    gateway = ElasticsearchGateway(config)
    await gateway.async_init()

    assert gateway.es_version.is_serverless() is True

    await gateway.async_stop_gateway()

@pytest.mark.asyncio
async def test_serverless_false(hass: HomeAssistantType, es_aioclient_mock: AiohttpClientMocker):
    """Verify non-serverless instances are detected."""

    es_url = "http://test_serverless_false:9200"

    mock_es_initialization(
        es_aioclient_mock,
        es_url,
    )
    config = build_full_config({
        "url": es_url
    })
    gateway = ElasticsearchGateway(config)
    await gateway.async_init()

    assert gateway.es_version.is_serverless() is False

    await gateway.async_stop_gateway()

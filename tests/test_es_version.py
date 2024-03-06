"""Test Elasticsearch Version."""

import pytest
from elasticsearch.config_flow import build_full_config
from elasticsearch.es_gateway import ElasticsearchGateway
from elasticsearch.es_version import ElasticsearchVersion
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from tests.test_util.es_startup_mocks import mock_es_initialization


@pytest.mark.asyncio
async def test_serverless_true(es_aioclient_mock: AiohttpClientMocker):
    """Verify serverless instances are detected."""

    es_url = "http://localhost:9200"

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

    instance = ElasticsearchVersion(gateway.client)
    await instance.async_init()

    assert instance.is_serverless() is True

    await gateway.async_stop_gateway()

@pytest.mark.asyncio
async def test_serverless_false(es_aioclient_mock: AiohttpClientMocker):
    """Verify non-serverless instances are detected."""

    es_url = "http://localhost:9200"

    mock_es_initialization(
        es_aioclient_mock,
        es_url,
    )
    config = build_full_config({
        "url": es_url
    })
    gateway = ElasticsearchGateway(config)
    await gateway.async_init()

    instance = ElasticsearchVersion(gateway.client)
    await instance.async_init()

    assert instance.is_serverless() is False

    await gateway.async_stop_gateway()

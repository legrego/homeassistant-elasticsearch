"""Test ES Privilege Check."""

import pytest
from homeassistant.helpers.typing import HomeAssistantType
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.elasticsearch.config_flow import build_full_config
from custom_components.elasticsearch.errors import CannotConnect, InsufficientPrivileges
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from custom_components.elasticsearch.es_privilege_check import ESPrivilegeCheck
from tests.test_util.es_startup_mocks import mock_es_initialization


@pytest.mark.asyncio
async def test_bad_connection(hass: HomeAssistantType, es_aioclient_mock: AiohttpClientMocker):
    """Test graceful error handling."""

    es_url = "http://test-bad-connection:9200"
    mock_es_initialization(
        es_aioclient_mock,
        es_url
    )

    config = build_full_config({
        "url": es_url
    })

    gateway = ElasticsearchGateway(config)
    await gateway.async_init()

    es_aioclient_mock.clear_requests()
    mock_es_initialization(es_aioclient_mock, mock_connection_error=True)

    instance = ESPrivilegeCheck(gateway)

    with pytest.raises(CannotConnect):
        await instance.check_privileges(config)

    await gateway.async_stop_gateway()

@pytest.mark.asyncio
async def test_successful_privilege_check(hass: HomeAssistantType, es_aioclient_mock: AiohttpClientMocker):
    """Test successful privilege check."""

    es_url = "http://test_successful_privilege_check:9200"
    mock_es_initialization(
        es_aioclient_mock,
        es_url
    )

    config = build_full_config({
        "url": es_url
    })

    gateway = ElasticsearchGateway(config)
    await gateway.async_init()

    instance = ESPrivilegeCheck(gateway)
    result = await instance.check_privileges(config)
    assert result.has_all_requested

    await gateway.async_stop_gateway()

@pytest.mark.asyncio
async def test_successful_privilege_check_missing_index_privilege(hass: HomeAssistantType, es_aioclient_mock: AiohttpClientMocker):
    """Test successful privilege check with missing index privileges."""

    es_url = "http://test_successful_privilege_check:9200"
    mock_es_initialization(
        es_aioclient_mock,
        es_url,
        mock_index_authorization_error=True
    )

    config = build_full_config({
        "url": es_url
    })

    gateway = ElasticsearchGateway(config)
    await gateway.async_init()

    instance = ESPrivilegeCheck(gateway)
    result = await instance.check_privileges(config)
    assert result.has_all_requested is False
    assert result.missing_cluster_privileges == []
    assert result.missing_index_privileges == {
        'hass-events*': ['index']
    }

    await gateway.async_stop_gateway()

@pytest.mark.asyncio
async def test_enforce_auth_failure(hass: HomeAssistantType, es_aioclient_mock: AiohttpClientMocker):
    """Enforce should throw when missing privileges."""

    es_url = "http://test_enforce_auth_failure:9200"
    mock_es_initialization(
        es_aioclient_mock,
        es_url,
        mock_index_authorization_error=True
    )

    config = build_full_config({"url": es_url, "username": "test"})

    gateway = ElasticsearchGateway(config)
    await gateway.async_init()

    instance = ESPrivilegeCheck(gateway)
    with pytest.raises(InsufficientPrivileges):
        await instance.enforce_privileges(config)

    await gateway.async_stop_gateway()

@pytest.mark.asyncio
async def test_enforce_auth_success(hass: HomeAssistantType, es_aioclient_mock: AiohttpClientMocker):
    """Enforce should not throw when not missing privileges."""

    es_url = "http://test_enforce_auth_success:9200"
    mock_es_initialization(
        es_aioclient_mock,
        es_url
    )

    config = build_full_config({"url": es_url, "username": "test"})

    gateway = ElasticsearchGateway(config)
    await gateway.async_init()

    instance = ESPrivilegeCheck(gateway)
    await instance.enforce_privileges(config)

    await gateway.async_stop_gateway()

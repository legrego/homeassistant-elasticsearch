"""Test ES Privilege Check."""

import pytest
from elasticsearch.const import (
    CONF_AUTH_BASIC_AUTH,
    CONF_AUTH_METHOD,
    CONF_INDEX_MODE,
    DOMAIN,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.typing import HomeAssistantType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.elasticsearch.config_flow import (
    build_new_data,
    build_new_options,
)
from custom_components.elasticsearch.errors import CannotConnect, InsufficientPrivileges
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from custom_components.elasticsearch.es_privilege_check import ESPrivilegeCheck
from tests.test_util.es_startup_mocks import mock_es_initialization


@pytest.mark.asyncio
async def test_bad_connection(
    hass: HomeAssistantType, es_aioclient_mock: AiohttpClientMocker
):
    """Test graceful error handling."""

    es_url = "http://test-bad-connection:9200"
    mock_es_initialization(es_aioclient_mock, es_url)

    mock_entry = MockConfigEntry(
        unique_id="test_authentication_error",
        domain=DOMAIN,
        version=5,
        data=build_new_data({"url": es_url}),
        options=build_new_options(),
        title="ES Config",
    )

    gateway = ElasticsearchGateway(config_entry=mock_entry)
    await gateway.async_init()

    es_aioclient_mock.clear_requests()
    mock_es_initialization(es_aioclient_mock, mock_connection_error=True)

    instance = ESPrivilegeCheck(gateway=gateway, config_entry=mock_entry)

    with pytest.raises(CannotConnect):
        await instance.check_privileges()

    await gateway.async_stop_gateway()


@pytest.mark.asyncio
async def test_successful_modern_privilege_check(
    hass: HomeAssistantType, es_aioclient_mock: AiohttpClientMocker
):
    """Test successful privilege check."""

    es_url = "http://test_successful_modern_privilege_check:9200"
    mock_es_initialization(es_aioclient_mock, es_url)

    mock_entry = MockConfigEntry(
        unique_id="test_authentication_error",
        domain=DOMAIN,
        version=5,
        data=build_new_data(
            {
                "url": es_url,
                CONF_INDEX_MODE: "datastream",
                CONF_AUTH_METHOD: CONF_AUTH_BASIC_AUTH,
                CONF_USERNAME: "test",
            }
        ),
        options=build_new_options(),
        title="ES Config",
    )

    gateway = ElasticsearchGateway(config_entry=mock_entry)
    await gateway.async_init()

    instance = ESPrivilegeCheck(gateway=gateway, config_entry=mock_entry)
    result = await instance.check_privileges()
    assert result.has_all_requested

    result = await instance.enforce_privileges()
    assert result is None

    await gateway.async_stop_gateway()


@pytest.mark.asyncio
async def test_successful_modern_privilege_check_missing_index_privilege(
    hass: HomeAssistantType, es_aioclient_mock: AiohttpClientMocker
):
    """Test successful privilege check with missing index privileges."""

    es_url = "http://test_successful_modern_privilege_check:9200"

    mock_es_initialization(
        es_aioclient_mock, es_url, mock_modern_datastream_authorization_error=True
    )

    mock_entry = MockConfigEntry(
        unique_id="test_authentication_error",
        domain=DOMAIN,
        version=5,
        data=build_new_data(
            {
                "url": es_url,
                CONF_INDEX_MODE: "datastream",
                CONF_AUTH_METHOD: CONF_AUTH_BASIC_AUTH,
                CONF_USERNAME: "test",
                CONF_PASSWORD: "test",
            }
        ),
        options=build_new_options(),
        title="ES Config",
    )

    gateway = ElasticsearchGateway(config_entry=mock_entry)
    await gateway.async_init()

    instance = ESPrivilegeCheck(gateway=gateway, config_entry=mock_entry)
    result = await instance.check_privileges()
    assert result.has_all_requested is False
    assert result.missing_cluster_privileges == []
    assert result.missing_index_privileges == {
        "metrics-homeassistant.*": ["create"],
    }

    with pytest.raises(InsufficientPrivileges):
        await instance.enforce_privileges()

    await gateway.async_stop_gateway()


@pytest.mark.asyncio
async def test_successful_legacy_privilege_check(
    hass: HomeAssistantType, es_aioclient_mock: AiohttpClientMocker
):
    """Test successful privilege check."""

    es_url = "http://test_successful_privilege_check:9200"
    mock_es_initialization(es_aioclient_mock, es_url)

    mock_entry = MockConfigEntry(
        unique_id="test_authentication_error",
        domain=DOMAIN,
        version=5,
        data=build_new_data(
            {
                "url": es_url,
                CONF_AUTH_METHOD: CONF_AUTH_BASIC_AUTH,
                CONF_USERNAME: "test",
                CONF_PASSWORD: "test",
            }
        ),
        options=build_new_options(),
        title="ES Config",
    )

    gateway = ElasticsearchGateway(config_entry=mock_entry)
    await gateway.async_init()

    instance = ESPrivilegeCheck(gateway=gateway, config_entry=mock_entry)
    result = await instance.check_privileges()
    assert result.has_all_requested

    await gateway.async_stop_gateway()


@pytest.mark.asyncio
async def test_successful_legacy_privilege_check_missing_index_privilege(
    hass: HomeAssistantType, es_aioclient_mock: AiohttpClientMocker
):
    """Test successful privilege check with missing index privileges."""

    es_url = "http://test_successful_privilege_check:9200"
    mock_es_initialization(
        es_aioclient_mock, es_url, mock_legacy_index_authorization_error=True
    )

    mock_entry = MockConfigEntry(
        unique_id="test_authentication_error",
        domain=DOMAIN,
        version=5,
        data=build_new_data(
            {
                "url": es_url,
                CONF_AUTH_METHOD: CONF_AUTH_BASIC_AUTH,
                CONF_USERNAME: "test",
                CONF_PASSWORD: "test",
            }
        ),
        options=build_new_options(),
        title="ES Config",
    )

    gateway = ElasticsearchGateway(mock_entry)
    await gateway.async_init()

    instance = ESPrivilegeCheck(gateway=gateway, config_entry=mock_entry)
    result = await instance.check_privileges()
    assert result.has_all_requested is False
    assert result.missing_cluster_privileges == []
    assert result.missing_index_privileges == {"hass-events*": ["index"]}

    with pytest.raises(InsufficientPrivileges):
        await instance.enforce_privileges()

    await gateway.async_stop_gateway()


@pytest.mark.asyncio
async def test_enforce_auth_failure(
    hass: HomeAssistantType, es_aioclient_mock: AiohttpClientMocker
):
    """Enforce should throw when missing privileges."""

    es_url = "http://test_enforce_auth_failure:9200"
    mock_es_initialization(
        es_aioclient_mock, es_url, mock_legacy_index_authorization_error=True
    )

    mock_entry = MockConfigEntry(
        unique_id="test_authentication_error",
        domain=DOMAIN,
        version=5,
        data=build_new_data(
            {
                "url": es_url,
                CONF_AUTH_METHOD: CONF_AUTH_BASIC_AUTH,
                CONF_USERNAME: "test",
                CONF_PASSWORD: "test",
            }
        ),
        options=build_new_options(),
        title="ES Config",
    )

    gateway = ElasticsearchGateway(config_entry=mock_entry)
    await gateway.async_init()

    instance = ESPrivilegeCheck(gateway=gateway, config_entry=mock_entry)
    with pytest.raises(InsufficientPrivileges):
        await instance.enforce_privileges()

    await gateway.async_stop_gateway()


@pytest.mark.asyncio
async def test_enforce_auth_success(
    hass: HomeAssistantType, es_aioclient_mock: AiohttpClientMocker
):
    """Enforce should not throw when not missing privileges."""

    es_url = "http://test_enforce_auth_success:9200"
    mock_es_initialization(es_aioclient_mock, es_url)

    mock_entry = MockConfigEntry(
        unique_id="test_authentication_error",
        domain=DOMAIN,
        version=5,
        data=build_new_data(
            {
                "url": es_url,
                CONF_AUTH_METHOD: CONF_AUTH_BASIC_AUTH,
                CONF_USERNAME: "test",
                CONF_PASSWORD: "test",
            }
        ),
        options=build_new_options(),
        title="ES Config",
    )

    gateway = ElasticsearchGateway(mock_entry)
    await gateway.async_init()

    instance = ESPrivilegeCheck(gateway=gateway, config_entry=mock_entry)
    await instance.enforce_privileges()

    result = await instance.enforce_privileges()
    assert result is None

    await gateway.async_stop_gateway()

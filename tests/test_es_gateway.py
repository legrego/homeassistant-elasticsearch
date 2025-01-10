"""Tests for the Elasticsearch Gateway."""
# noqa: F401 # pylint: disable=redefined-outer-name

import os
import ssl
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import elastic_transport
import elasticsearch8
import pytest
from aiohttp import client_exceptions
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    CannotConnect,
    InsufficientPrivileges,
    UnsupportedVersion,
    UntrustedCertificate,
)
from custom_components.elasticsearch.es_gateway import (
    ElasticsearchGateway,
)
from custom_components.elasticsearch.es_gateway_8 import Elasticsearch8Gateway, Gateway8Settings
from elastic_transport import BaseNode, ObjectApiResponse
from elasticsearch8._async.client import AsyncElasticsearch
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from syrupy.assertion import SnapshotAssertion

from tests import const
from tests.const import (
    CLUSTER_INFO_8DOT0_RESPONSE_BODY,
    CLUSTER_INFO_8DOT14_RESPONSE_BODY,
    TEST_CONFIG_ENTRY_DATA_URL,
)


def mock_es_exception(exception, message="None"):
    """Return an AsyncMock that mocks an Elasticsearch API response."""

    # if it's a TransportError, we provide message
    if issubclass(exception, elasticsearch8.TransportError):
        return AsyncMock(side_effect=exception(message=message))

    # if it's an APIerror we provide meta, body, message
    if issubclass(exception, elasticsearch8.ApiError):
        return AsyncMock(side_effect=exception(meta=MagicMock, body=None, message=message))


def mock_es_response(body):
    """Return an AsyncMock that mocks an Elasticsearch API response."""
    return AsyncMock(return_value=ObjectApiResponse(meta={}, body=body))


@pytest.fixture
async def cannot_connect_error(gateway: ElasticsearchGateway):
    """Return a CannotConnect error."""

    return elasticsearch8.exceptions.TransportError(
        message="There was a transport error",
        errors=(),
    )


@pytest.fixture
async def mock_elasticsearch_client():
    """Return a mock Elasticsearch client."""
    return MagicMock(AsyncElasticsearch)


class Test_Init:
    """Initialization tests for the Elasticsearch Gateway."""

    @pytest.fixture
    def gateway_settings(self) -> Gateway8Settings:
        """Return a Gateway8Settings instance."""
        return Gateway8Settings(
            url=const.TEST_CONFIG_ENTRY_DATA_URL,
            username="username",
            password="password",
            verify_certs=True,
            ca_certs=None,
            request_timeout=30,
            minimum_version=None,
        )

    @pytest.fixture
    async def gateway_mock_client(self, gateway_settings, mock_elasticsearch_client):
        """Return a mock Elasticsearch client."""
        gateway_settings.to_client = MagicMock(return_value=mock_elasticsearch_client)

        gateway = Elasticsearch8Gateway(gateway_settings=gateway_settings)

        gateway._client.info = mock_es_response(CLUSTER_INFO_8DOT14_RESPONSE_BODY)

        gateway._client.security = MagicMock()
        gateway._client.security.has_privileges = mock_es_response({"has_all_requested": True})

        gateway._client.xpack = MagicMock()
        gateway._client.xpack.usage = mock_es_response({"security": {"available": True, "enabled": True}})

        return gateway

    @pytest.fixture
    async def gateway(self, gateway_settings):
        """Return an Elasticsearch8Gateway instance."""
        gateway = Elasticsearch8Gateway(gateway_settings=gateway_settings)

        yield gateway

        await gateway.stop()

    class Test_Initialization:
        """Initialization tests for the Elasticsearch8 Gateway."""

        async def test_init_basic_auth(self) -> None:
            """Test initializing a gateway with basic authentication."""
            gateway = Elasticsearch8Gateway(
                gateway_settings=Gateway8Settings(
                    url=const.TEST_CONFIG_ENTRY_DATA_URL, username="username", password="password"
                )
            )

            assert gateway._client._headers["Authorization"].startswith("Basic")

        async def test_init_api_key_auth(self) -> None:
            """Test initializing a gateway with API Key authentication."""

            # API Key Authentication
            gateway = Elasticsearch8Gateway(
                gateway_settings=Gateway8Settings(
                    url=const.TEST_CONFIG_ENTRY_DATA_URL,
                    api_key="api",
                )
            )

            assert gateway._client._headers["Authorization"].startswith("ApiKey")

        async def test_init_no_auth(self) -> None:
            """Test initializing a gateway with no authentication."""
            gateway = Elasticsearch8Gateway(
                gateway_settings=Gateway8Settings(
                    url=const.TEST_CONFIG_ENTRY_DATA_URL_INSECURE,
                )
            )

            assert gateway._client._headers.get("Authorization", None) is None

        @pytest.mark.parametrize(
            ("verify_certs", "verify_hostname", "expected_verify_mode", "expected_verify_hostname"),
            [
                (True, True, ssl.CERT_REQUIRED, True),
                (True, False, ssl.CERT_REQUIRED, False),
                (False, True, ssl.CERT_NONE, False),
                (False, False, ssl.CERT_NONE, False),
            ],
            ids=[
                "Verify Certs and Verify Hostname",
                "Verify Certs and Don't Verify Hostname",
                "No Certs and Ignore Verify Hostname",
                "No Certs and Don't Verify Hostname",
            ],
        )
        async def test_init_tls(
            self, verify_certs, verify_hostname, expected_verify_mode, expected_verify_hostname
        ) -> None:
            """Test initializing a gateway with various TLS settings."""

            gateway = Elasticsearch8Gateway(
                gateway_settings=Gateway8Settings(
                    url=const.TEST_CONFIG_ENTRY_DATA_URL,
                    verify_certs=verify_certs,
                    verify_hostname=verify_hostname,
                )
            )

            node: BaseNode = gateway._client._transport.node_pool.get()
            ssl_context = node._ssl_context  # type: ignore[reportAttributeAccessIssue]

            assert ssl_context.check_hostname == expected_verify_hostname
            assert ssl_context.verify_mode == expected_verify_mode

        async def test_init_tls_custom_ca(self, snapshot: SnapshotAssertion) -> None:
            """Test initializing a gateway with TLS and custom ca cert."""

            # cert is located in "certs/http_ca.crt" relative to this file, get the absolute path
            current_directory = os.path.dirname(os.path.abspath(__file__))

            gateway = Elasticsearch8Gateway(
                gateway_settings=Gateway8Settings(
                    url=const.TEST_CONFIG_ENTRY_DATA_URL,
                    verify_certs=True,
                    verify_hostname=True,
                    ca_certs=f"{current_directory}/certs/http_ca.crt",
                )
            )

            node: BaseNode = gateway._client._transport.node_pool.get()
            ssl_context = node._ssl_context  # type: ignore[reportAttributeAccessIssue]

            for cert in ssl_context.get_ca_certs():
                if cert["serialNumber"] == "25813FA4F725F5566FCF014C0B8B0973E710DF90":
                    assert cert == snapshot

            assert snapshot.num_executions == 1

        async def test_async_init(self, gateway_mock_client) -> None:
            """Test the async initialization with proper permissions on a supported version."""

            assert await gateway_mock_client.async_init() is None

        async def test_async_init_unsupported_version(self, gateway_mock_client) -> None:
            """Test the async_init method when the target cluster is running an unsupported version."""

            gateway_mock_client._client.info = mock_es_response(CLUSTER_INFO_8DOT0_RESPONSE_BODY)

            with pytest.raises(UnsupportedVersion):
                assert await gateway_mock_client.async_init() is None

        async def test_async_init_unauthenticated(self, gateway_mock_client) -> None:
            """Test the async_init method with an unauthenticated session."""

            gateway_mock_client._client.info = mock_es_exception(elasticsearch8.AuthenticationException)

            with pytest.raises(AuthenticationRequired):
                await gateway_mock_client.async_init()

        @pytest.mark.asyncio
        async def test_async_init_ssl_error(self, gateway_mock_client):
            """Test async_init when there is a TLS Certificate issue."""

            gateway_mock_client._client.info = mock_es_exception(elastic_transport.TlsError)

            with pytest.raises(UntrustedCertificate):
                await gateway_mock_client.async_init()

        async def test_async_init_unauthorized(self, gateway_mock_client) -> None:
            """Test the async_init method unauthorized."""

            gateway_mock_client._client.info = mock_es_exception(elasticsearch8.AuthorizationException)

            with pytest.raises(InsufficientPrivileges):
                assert await gateway_mock_client.async_init() is None

        async def test_async_init_unreachable(self, gateway_mock_client) -> None:
            """Test the async_init method with unreachable Elasticsearch."""

            gateway_mock_client._client.info = mock_es_exception(elasticsearch8.ConnectionTimeout)

            with pytest.raises(CannotConnect):
                assert await gateway_mock_client.async_init() is None

    class Test_Failures:
        """Test failure scenarios during initialization."""

        @pytest.mark.asyncio
        async def test_async_init_ssl_error(self, gateway, es_mock_builder):
            """Test async_init when there are insufficient privileges."""

            es_mock_builder.with_selfsigned_certificate()

            with pytest.raises(UntrustedCertificate):
                await gateway.async_init()

        async def test_async_init_unauthorized(self, gateway: ElasticsearchGateway, es_mock_builder) -> None:
            """Test the async_init method with unauthorized user."""

            # es_mock_builder.as_elasticsearch_8_17().with_incorrect_permissions()
            es_mock_builder.with_server_error(status=403)
            with pytest.raises(InsufficientPrivileges):
                assert await gateway.async_init() is None

        async def test_async_init_unreachable(self, gateway: ElasticsearchGateway, es_mock_builder) -> None:
            """Test the async_init method with unreachable Elasticsearch."""

            es_mock_builder.with_server_timeout()

            with pytest.raises(CannotConnect):
                assert await gateway.async_init() is None


class Test_Public_Functions:
    """Public function tests for the Elasticsearch Gateway."""

    async def test_ping(self, gateway: ElasticsearchGateway, es_aioclient_mock: AiohttpClientMocker) -> None:
        """Test the ping method."""

        temp = gateway.ping
        gateway.ping = AsyncMock(return_value=True)
        gateway.has_security = AsyncMock(return_value=True)
        gateway._has_required_privileges = AsyncMock(return_value=True)

        es_aioclient_mock.get(
            f"{TEST_CONFIG_ENTRY_DATA_URL}",
            status=200,
            json=CLUSTER_INFO_8DOT14_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
        )

        gateway.ping = temp

        await gateway.async_init()

        assert await gateway.ping() is True

    async def test_ping_fail(
        self, gateway: ElasticsearchGateway, es_aioclient_mock: AiohttpClientMocker
    ) -> None:
        """Test the ping method."""
        temp = gateway.ping
        gateway.ping = AsyncMock(return_value=True)
        gateway.has_security = AsyncMock(return_value=True)
        gateway._has_required_privileges = AsyncMock(return_value=True)

        es_aioclient_mock.get(
            f"{TEST_CONFIG_ENTRY_DATA_URL}/",
            exc=Exception,
        )

        gateway.ping = temp

        assert await gateway.ping() is False

    async def test_has_privileges(
        self, initialized_gateway: ElasticsearchGateway, es_aioclient_mock: AiohttpClientMocker
    ) -> None:
        """Test the has_privileges method."""

        es_aioclient_mock.get(
            url=f"{TEST_CONFIG_ENTRY_DATA_URL}/_xpack/usage",
            json={
                "security": {"available": True, "enabled": True},
            },
        )
        es_aioclient_mock.post(
            f"{TEST_CONFIG_ENTRY_DATA_URL}/_security/user/_has_privileges",
            status=200,
            json={
                "has_all_requested": True,
            },
        )

        assert await initialized_gateway.has_privileges({}) == {
            "has_all_requested": True,
        }

    async def test_get_index_template(
        self,
        initialized_gateway: ElasticsearchGateway,
        es_aioclient_mock: AiohttpClientMocker,
        verify_cleanup,
    ) -> None:
        """Test the get_index_template method."""

        es_aioclient_mock.get(
            f"{TEST_CONFIG_ENTRY_DATA_URL}/_index_template/test_template",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={},
        )

        assert await initialized_gateway.get_index_template("test_template") == {}

    async def test_get_index_template_fail(
        self, initialized_gateway: ElasticsearchGateway, es_aioclient_mock: AiohttpClientMocker
    ) -> None:
        """Test the get_index_template method."""

        es_aioclient_mock.get(
            f"{TEST_CONFIG_ENTRY_DATA_URL}/_index_template/test_template",
            status=404,
            json={},
        )

        assert await initialized_gateway.get_index_template("test_template", ignore=[404]) == {}

    async def test_get_index_template_exception(
        self,
        initialized_gateway: ElasticsearchGateway,
        es_aioclient_mock: AiohttpClientMocker,
        cannot_connect_error,
    ) -> None:
        """Test the get_index_template method."""
        es_aioclient_mock.get(
            f"{TEST_CONFIG_ENTRY_DATA_URL}/_index_template/test_template",
            exc=cannot_connect_error,
        )

        # type of cannot_connect_error
        with pytest.raises(CannotConnect):
            await initialized_gateway.get_index_template("test_template")

    async def test_put_index_template(
        self, initialized_gateway: ElasticsearchGateway, es_aioclient_mock: AiohttpClientMocker
    ) -> None:
        """Test the put_index_template method."""

        es_aioclient_mock.put(
            f"{TEST_CONFIG_ENTRY_DATA_URL}/_index_template/test_template",
            status=200,
            json={},
        )

        assert await initialized_gateway.put_index_template("test_template", {}) == {}

        method, url, data, headers = es_aioclient_mock.mock_calls[0]

        assert method == "PUT"
        assert str(url) == f"{TEST_CONFIG_ENTRY_DATA_URL}/_index_template/test_template"
        assert data == b"{}"


class Test_Connection_Test:
    """Test Connection state transitions."""

    async def test_check_connection_first_time_success(self, gateway: ElasticsearchGateway) -> None:
        """Test check_connection method when connecting for the first time successfully."""
        gateway.ping = AsyncMock(return_value=True)
        gateway._logger.info = MagicMock()
        gateway._logger.error = MagicMock()

        result = await gateway.check_connection()

        assert result is True
        gateway._logger.info.assert_called_once_with("Connection to Elasticsearch is established.")
        gateway._logger.error.assert_not_called()

    async def test_check_connection_first_time_failure(self, gateway: ElasticsearchGateway) -> None:
        """Test check_connection method when connecting for the first time fails."""
        gateway.ping = AsyncMock(return_value=False)
        gateway._logger.info = MagicMock()
        gateway._logger.error = MagicMock()

        result = await gateway.check_connection()

        assert result is False
        gateway._logger.error.assert_called_once_with("Failed to establish connection to Elasticsearch.")
        gateway._logger.info.assert_not_called()

    async def test_check_connection_maintained(self, gateway: ElasticsearchGateway) -> None:
        """Test check_connection method when connection is maintained."""
        gateway._previous_ping = True
        gateway.ping = AsyncMock(return_value=True)
        gateway._logger.debug = MagicMock()

        result = await gateway.check_connection()

        assert result is True
        gateway._logger.debug.assert_called_once_with("Connection to Elasticsearch is still available.")

    async def test_check_connection_lost(self, gateway: ElasticsearchGateway) -> None:
        """Test check_connection method when connection is lost."""
        gateway._previous_ping = True
        gateway.ping = AsyncMock(return_value=False)
        gateway._logger.error = MagicMock()
        gateway._logger.debug = MagicMock()

        result = await gateway.check_connection()

        assert result is False
        gateway._logger.error.assert_called_once_with("Connection to Elasticsearch has been lost.")
        gateway._logger.debug.assert_not_called()

    async def test_check_connection_down(self, gateway: ElasticsearchGateway) -> None:
        """Test check_connection method when connection is still down."""
        gateway._previous_ping = False
        gateway.ping = AsyncMock(return_value=False)
        gateway._logger.debug = MagicMock()

        result = await gateway.check_connection()

        assert result is False
        gateway._logger.debug.assert_called_once_with("Connection to Elasticsearch is still down.")

    async def test_check_connection_reestablished(self, gateway: ElasticsearchGateway) -> None:
        """Test check_connection method when connection is reestablished."""
        gateway._previous_ping = False
        gateway.ping = AsyncMock(return_value=True)
        gateway._logger.info = MagicMock()

        result = await gateway.check_connection()

        assert result is True
        gateway._logger.info.assert_called_once_with("Connection to Elasticsearch has been reestablished.")


class Test_Exception_Conversion:
    """Test the conversion of Elasticsearch exceptions to custom exceptions."""

    @pytest.mark.parametrize(
        ("status_code", "expected_response"),
        [
            (404, CannotConnect),
            (401, AuthenticationRequired),
            (403, InsufficientPrivileges),
            (500, CannotConnect),
            (400, CannotConnect),
            (502, CannotConnect),
            (503, CannotConnect),
            (200, None),
        ],
        ids=[
            "404 to CannotConnect",
            "401 to AuthenticationRequired",
            "403 to InsufficientPrivileges",
            "500 to ServerError",
            "400 to ClientError",
            "502 to CannotConnect",
            "503 to CannotConnect",
            "200 to None",
        ],
    )
    async def test_simple_return_codes(
        self,
        gateway: ElasticsearchGateway,
        es_aioclient_mock,
        status_code: int,
        expected_response: Any,
    ) -> None:
        """Test the error converter."""
        temp = gateway.info
        gateway.info = AsyncMock(return_value=CLUSTER_INFO_8DOT14_RESPONSE_BODY)
        gateway.has_security = AsyncMock(return_value=True)
        gateway._has_required_privileges = AsyncMock(return_value=True)
        await gateway.async_init()
        gateway.info = temp

        es_aioclient_mock.get(
            f"{TEST_CONFIG_ENTRY_DATA_URL}",
            status=status_code,
            json=CLUSTER_INFO_8DOT14_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
        )

        if expected_response is None:
            assert await gateway.info() == CLUSTER_INFO_8DOT14_RESPONSE_BODY
        else:
            with pytest.raises(expected_response):
                await gateway.info()

    @pytest.mark.parametrize(
        ("aiohttp_exception", "expected_exception"),
        [
            (client_exceptions.ServerConnectionError(), CannotConnect),
            # child exceptions of ServerConnectionError
            (
                client_exceptions.ServerFingerprintMismatch(expected=b"", got=b"", host="host", port=0),
                CannotConnect,
            ),
            (client_exceptions.ServerDisconnectedError(), CannotConnect),
            (client_exceptions.ServerTimeoutError(), CannotConnect),
            # (client_exceptions.ClientError(), ClientError),
            # child exceptions of ClientError
            # (client_exceptions.ClientResponseError(), ClientError),
            (client_exceptions.ClientPayloadError(), CannotConnect),
            (client_exceptions.ClientConnectionError(), CannotConnect),
            # child exceptions of ClientConnectionError
            # (
            #     client_exceptions.ClientSSLError(connection_key=MagicMock(), os_error=Exception("AHHHHH")),
            #     SSLError,
            # ),
            # child exceptions of ClientSSLError
            # (client_exceptions.ClientConnectorSSLError(), SSLError),
        ],
        ids=[
            "ServerConnectionError to CannotConnect",
            "ServerFingerprintMismatch to CannotConnect",
            "ServerDisconnectedError to CannotConnect",
            "ServerTimeoutError to CannotConnect",
            # "ClientError to ClientError",
            # "ClientResponseError to ClientError",
            "ClientPayloadError to CannotConnect",
            "ClientConnectionError to CannotConnect",
            # "ClientSSLError to SSLConnectionError",
            # "ClientConnectorSSLError to CannotConnect",
        ],
    )
    async def test_simple_web_exceptions(
        self, aiohttp_exception, expected_exception, es_aioclient_mock, gateway
    ) -> None:
        """Test the error converter."""
        temp = gateway.info
        gateway.info = AsyncMock(return_value=CLUSTER_INFO_8DOT14_RESPONSE_BODY)
        gateway.has_security = AsyncMock(return_value=True)
        gateway._has_required_privileges = AsyncMock(return_value=True)
        await gateway.async_init()
        gateway.info = temp

        es_aioclient_mock.get(f"{TEST_CONFIG_ENTRY_DATA_URL}", exc=aiohttp_exception)

        with pytest.raises(expected_exception):
            await gateway.info()

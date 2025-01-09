"""Tests for the Elasticsearch Gateway."""
# noqa: F401 # pylint: disable=redefined-outer-name

import os
import ssl
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import elasticsearch8
import pytest
from aiohttp import client_exceptions
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    CannotConnect,
    ClientError,
    InsufficientPrivileges,
    ServerError,
    SSLError,
    UnsupportedVersion,
    UntrustedCertificate,
)
from custom_components.elasticsearch.es_gateway import (
    ElasticsearchGateway,
)
from custom_components.elasticsearch.es_gateway_8 import Elasticsearch8Gateway, Gateway8Settings
from elastic_transport import BaseNode
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from tests import const
from tests.const import (
    CLUSTER_INFO_8DOT14_RESPONSE_BODY,
    TEST_CONFIG_ENTRY_DATA_URL,
)


@pytest.fixture
async def cannot_connect_error(gateway: ElasticsearchGateway):
    """Return a CannotConnect error."""

    return elasticsearch8.exceptions.TransportError(
        message="There was a transport error",
        errors=(),
    )


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
    async def gateway(self, gateway_settings):
        """Return an Elasticsearch8Gateway instance."""
        gateway = Elasticsearch8Gateway(gateway_settings=gateway_settings)

        yield gateway

        await gateway.stop()

    class Test_ElasticsearchServerless:
        """Initialization tests for the Elasticsearch8 Gateway connecting to serverless."""

        async def test_esserverless_async_init_basic_auth(self, gateway_settings, es_mock_builder) -> None:
            """Test initializing a gateway to serverless with basic authentication."""
            gateway = Elasticsearch8Gateway(gateway_settings=gateway_settings)

            es_mock_builder.as_elasticsearch_serverless().with_correct_permissions()

            assert await gateway.async_init() is None
            assert gateway.settings == gateway_settings
            assert gateway._client is not None
            assert gateway._client._headers["Authorization"].startswith("Basic")

            await gateway.stop()

        async def test_esserverless_async_init_api_key_auth(self, gateway_settings, es_mock_builder) -> None:
            """Test initializing a gateway to serverless with api key authentication."""

            # API Key Authentication
            gateway = Elasticsearch8Gateway(
                gateway_settings=Gateway8Settings(
                    url=const.TEST_CONFIG_ENTRY_DATA_URL,
                    api_key="api",
                )
            )

            es_mock_builder.reset().as_elasticsearch_serverless().with_correct_permissions()

            assert await gateway.async_init() is None
            assert gateway._client is not None
            assert gateway._client._headers["Authorization"].startswith("ApiKey")

            await gateway.stop()

        async def test_esserverless_async_init_with_tls(self, gateway_settings, es_mock_builder) -> None:
            """Test initializing a gateway to serverless with TLS."""
            gateway = Elasticsearch8Gateway(
                gateway_settings=Gateway8Settings(
                    url=const.TEST_CONFIG_ENTRY_DATA_URL,
                    api_key="api",
                    verify_certs=True,
                    verify_hostname=True,
                )
            )

            es_mock_builder.as_elasticsearch_serverless().with_correct_permissions()

            assert await gateway.async_init() is None

            assert gateway._client is not None
            node: BaseNode = gateway._client._transport.node_pool.get()
            assert node is not None
            assert hasattr(node, "_ssl_context")
            if hasattr(node, "_ssl_context"):
                assert node._ssl_context.check_hostname is True
                assert node._ssl_context.verify_mode == ssl.CERT_REQUIRED

            await gateway.stop()

    class Test_ElasticsearchStateful:
        """Initialization tests for the Elasticsearch8 Gateway."""

        async def test_es8_async_init_basic_auth(self, es_mock_builder) -> None:
            """Test initializing a gateway with basic authentication."""
            gateway = Elasticsearch8Gateway(
                gateway_settings=Gateway8Settings(
                    url=const.TEST_CONFIG_ENTRY_DATA_URL, username="username", password="password"
                )
            )

            es_mock_builder.as_elasticsearch_8_17(with_security=True).with_correct_permissions()

            assert await gateway.async_init() is None
            assert gateway._client is not None
            assert gateway._client._headers["Authorization"].startswith("Basic")

            await gateway.stop()

        async def test_es8_async_init_api_key_auth(self, es_mock_builder) -> None:
            """Test initializing a gateway with API Key authentication."""

            # API Key Authentication
            gateway = Elasticsearch8Gateway(
                gateway_settings=Gateway8Settings(
                    url=const.TEST_CONFIG_ENTRY_DATA_URL,
                    api_key="api",
                )
            )

            es_mock_builder.reset().as_elasticsearch_8_17(with_security=True).with_correct_permissions()

            assert await gateway.async_init() is None
            assert gateway._client is not None
            assert gateway._client._headers["Authorization"].startswith("ApiKey")

            await gateway.stop()

        async def test_es8_async_init_no_auth(self, es_mock_builder) -> None:
            """Test initializing a gateway with no authentication."""
            gateway = Elasticsearch8Gateway(
                gateway_settings=Gateway8Settings(
                    url=const.TEST_CONFIG_ENTRY_DATA_URL_INSECURE,
                )
            )

            es_mock_builder.reset().as_elasticsearch_8_17(with_security=False)

            assert await gateway.async_init() is None
            assert gateway._client is not None
            assert gateway._client._headers.get("Authorization", None) is None

            await gateway.stop()

        async def test_es8_async_init_with_tls(self, es_mock_builder) -> None:
            """Test initializing a gateway with TLS."""

            gateway = Elasticsearch8Gateway(
                gateway_settings=Gateway8Settings(
                    url=const.TEST_CONFIG_ENTRY_DATA_URL,
                    verify_certs=True,
                    verify_hostname=True,
                )
            )

            es_mock_builder.as_elasticsearch_8_17(with_security=True).with_correct_permissions()

            assert await gateway.async_init() is None

            assert gateway._client is not None
            node: BaseNode = gateway._client._transport.node_pool.get()
            ssl_context = node._ssl_context  # type: ignore[reportAttributeAccessIssue]

            assert ssl_context.check_hostname is True
            assert ssl_context.verify_mode == ssl.CERT_REQUIRED

            await gateway.stop()

        async def test_es8_async_init_with_tls_custom_ca(self, es_mock_builder, snapshot) -> None:
            """Test initializing a gateway with TLS and custom ca."""

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

            es_mock_builder.as_elasticsearch_8_17(with_security=True).with_correct_permissions()

            assert await gateway.async_init() is None

            assert gateway._client is not None
            node: BaseNode = gateway._client._transport.node_pool.get()
            ssl_context = node._ssl_context  # type: ignore[reportAttributeAccessIssue]

            assert ssl_context.check_hostname is True
            assert ssl_context.verify_mode == ssl.CERT_REQUIRED

            ca_certs = ssl_context.get_ca_certs()

            added_cert: dict | None = None

            for cert in ca_certs:
                if cert["serialNumber"] == "25813FA4F725F5566FCF014C0B8B0973E710DF90":
                    added_cert = cert
                    break

            assert added_cert is not None
            assert added_cert == snapshot

            await gateway.stop()

        async def test_es8_async_init_with_tls_no_hostname(self, es_mock_builder) -> None:
            """Test initializing a gateway with TLS and no hostname checking."""
            gateway = Elasticsearch8Gateway(
                gateway_settings=Gateway8Settings(
                    url=const.TEST_CONFIG_ENTRY_DATA_URL,
                    verify_certs=True,
                    verify_hostname=False,
                )
            )

            es_mock_builder.reset().as_elasticsearch_8_17(with_security=True).with_correct_permissions()

            assert await gateway.async_init() is None

            assert gateway._client is not None
            node: BaseNode = gateway._client._transport.node_pool.get()
            ssl_context = node._ssl_context  # type: ignore[reportAttributeAccessIssue]

            assert ssl_context.check_hostname is False
            assert ssl_context.verify_mode == ssl.CERT_REQUIRED

            await gateway.stop()

        async def test_es8_async_init_without_tls(self, es_mock_builder, snapshot) -> None:
            """Test initializing a gateway without TLS."""
            gateway = Elasticsearch8Gateway(
                gateway_settings=Gateway8Settings(
                    url=const.TEST_CONFIG_ENTRY_DATA_URL,
                    verify_certs=False,
                    verify_hostname=False,
                )
            )

            es_mock_builder.reset().as_elasticsearch_8_17(with_security=True).with_correct_permissions()

            assert await gateway.async_init() is None

            assert gateway._client is not None
            node: BaseNode = gateway._client._transport.node_pool.get()
            ssl_context = node._ssl_context  # type: ignore[reportAttributeAccessIssue]

            assert ssl_context.check_hostname is False
            assert ssl_context.verify_mode == ssl.CERT_NONE

            await gateway.stop()

            # Without TLS but with Hostname Checking should not enable hostname checking but also should not error
            gateway = Elasticsearch8Gateway(
                gateway_settings=Gateway8Settings(
                    url=const.TEST_CONFIG_ENTRY_DATA_URL,
                    verify_certs=False,
                    verify_hostname=True,
                )
            )

            es_mock_builder.reset().as_elasticsearch_8_17(with_security=True).with_correct_permissions()

            assert await gateway.async_init() is None

            assert gateway._client is not None
            node: BaseNode = gateway._client._transport.node_pool.get()
            ssl_context = node._ssl_context  # type: ignore[reportAttributeAccessIssue]

            assert ssl_context.check_hostname is False
            assert ssl_context.verify_mode == ssl.CERT_NONE

            await gateway.stop()

        async def test_es8_async_init_minimum_supported(
            self, gateway: ElasticsearchGateway, es_mock_builder
        ) -> None:
            """Test the async_init method with unauthorized user."""

            es_mock_builder.as_elasticsearch_8_14().with_correct_permissions()

            assert await gateway.async_init() is None

    class Test_Failures:
        """Test failure scenarios during initialization."""

        @pytest.mark.asyncio
        async def test_async_init_ssl_error(self, gateway, es_mock_builder):
            """Test async_init when there are insufficient privileges."""

            es_mock_builder.with_untrusted_certificate()

            with pytest.raises(UntrustedCertificate):
                await gateway.async_init()

        async def test_async_init_unsupported(self, gateway: ElasticsearchGateway, es_mock_builder) -> None:
            """Test the async_init method with unauthorized user."""

            es_mock_builder.as_elasticsearch_8_0().with_correct_permissions()

            with pytest.raises(UnsupportedVersion):
                assert await gateway.async_init() is None

        async def test_async_init_unauthorized(self, gateway: ElasticsearchGateway, es_mock_builder) -> None:
            """Test the async_init method with unauthorized user."""

            es_mock_builder.as_elasticsearch_8_17().with_incorrect_permissions()

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
            (client_exceptions.ServerConnectionError(), ServerError),
            # child exceptions of ServerConnectionError
            (
                client_exceptions.ServerFingerprintMismatch(expected=b"", got=b"", host="host", port=0),
                SSLError,
            ),
            (client_exceptions.ServerDisconnectedError(), ServerError),
            (client_exceptions.ServerTimeoutError(), ServerError),
            # (client_exceptions.ClientError(), ClientError),
            # child exceptions of ClientError
            # (client_exceptions.ClientResponseError(), ClientError),
            (client_exceptions.ClientPayloadError(), ClientError),
            (client_exceptions.ClientConnectionError(), ClientError),
            # child exceptions of ClientConnectionError
            # (
            #     client_exceptions.ClientSSLError(connection_key=MagicMock(), os_error=Exception("AHHHHH")),
            #     SSLError,
            # ),
            # child exceptions of ClientSSLError
            # (client_exceptions.ClientConnectorSSLError(), SSLError),
            (
                client_exceptions.ClientConnectorCertificateError(
                    connection_key=MagicMock(), certificate_error=Exception("AHHHHH")
                ),
                UntrustedCertificate,
            ),
        ],
        ids=[
            "ServerConnectionError to ServerError",
            "ServerFingerprintMismatch to SSLError",
            "ServerDisconnectedError to ServerError",
            "ServerTimeoutError to ServerError",
            # "ClientError to ClientError",
            # "ClientResponseError to ClientError",
            "ClientPayloadError to ClientError",
            "ClientConnectionError to ClientError",
            # "ClientSSLError to SSLConnectionError",
            # "ClientConnectorSSLError to CannotConnect",
            "ClientConnectorCertificateError to UntrustedCertificate",
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

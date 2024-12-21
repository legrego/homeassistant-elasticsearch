"""Tests for the Elasticsearch Gateway."""
# noqa: F401 # pylint: disable=redefined-outer-name

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
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from tests.conftest import es_mocker
from tests.const import (
    CLUSTER_INFO_8DOT0_RESPONSE_BODY,
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


class Test_Initialization:
    """Initialization tests for the Elasticsearch Gateway."""

    def test_init(self, gateway) -> None:
        """Test the __init__ method."""

        assert gateway._settings is not None
        assert gateway._client is None

    async def test_async_init(self, gateway: ElasticsearchGateway) -> None:
        """Test the async_init method."""

        gateway.info = AsyncMock(return_value=CLUSTER_INFO_8DOT14_RESPONSE_BODY)
        gateway.has_security = AsyncMock(return_value=True)
        gateway._has_required_privileges = AsyncMock(return_value=True)

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


class Test_Integration_Tests:
    """Integration tests for the Elasticsearch Gateway."""

    async def test_async_init_mock_elasticsearch(
        self, gateway: ElasticsearchGateway, es_mock_builder: es_mocker
    ) -> None:
        """Test the async_init method."""

        es_mock_builder.as_elasticsearch_8_17().with_correct_permissions()

        assert await gateway.async_init() is None

    @pytest.mark.asyncio
    async def test_async_init_mock_elasticsearch_ssl_error(
        self, gateway, es_aioclient_mock: AiohttpClientMocker
    ):
        """Test async_init when there are insufficient privileges."""

        class MockTLSError(client_exceptions.ClientConnectorCertificateError):
            """Mocks an TLS error caused by an untrusted certificate.

            This is imperfect, but gets the job done for now.
            """

            def __init__(self) -> None:
                self._conn_key = MagicMock()
                self._certificate_error = Exception("AHHHH")

        es_aioclient_mock.get(f"{TEST_CONFIG_ENTRY_DATA_URL}", exc=MockTLSError)

        with pytest.raises(UntrustedCertificate):
            await gateway.async_init()

    async def test_async_init_mock_elasticsearch_serverless(
        self, gateway: ElasticsearchGateway, es_mock_builder: es_mocker
    ) -> None:
        """Test the async_init method with unauthorized user."""

        es_mock_builder.as_elasticsearch_serverless().with_correct_permissions()

        assert await gateway.async_init() is None

    async def test_async_init_mock_elasticsearch_minimum_supported(
        self, gateway: ElasticsearchGateway, es_mock_builder: es_mocker
    ) -> None:
        """Test the async_init method with unauthorized user."""

        es_mock_builder.as_elasticsearch_8_14().with_correct_permissions()

        assert await gateway.async_init() is None

    async def test_async_init_mock_elasticsearch_unsupported(
        self, gateway: ElasticsearchGateway, es_aioclient_mock: AiohttpClientMocker
    ) -> None:
        """Test the async_init method with unauthorized user."""


        es_aioclient_mock.get(
            f"{TEST_CONFIG_ENTRY_DATA_URL}",
            status=200,
            json=CLUSTER_INFO_8DOT0_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
        )

        with pytest.raises(UnsupportedVersion):
            assert await gateway.async_init() is None

    async def test_async_init_mock_elasticsearch_unauthorized(
        self, gateway: ElasticsearchGateway, es_aioclient_mock: AiohttpClientMocker
    ) -> None:
        """Test the async_init method with unauthorized user."""

        es_aioclient_mock.get(
            f"{TEST_CONFIG_ENTRY_DATA_URL}",
            status=200,
            json=CLUSTER_INFO_8DOT14_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
        )

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
                "has_all_requested": False,
            },
        )

        with pytest.raises(InsufficientPrivileges):
            assert await gateway.async_init() is None

    async def test_async_init_mock_elasticsearch_unreachable(
        self, gateway: ElasticsearchGateway, es_aioclient_mock: AiohttpClientMocker
    ) -> None:
        """Test the async_init method with unreachable Elasticsearch."""

        es_aioclient_mock.get(f"{TEST_CONFIG_ENTRY_DATA_URL}", exc=client_exceptions.ServerTimeoutError())

        with pytest.raises(CannotConnect):
            assert await gateway.async_init() is None


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

"""Tests for the Elasticsearch Gateway."""
# noqa: F401 # pylint: disable=redefined-outer-name

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import elasticsearch7
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
    UntrustedCertificate,
)
from custom_components.elasticsearch.es_gateway import (
    ElasticsearchGateway,
)
from custom_components.elasticsearch.es_gateway_7 import (
    Elasticsearch7Gateway,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from tests.const import (
    CLUSTER_INFO_8DOT11_RESPONSE_BODY,
    TEST_CONFIG_ENTRY_DATA_URL,
)


@pytest.fixture
async def cannot_connect_error(gateway: ElasticsearchGateway):
    """Return a CannotConnect error."""

    if isinstance(gateway, Elasticsearch7Gateway):
        return elasticsearch7.exceptions.TransportError("There was a transport error", 404, "Not Found")

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

        gateway.info = AsyncMock(return_value=True)
        gateway._has_required_privileges = AsyncMock(return_value=True)

        assert await gateway.async_init() is None


class Test_Public_Functions:
    """Public function tests for the Elasticsearch Gateway."""

    async def test_ping(self, gateway: ElasticsearchGateway, es_aioclient_mock: AiohttpClientMocker) -> None:
        """Test the ping method."""

        temp = gateway.ping
        gateway.ping = AsyncMock(return_value=True)
        gateway._has_required_privileges = AsyncMock(return_value=True)

        es_aioclient_mock.get(
            f"{TEST_CONFIG_ENTRY_DATA_URL}",
            status=200,
            json=CLUSTER_INFO_8DOT11_RESPONSE_BODY,
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
        self, gateway: ElasticsearchGateway, es_aioclient_mock: AiohttpClientMocker
    ) -> None:
        """Test the async_init method."""

        es_aioclient_mock.get(
            url=f"{TEST_CONFIG_ENTRY_DATA_URL}",
            json=CLUSTER_INFO_8DOT11_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
        )

        es_aioclient_mock.post(
            f"{TEST_CONFIG_ENTRY_DATA_URL}/_security/user/_has_privileges",
            status=200,
            json={
                "has_all_requested": True,
            },
        )

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

    async def test_async_init_mock_elasticsearch_unauthorized(
        self, gateway: ElasticsearchGateway, es_aioclient_mock: AiohttpClientMocker
    ) -> None:
        """Test the async_init method with unauthorized user."""

        es_aioclient_mock.get(
            f"{TEST_CONFIG_ENTRY_DATA_URL}",
            status=200,
            json=CLUSTER_INFO_8DOT11_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
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
        gateway.info = AsyncMock(return_value=True)
        gateway._has_required_privileges = AsyncMock(return_value=True)
        await gateway.async_init()
        gateway.info = temp

        es_aioclient_mock.get(
            f"{TEST_CONFIG_ENTRY_DATA_URL}",
            status=status_code,
            json=CLUSTER_INFO_8DOT11_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
        )

        if expected_response is None:
            assert await gateway.info() == CLUSTER_INFO_8DOT11_RESPONSE_BODY
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
        gateway.info = AsyncMock(return_value=True)
        gateway._has_required_privileges = AsyncMock(return_value=True)
        await gateway.async_init()
        gateway.info = temp

        es_aioclient_mock.get(f"{TEST_CONFIG_ENTRY_DATA_URL}", exc=aiohttp_exception)

        with pytest.raises(expected_exception):
            await gateway.info()

        # assert str(err.value) == msg

    # def test_error_converter_8(self) -> None:
    #     """Test the error converter."""
    #     client_exceptions.ClientConnectionError

    #     meta = MagicMock(spec=elasticsearch8.helpers.ApiResponseMeta)
    #     with pytest.raises(InsufficientPrivileges), Elasticsearch8Gateway._error_converter(msg=""):
    #         raise elasticsearch8.exceptions.AuthorizationException(
    #             message="Authorization error", meta=meta, body="test"
    #         )

    #     with pytest.raises(CannotConnect), Elasticsearch8Gateway._error_converter(msg=""):
    #         raise elasticsearch8.exceptions.TransportError("Transport error", errors=MagicMock())

    #     with pytest.raises(CannotConnect), Elasticsearch8Gateway._error_converter(msg=""):
    #         raise elasticsearch8.exceptions.ConnectionError("Connection error")

    #     with pytest.raises(CannotConnect), Elasticsearch8Gateway._error_converter(msg=""):
    #         raise elasticsearch8.exceptions.SSLError("SSL error")

    #     with pytest.raises(CannotConnect), Elasticsearch8Gateway._error_converter(msg=""):
    #         raise elasticsearch8.exceptions.ConnectionTimeout("Connection timeout")

    # def test_error_converter_7(self) -> None:
    #     """Test the error converter"""

    #     with pytest.raises(InsufficientPrivileges), Elasticsearch7Gateway._error_converter(msg=""):
    #         raise elasticsearch7.exceptions.AuthorizationException("Authorization error")

    #     with pytest.raises(CannotConnect), Elasticsearch7Gateway._error_converter(msg=""):
    #         raise elasticsearch7.exceptions.TransportError("Transport error", 404, "Not Found")

    #     with pytest.raises(CannotConnect), Elasticsearch7Gateway._error_converter(msg=""):
    #         raise elasticsearch7.exceptions.ConnectionError("Connection error")

    #     with pytest.raises(CannotConnect), Elasticsearch7Gateway._error_converter(msg=""):
    #         raise elasticsearch7.exceptions.SSLError("SSL error")

    #     with pytest.raises(CannotConnect), Elasticsearch7Gateway._error_converter(msg=""):
    #         raise elasticsearch7.exceptions.ConnectionTimeout("Connection timeout")

    #     with pytest.raises(CannotConnect), Elasticsearch7Gateway._error_converter(msg=""):
    #         raise elasticsearch7.exceptions.NotFoundError("Not found error")

    #     with pytest.raises(CannotConnect), Elasticsearch7Gateway._error_converter(msg=""):
    #         raise elasticsearch7.exceptions.ConflictError("Conflict error")


class Test_Unit_Tests:
    """Unit tests for the Elasticsearch gateway."""

    # def test_error_converter_8(
    #     self,
    # ) -> None:
    #     """Test the error converter."""

    #     meta = MagicMock(spec=ApiResponseMeta)
    #     with pytest.raises(AuthenticationRequired), Elasticsearch8Gateway._error_converter(msg=""):
    #         raise elasticsearch8.exceptions.AuthenticationException(
    #             message="Authentication error", meta=meta, body="test"
    #         )

    #     with pytest.raises(InsufficientPrivileges), Elasticsearch8Gateway._error_converter(msg=""):
    #         raise elasticsearch8.exceptions.AuthorizationException(
    #             "Authorization error", meta=meta, body="test"
    #         )

    #     with pytest.raises(CannotConnect), Elasticsearch8Gateway._error_converter(msg=""):
    #         raise elasticsearch8.exceptions.TransportError("Transport error", errors=MagicMock())

    #     with pytest.raises(CannotConnect), Elasticsearch8Gateway._error_converter(msg=""):
    #         raise elasticsearch8.exceptions.ConnectionError("Connection error")

    #     with pytest.raises(CannotConnect), Elasticsearch8Gateway._error_converter(msg=""):
    #         raise elasticsearch8.exceptions.SSLError("SSL error")

    #     with pytest.raises(CannotConnect), Elasticsearch8Gateway._error_converter(msg=""):
    #         raise elasticsearch8.exceptions.ConnectionTimeout("Connection timeout")

    # def test_error_converter_7(self) -> None:
    #     """Test the error converter"""

    #     with pytest.raises(AuthenticationRequired), Elasticsearch7Gateway._error_converter(msg=""):
    #         raise elasticsearch7.exceptions.AuthenticationException("Authentication error")

    #     with pytest.raises(InsufficientPrivileges), Elasticsearch7Gateway._error_converter(msg=""):
    #         raise elasticsearch7.exceptions.AuthorizationException("Authorization error")

    #     with pytest.raises(CannotConnect), Elasticsearch7Gateway._error_converter(msg=""):
    #         raise elasticsearch7.exceptions.TransportError("Transport error", 404, "Not Found")

    #     with pytest.raises(CannotConnect), Elasticsearch7Gateway._error_converter(msg=""):
    #         raise elasticsearch7.exceptions.ConnectionError("Connection error")

    #     with pytest.raises(CannotConnect), Elasticsearch7Gateway._error_converter(msg=""):
    #         raise elasticsearch7.exceptions.SSLError("SSL error")

    #     with pytest.raises(CannotConnect), Elasticsearch7Gateway._error_converter(msg=""):
    #         raise elasticsearch7.exceptions.ConnectionTimeout("Connection timeout")

    #     with pytest.raises(CannotConnect), Elasticsearch7Gateway._error_converter(msg=""):
    #         raise elasticsearch7.exceptions.NotFoundError("Not found error")

    #     with pytest.raises(CannotConnect), Elasticsearch7Gateway._error_converter(msg=""):
    #         raise elasticsearch7.exceptions.ConflictError("Conflict error")

    # except elasticsearch7.AuthenticationException as err:
    #     msg = "Authentication error connecting to Elasticsearch"
    #     raise AuthenticationRequired(msg) from err

    # except elasticsearch7.AuthorizationException as err:
    #     msg = "Authorization error connecting to Elasticsearch"
    #     raise InsufficientPrivileges(msg) from err

    # except elasticsearch7.TransportError as err:
    #     if isinstance(err.info, client_exceptions.ClientConnectorCertificateError):
    #         msg = "Untrusted certificate connecting to Elasticsearch"
    #         raise UntrustedCertificate(msg) from err
    #     if isinstance(err.info, client_exceptions.ClientConnectorError):
    #         msg = "Client error connecting to Elasticsearch"
    #         raise ClientError(msg) from err
    #     msg = "Error connecting to Elasticsearch"
    #     raise CannotConnect(msg) from err

    # except elasticsearch7.ElasticsearchException as err:
    #     msg = "Error connecting to Elasticsearch"
    #     raise ESIntegrationException(msg) from err

    # except Exception:
    #     self._logger.exception("Unknown error retrieving cluster info")
    #     raise


# @pytest.mark.parametrize(("gateway"), [es8_gateway, es7_gateway])
# class Test_Integration_Tests:
#     """Integration tests for the Elasticsearch Gateway"""

#     # @pytest.mark.asyncio


# class Test_Elasticsearch_Gateway:
#     """Test ElasticsearchGateway."""

#     @pytest.fixture(autouse=True)
#     def minimum_privileges(self) -> None:
#         """Provide a default empty minimum_privileges object."""
#         return

#     @pytest.mark.asyncio
#     async def test_async_init(
#         self,
#         hass: HomeAssistant,
#         uninitialized_gateway: ElasticsearchGateway,
#         minimum_privileges: dict,
#         config_entry,
#     ):
#         """Test async_init."""
#         with (
#             mock.patch.object(
#                 uninitialized_gateway,
#                 "_get_cluster_info",
#                 return_value=CLUSTER_INFO_8DOT0_RESPONSE_BODY,
#             ),
#             mock.patch.object(uninitialized_gateway, "test_connection", return_value=True),
#         ):
#             await uninitialized_gateway.async_init(config_entry=config_entry)

#         assert uninitialized_gateway._info is not None
#         assert uninitialized_gateway._capabilities is not None
#         assert uninitialized_gateway._cancel_connection_monitor is None

#         await uninitialized_gateway.stop()

#     @pytest.mark.asyncio
#     async def test_async_init_with_monitor(
#         self,
#         hass: HomeAssistant,
#         uninitialized_gateway: ElasticsearchGateway,
#         minimum_privileges: dict,
#         config_entry,
#     ):
#         """Test async_init."""

#         uninitialized_gateway._use_connection_monitor = True

#         with (
#             mock.patch.object(
#                 uninitialized_gateway,
#                 "_get_cluster_info",
#                 return_value=CLUSTER_INFO_8DOT0_RESPONSE_BODY,
#             ),
#             mock.patch.object(uninitialized_gateway, "test_connection", return_value=True),
#         ):
#             await uninitialized_gateway.async_init(config_entry=config_entry)

#         initialized_gateway = uninitialized_gateway
#         assert initialized_gateway._info is not None
#         assert initialized_gateway._capabilities is not None
#         assert initialized_gateway._cancel_connection_monitor is not None

#         await initialized_gateway.stop()

#     @pytest.mark.asyncio
#     @pytest.mark.parametrize("minimum_privileges", [{}])
#     async def test_async_init_with_insufficient_privileges(
#         self,
#         hass: HomeAssistant,
#         uninitialized_gateway: ElasticsearchGateway,
#         minimum_privileges: dict,
#         config_entry,
#     ):
#         """Test async_init with insufficient privileges."""
#         with (
#             mock.patch.object(uninitialized_gateway, "_has_required_privileges", return_value=False),
#             mock.patch.object(
#                 uninitialized_gateway,
#                 "_get_cluster_info",
#                 return_value=CLUSTER_INFO_8DOT0_RESPONSE_BODY,
#             ),
#             mock.patch.object(uninitialized_gateway, "test_connection", return_value=True),
#             pytest.raises(InsufficientPrivileges),
#         ):
#             await uninitialized_gateway.async_init(config_entry=config_entry)

#         assert uninitialized_gateway._info is not None
#         assert uninitialized_gateway._capabilities is not None
#         assert uninitialized_gateway._cancel_connection_monitor is None

#     @pytest.mark.asyncio
#     async def test_async_init_successful(self, hass: HomeAssistant, config_entry, uninitialized_gateway):
#         """Test async_init when initialization is successful."""
#         uninitialized_gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "7.11"}})
#         uninitialized_gateway.test_connection = AsyncMock(return_value=True)
#         uninitialized_gateway._has_required_privileges = AsyncMock(return_value=True)

#         await uninitialized_gateway.async_init(config_entry=config_entry)

#         initialized_gateway = uninitialized_gateway

#         assert initialized_gateway._info == {"version": {"number": "7.11"}}
#         assert initialized_gateway._capabilities is not None
#         assert initialized_gateway._cancel_connection_monitor is None

#     @pytest.mark.asyncio
#     async def test_async_init_connection_test_failed(
#         self,
#         hass: HomeAssistant,
#         config_entry,
#         uninitialized_gateway,
#     ):
#         """Test async_init when connection test fails."""
#         uninitialized_gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "7.11"}})
#         uninitialized_gateway.test_connection = AsyncMock(return_value=False)

#         with pytest.raises(ConnectionError):
#             await uninitialized_gateway.async_init(config_entry=config_entry)

#         assert uninitialized_gateway._info == {"version": {"number": "7.11"}}
#         # make sure capabilities is an empty dict
#         assert uninitialized_gateway._capabilities == {}
#         assert uninitialized_gateway._cancel_connection_monitor is None

#     @pytest.mark.asyncio
#     async def test_async_init_unsupported_version(self, hass: HomeAssistant, config_entry):
#         """Test async_init when the Elasticsearch version is unsupported."""
#         gateway = Elasticsearch7Gateway(hass=hass, url="http://my_es_host:9200")
#         gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "6.8"}})
#         gateway.test_connection = AsyncMock(return_value=True)

#         with pytest.raises(UnsupportedVersion):
#             await gateway.async_init(config_entry=config_entry)

#         assert gateway._info == {"version": {"number": "6.8"}}
#         assert gateway._capabilities is not None
#         assert not gateway._capabilities[CAPABILITIES.SUPPORTED]
#         assert gateway._cancel_connection_monitor is None

#     @pytest.mark.asyncio
#     async def test_async_init_insufficient_privileges(self, hass: HomeAssistant, config_entry):
#         """Test async_init when there are insufficient privileges."""
#         gateway = Elasticsearch7Gateway(hass=hass, url="http://my_es_host:9200", minimum_privileges="test")
#         gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "7.11"}})
#         gateway.test_connection = AsyncMock(return_value=True)
#         gateway._has_required_privileges = AsyncMock(return_value=False)

#         with pytest.raises(InsufficientPrivileges):
#             await gateway.async_init(config_entry=config_entry)

#         assert gateway._info == {"version": {"number": "7.11"}}
#         assert gateway._capabilities is not None
#         assert gateway._cancel_connection_monitor is None

#     @pytest.mark.asyncio
#     async def test_async_init_ssl_error(self, hass: HomeAssistant, config_entry):
#         """Test async_init when there are insufficient privileges."""

#         gateway = Elasticsearch7Gateway(hass=hass, url="http://my_es_host:9200", minimum_privileges="test")
#         # gateway._get_cluster_info = AsyncMock()

#         # create a mock certificate error
#         # client_exceptions.ClientConnectorCertificateError()
#         certificate_error = client_exceptions.ClientConnectorCertificateError(
#             connection_key="test", certificate_error=MagicMock()
#         )

#         gateway.client.info = AsyncMock(side_effect=SSLError(None, None, certificate_error))

#         with pytest.raises(UntrustedCertificate):
#             await gateway.async_init(config_entry=config_entry)

#     @pytest.mark.asyncio
#     @pytest.mark.parametrize("mock_test_connection", [False])
#     async def test_test_success(
#         self,
#         hass: HomeAssistant,
#         initialized_gateway: ElasticsearchGateway,
#         mock_test_connection,
#     ):
#         """Test the gateway connection test function for success."""

#         async_test_result = asyncio.Future()
#         async_test_result.set_result(True)

#         # assert not await initialized_gateway.test_connection()

#         with (
#             mock.patch.object(initialized_gateway, "_get_cluster_info", return_value=async_test_result),
#         ):
#             assert await initialized_gateway.test_connection()

#     @pytest.mark.parametrize("mock_test_connection", [False])
#     async def test_test_failed(
#         self,
#         hass: HomeAssistant,
#         initialized_gateway: ElasticsearchGateway,
#         mock_test_connection,
#     ):
#         """Test the gateway connection test function for failure."""

#         # assert await initialized_gateway.test_connection()

#         with (
#             mock.patch.object(
#                 initialized_gateway,
#                 "_get_cluster_info",
#                 side_effect=ESIntegrationException(TransportError7(404, "Not Found")),
#             ),
#         ):
#             assert not await initialized_gateway.test_connection()

#     @pytest.mark.parametrize(
#         ("name", "cluster_info"),
#         [
#             ("7DOT11_CAPABILITIES", CLUSTER_INFO_7DOT11_RESPONSE_BODY),
#             ("7DOT17_CAPABILITIES", CLUSTER_INFO_7DOT17_RESPONSE_BODY),
#             ("8DOT0_CAPABILITIES", CLUSTER_INFO_8DOT0_RESPONSE_BODY),
#             ("8DOT8_CAPABILITIES", CLUSTER_INFO_8DOT8_RESPONSE_BODY),
#             ("8DOT11_CAPABILITIES", CLUSTER_INFO_8DOT11_RESPONSE_BODY),
#             ("SERVERLESS_CAPABILITIES", CLUSTER_INFO_SERVERLESS_RESPONSE_BODY),
#         ],
#     )
#     async def test_capabilities(
#         self,
#         hass: HomeAssistant,
#         uninitialized_gateway: ElasticsearchGateway,
#         name: str,
#         cluster_info: dict,
#         snapshot: SnapshotAssertion,
#         config_entry,
#     ):
#         """Test capabilities."""
#         with (
#             mock.patch.object(uninitialized_gateway, "_get_cluster_info", return_value=cluster_info),
#             mock.patch.object(uninitialized_gateway, "test_connection", return_value=True),
#         ):
#             await uninitialized_gateway.async_init(config_entry=config_entry)

#         assert uninitialized_gateway._capabilities is not None

#         assert {
#             "name": name,
#             "cluster info": cluster_info,
#             "capabilities": uninitialized_gateway._capabilities,
#         } == snapshot

#     async def test_has_capability(self, hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
#         """Test has_capability."""
#         uninitialized_gateway._capabilities = {
#             "supported": True,
#             "timeseries_datastream": True,
#             "ignore_missing_component_templates": False,
#             "datastream_lifecycle_management": True,
#             "max_primary_shard_size": False,
#         }

#         assert uninitialized_gateway.has_capability("supported") is True
#         assert uninitialized_gateway.has_capability("timeseries_datastream") is True
#         assert uninitialized_gateway.has_capability("ignore_missing_component_templates") is False
#         assert uninitialized_gateway.has_capability("datastream_lifecycle_management") is True
#         assert uninitialized_gateway.has_capability("max_primary_shard_size") is False
#         assert uninitialized_gateway.has_capability("invalid_capability") is False

#     async def test_client(self, hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
#         """Test Getter for client."""
#         uninitialized_gateway._client = mock.Mock(spec=AsyncElasticsearch7)
#         assert uninitialized_gateway.client == uninitialized_gateway._client

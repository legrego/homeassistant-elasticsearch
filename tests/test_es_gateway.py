"""Tests for the Elasticsearch Gateway."""
# noqa: F401 # pylint: disable=redefined-outer-name

import os
import ssl
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import elastic_transport
import elasticsearch8
import elasticsearch8.helpers
import pytest
from aiohttp import client_exceptions
from custom_components.elasticsearch.const import ES_CHECK_PERMISSIONS_DATASTREAM
from custom_components.elasticsearch.datastreams.index_template import index_template_definition
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    CannotConnect,
    InsufficientPrivileges,
    ServerError,
    UnsupportedVersion,
    UntrustedCertificate,
)
from custom_components.elasticsearch.es_gateway import (
    ElasticsearchGateway,
)
from custom_components.elasticsearch.es_gateway_8 import Elasticsearch8Gateway, Gateway8Settings
from elastic_transport import ApiResponseMeta, BaseNode, ObjectApiResponse
from elasticsearch8._async.client import AsyncElasticsearch
from syrupy.assertion import SnapshotAssertion

from tests import const
from tests.const import (
    CLUSTER_INFO_8DOT0_RESPONSE_BODY,
    CLUSTER_INFO_8DOT14_RESPONSE_BODY,
    CLUSTER_INFO_SERVERLESS_RESPONSE_BODY,
)


def self_signed_tls_error():
    """Return a self-signed certificate error."""
    connection_key = MagicMock()
    connection_key.host = "mock_es_integration"
    connection_key.port = 9200
    connection_key.is_ssl = True

    certificate_error = ssl.SSLCertVerificationError()
    certificate_error.verify_code = 19
    certificate_error.verify_message = "'self-signed certificate in certificate chain'"
    certificate_error.library = "SSL"
    certificate_error.reason = "CERTIFICATE_VERIFY_FAILED"
    certificate_error.strerror = "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain (_ssl.c:1000)"
    certificate_error.errno = 1

    return client_exceptions.ClientConnectorCertificateError(
        connection_key=connection_key, certificate_error=certificate_error
    )

def mock_api_response_meta(status_code=200):
    """Return a mock API response meta."""
    return ApiResponseMeta(
        status=status_code, headers=MagicMock(), http_version="1.1", duration=0.0, node=MagicMock()
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
def gateway_settings() -> Gateway8Settings:
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
async def gateway_mock_shared(gateway_settings) -> Elasticsearch8Gateway:
    """Return a mock Elasticsearch client."""
    gateway_settings.to_client = MagicMock(return_value=MagicMock(AsyncElasticsearch))

    gateway = Elasticsearch8Gateway(gateway_settings=gateway_settings)

    gateway._client.options = MagicMock(return_value=gateway._client)

    gateway._client.security = MagicMock()
    gateway._client.security.has_privileges = mock_es_response({"has_all_requested": True})

    gateway._client.indices = MagicMock()
    gateway._client.indices.get_index_template = mock_es_response(
        {
            "index_templates": [
                {
                    "name": "datastream_metrics",
                    "index_template": {"version": index_template_definition.get("version", 0)},
                }
            ]
        }
    )
    gateway._client.indices.put_index_template = mock_es_response({})
    gateway._client.indices.get_data_stream = mock_es_response(
        {
            "data_streams": [
                {
                    "name": "metrics-homeassistant.sensor-default",
                },
                {
                    "name": "metrics-homeassistant.counter-default",
                },
            ]
        }
    )
    gateway._client.indices.rollover = mock_es_response(
        {
            "acknowledged": True,
            "shards_acknowledged": True,
            "old_index": ".ds-metrics-homeassistant.domain-default-2024.12.19-000001",
            "new_index": ".ds-metrics-homeassistant.domain-default-2025.01.10-000002",
            "rolled_over": True,
            "dry_run": False,
            "lazy": False,
            "conditions": {},
        }
    )

    return gateway


@pytest.fixture
async def gateway_mock_stateful(gateway_mock_shared: Elasticsearch8Gateway) -> Elasticsearch8Gateway:
    """Return a mock Elasticsearch client."""

    gateway_mock_shared._client.info = mock_es_response(CLUSTER_INFO_8DOT14_RESPONSE_BODY)
    gateway_mock_shared._client.xpack = MagicMock()
    gateway_mock_shared._client.xpack.usage = mock_es_response(
        {"security": {"available": True, "enabled": True}}
    )
    return gateway_mock_shared


@pytest.fixture
async def gateway_mock_serverless(gateway_mock_shared: Elasticsearch8Gateway) -> Elasticsearch8Gateway:
    """Return a mock Elasticsearch client."""

    gateway_mock_shared._client.info = mock_es_response(CLUSTER_INFO_SERVERLESS_RESPONSE_BODY)
    gateway_mock_shared._client.xpack = MagicMock()

    gateway_mock_shared._client.xpack.usage = mock_es_exception(
        elasticsearch8.ApiError, message="api_not_available_exception"
    )

    return gateway_mock_shared


class Test_Initialization:
    """Initialization tests for the Elasticsearch Gateway."""

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

    async def test_async_init(self, gateway_mock_stateful) -> None:
        """Test the async initialization with proper permissions on a supported version."""

        assert await gateway_mock_stateful.async_init() is None

    async def test_async_init_unsupported_version(self, gateway_mock_stateful) -> None:
        """Test the async_init method when the target cluster is running an unsupported version."""

        gateway_mock_stateful._client.info = mock_es_response(CLUSTER_INFO_8DOT0_RESPONSE_BODY)

        with pytest.raises(UnsupportedVersion):
            assert await gateway_mock_stateful.async_init() is None

    async def test_async_init_unauthenticated(self, gateway_mock_stateful) -> None:
        """Test the async_init method with an unauthenticated session."""

        gateway_mock_stateful._client.info = mock_es_exception(elasticsearch8.AuthenticationException)

        with pytest.raises(AuthenticationRequired):
            await gateway_mock_stateful.async_init()

    @pytest.mark.asyncio
    async def test_async_init_ssl_error(self, gateway_mock_stateful):
        """Test async_init when there is a TLS Certificate issue."""

        gateway_mock_stateful._client.info = mock_es_exception(elastic_transport.TlsError)

        with pytest.raises(UntrustedCertificate):
            await gateway_mock_stateful.async_init()

    async def test_async_init_unauthorized(self, gateway_mock_stateful) -> None:
        """Test the async_init method unauthorized."""

        gateway_mock_stateful._client.info = mock_es_exception(elasticsearch8.AuthorizationException)

        with pytest.raises(InsufficientPrivileges):
            assert await gateway_mock_stateful.async_init() is None

    async def test_async_init_unreachable(self, gateway_mock_stateful) -> None:
        """Test the async_init method with unreachable Elasticsearch."""

        gateway_mock_stateful._client.info = mock_es_exception(elasticsearch8.ConnectionTimeout)

        with pytest.raises(CannotConnect):
            assert await gateway_mock_stateful.async_init() is None


class Test_Public_Functions:
    """Public function tests for the Elasticsearch Gateway."""

    async def test_ping(self, gateway_mock_stateful) -> None:
        """Test the ping method."""
        assert await gateway_mock_stateful.ping() is True

    async def test_ping_fail(self, gateway_mock_stateful) -> None:
        """Test the ping method."""
        gateway_mock_stateful._client.info = mock_es_exception(elasticsearch8.AuthenticationException)
        with pytest.raises(AuthenticationRequired):
            await gateway_mock_stateful.ping()

        gateway_mock_stateful._client.info = mock_es_exception(elasticsearch8.AuthorizationException)
        with pytest.raises(AuthenticationRequired):
            await gateway_mock_stateful.ping()

        gateway_mock_stateful._client.info = mock_es_exception(elasticsearch8.ConnectionTimeout)
        assert await gateway_mock_stateful.ping() is False

    async def test_has_security_stateful_success(self, gateway_mock_stateful):
        """Test the has_security method."""

        assert await gateway_mock_stateful.has_security() is True

        gateway_mock_stateful._client.info.assert_called_once()
        gateway_mock_stateful._client.xpack.usage.assert_called_once()

    async def test_has_security_stateful_missing(self, gateway_mock_stateful) -> None:
        """Test the has_security method."""

        gateway_mock_stateful._client.xpack.usage = mock_es_response(
            {"other_feature": {"available": False, "enabled": False}}
        )

        assert await gateway_mock_stateful.has_security() is False

        gateway_mock_stateful._client.info.assert_called_once()
        gateway_mock_stateful._client.xpack.usage.assert_called_once()

    async def test_has_security_stateful_failure(self, gateway_mock_stateful) -> None:
        """Test the has_security method."""

        gateway_mock_stateful._client.xpack.usage = mock_es_response(
            {"security": {"available": False, "enabled": False}}
        )

        assert await gateway_mock_stateful.has_security() is False

        gateway_mock_stateful._client.info.assert_called_once()
        gateway_mock_stateful._client.xpack.usage.assert_called_once()

    async def test_has_security_serverless(self, gateway_mock_serverless):
        """Test the has_security method."""

        assert await gateway_mock_serverless.has_security() is True

        gateway_mock_serverless._client.info.assert_called_once()
        gateway_mock_serverless._client.xpack.usage.assert_not_called()

    async def test_get_datastream(self, gateway_mock_stateful):
        """Test the get_datastream method."""

        await gateway_mock_stateful.get_datastream("metrics-homeassistant.*")

        gateway_mock_stateful._client.indices.get_data_stream.assert_called_once_with(
            name="metrics-homeassistant.*"
        )

    async def test_rollover_datastream(self, gateway_mock_stateful):
        """Test the get_datastream method."""

        await gateway_mock_stateful.rollover_datastream("metrics-homeassistant.sensor-default")

        gateway_mock_stateful._client.indices.rollover.assert_called_once_with(
            alias="metrics-homeassistant.sensor-default"
        )

    async def test_has_privileges(self, gateway_mock_stateful):
        """Test the has_privileges method when the underlying client returns that we do have privileges."""
        privileges = ES_CHECK_PERMISSIONS_DATASTREAM

        assert await gateway_mock_stateful.has_privileges(privileges) is True

        gateway_mock_stateful._client.security.has_privileges.assert_called_once_with(**privileges)

    async def test_has_privileges_false(self, gateway_mock_stateful):
        """Test the has_privileges method when the underlying client returns that we do not have privileges."""
        privileges = ES_CHECK_PERMISSIONS_DATASTREAM

        gateway_mock_stateful._client.security.has_privileges = mock_es_response({"has_all_requested": False})

        assert await gateway_mock_stateful.has_privileges(privileges) is False

        gateway_mock_stateful._client.security.has_privileges.assert_called_once_with(**privileges)

    async def test_get_index_template(self, gateway_mock_stateful):
        """Test the get_index_template method."""

        await gateway_mock_stateful.get_index_template("datastream_metrics")

        gateway_mock_stateful._client.indices.get_index_template.assert_called_once_with(
            name="datastream_metrics"
        )

    async def test_get_index_template_ignore_404(self, gateway_mock_stateful):
        """Test the get_index_template method when the template is missing."""

        gateway_mock_stateful._client.indices.get_index_template = mock_es_response({"index_templates": []})

        assert await gateway_mock_stateful.get_index_template("datastream_metrics", ignore=[404]) == {
            "index_templates": []
        }

        gateway_mock_stateful._client.indices.get_index_template.assert_called_with(name="datastream_metrics")
        gateway_mock_stateful._client.options.assert_called_with(ignore_status=[404])

    async def test_put_index_template(self, gateway_mock_stateful):
        """Test the put_index_template method."""

        await gateway_mock_stateful.put_index_template("datastream_metrics", index_template_definition)

        gateway_mock_stateful._client.indices.put_index_template.assert_called_once_with(
            name="datastream_metrics", **index_template_definition
        )

    class Test_Check_Connection:
        @pytest.fixture(name="gateway")
        async def gateway_fixture(self, gateway_settings):
            """Return a gateway instance."""
            gateway = Elasticsearch8Gateway(gateway_settings=gateway_settings)

            gateway._logger.debug = MagicMock()
            gateway._logger.error = MagicMock()
            gateway._logger.info = MagicMock()

            try:
                yield gateway
            finally:
                await gateway.stop()

        async def test_check_connection_first_time_success(self, gateway) -> None:
            """Test check_connection method when connecting for the first time successfully."""
            gateway.ping = AsyncMock(return_value=True)

            result = await gateway.check_connection()

            assert result is True
            gateway._logger.info.assert_called_once_with("Connection to Elasticsearch is established.")
            gateway._logger.error.assert_not_called()

        async def test_check_connection_first_time_failure(self, gateway) -> None:
            """Test check_connection method when connecting for the first time fails."""
            gateway.ping = AsyncMock(return_value=False)

            result = await gateway.check_connection()

            assert result is False
            gateway._logger.error.assert_called_once_with("Failed to establish connection to Elasticsearch.")
            gateway._logger.info.assert_not_called()

        async def test_check_connection_maintained(self, gateway) -> None:
            """Test check_connection method when connection is maintained."""
            gateway._previous_ping = True
            gateway.ping = AsyncMock(return_value=True)

            result = await gateway.check_connection()

            assert result is True
            gateway._logger.debug.assert_called_once_with("Connection to Elasticsearch is still available.")

        async def test_check_connection_lost(self, gateway) -> None:
            """Test check_connection method when connection is lost."""
            gateway._previous_ping = True
            gateway.ping = AsyncMock(return_value=False)

            result = await gateway.check_connection()

            assert result is False
            gateway._logger.error.assert_called_once_with("Connection to Elasticsearch has been lost.")
            gateway._logger.debug.assert_not_called()

        async def test_check_connection_down(self, gateway) -> None:
            """Test check_connection method when connection is still down."""
            gateway._previous_ping = False
            gateway.ping = AsyncMock(return_value=False)

            result = await gateway.check_connection()

            assert result is False
            gateway._logger.debug.assert_called_once_with("Connection to Elasticsearch is still down.")

        async def test_check_connection_reestablished(self, gateway) -> None:
            """Test check_connection method when connection is reestablished."""
            gateway._previous_ping = False
            gateway.ping = AsyncMock(return_value=True)

            result = await gateway.check_connection()

            assert result is True
            gateway._logger.info.assert_called_once_with(
                "Connection to Elasticsearch has been reestablished."
            )


class Test_Exception_Conversion:
    """Test the conversion of Elasticsearch exceptions to custom exceptions."""

    @pytest.mark.parametrize(
        ("exception", "expected_exception", "message"),
        [
            (
                elasticsearch8.TransportError(message="Test Case"),
                CannotConnect,
                "Unknown transport error connecting to Elasticsearch",
            ),
            (
                elasticsearch8.AuthenticationException(message="Test Case", meta=MagicMock(), body=None),
                AuthenticationRequired,
                "Authentication error connecting to Elasticsearch",
            ),
            (
                elasticsearch8.AuthorizationException(message="Test Case", meta=MagicMock(), body=None),
                InsufficientPrivileges,
                "Authorization error connecting to Elasticsearch",
            ),
            (
                elasticsearch8.ConnectionTimeout(message="Test Case"),
                CannotConnect,
                "Connection timeout connecting to Elasticsearch",
            ),
            (
                elasticsearch8.SSLError(message="Test Case"),
                UntrustedCertificate,
                "Could not complete TLS Handshake",
            ),
            (
                elasticsearch8.ConnectionError(message="Test Case"),
                CannotConnect,
                "Error connecting to Elasticsearch",
            ),
            (
                elasticsearch8.ApiError(
                    message="Test Case",
                    meta=mock_api_response_meta(status_code=None),  # type: ignore [arg-type]
                    body=None,
                ),
                ServerError,
                "Unknown API Error in request to Elasticsearch",
            ),
            (
                elasticsearch8.ApiError(
                    message="Test Case", meta=mock_api_response_meta(status_code=400), body=None
                ),
                ServerError,
                "Error in request to Elasticsearch",
            ),
            (Exception(), Exception, ""),
        ],
        ids=[
            "TransportError to CannotConnect",
            "AuthenticationException to AuthenticationRequired",
            "AuthorizationException to InsufficientPrivileges",
            "ConnectionTimeout to CannotConnect",
            "SSLError to UntrustedCertificate",
            "ConnectionError to CannotConnect",
            "ApiError to CannotConnect",
            "ApiError(404) to ServerError",
            "Exception to Exception",
        ],
    )
    async def test_error_conversion_bulk_index_error(
        self, gateway_mock_shared, exception, expected_exception, message
    ):
        """Test the error converter handling of a bulk index error."""
        with pytest.raises(expected_exception, match=message), gateway_mock_shared._error_converter():
            raise exception

class Test_Errors_e2e:
    """Test the error handling of aiohttp errors through the ES Client and Gateway."""

    @pytest.fixture
    async def gateway(self, gateway_settings, es_mock_builder):
        """Return a gateway instance."""

        es_mock_builder.as_elasticsearch_8_17().with_correct_permissions()
        gateway = Elasticsearch8Gateway(gateway_settings=gateway_settings)
        es_mock_builder.reset()

        try:
            yield gateway
        finally:
            await gateway.stop()

    @pytest.mark.parametrize(
        ("status_code", "expected_exception"),
        [
            (404, CannotConnect),
            (401, AuthenticationRequired),
            (403, InsufficientPrivileges),
            (500, CannotConnect),
            (400, CannotConnect),
            (502, CannotConnect),
            (503, CannotConnect),
        ],
        ids=[
            "404 to CannotConnect",
            "401 to AuthenticationRequired",
            "403 to InsufficientPrivileges",
            "500 to CannotConnect",
            "400 to CannotConnect",
            "502 to CannotConnect",
            "503 to CannotConnect",
        ],
    )
    async def test_http_error_codes(
        self,
        gateway: ElasticsearchGateway,
        es_mock_builder,
        status_code: int,
        expected_exception: Any,
    ) -> None:
        """Test the error converter."""
        es_mock_builder.with_server_error(status=status_code)

        with pytest.raises(expected_exception):
            await gateway.info()

    @pytest.mark.parametrize(
        ("aiohttp_exception", "expected_exception"),
        [
            (client_exceptions.ServerConnectionError(), CannotConnect),
            # child exceptions of ServerConnectionError
            (
                client_exceptions.ServerFingerprintMismatch(
                    expected=b"expected", got=b"actual", host="host", port=9200
                ),
                CannotConnect,
            ),
            (client_exceptions.ServerDisconnectedError(), CannotConnect),
            (client_exceptions.ServerTimeoutError(), CannotConnect),
            (client_exceptions.ClientError(), CannotConnect),
            # child exceptions of ClientError
            (
                client_exceptions.ClientResponseError(request_info=MagicMock(), history=MagicMock()),
                CannotConnect,
            ),
            (client_exceptions.ClientPayloadError(), CannotConnect),
            (client_exceptions.ClientConnectionError(), CannotConnect),
            (self_signed_tls_error(), UntrustedCertificate),
        ],
        ids=[
            "ServerConnectionError to CannotConnect",
            "ServerFingerprintMismatch to CannotConnect",
            "ServerDisconnectedError to CannotConnect",
            "ServerTimeoutError to CannotConnect",
            "ClientError to CannotConnect",
            "ClientResponseError to CannotConnect",
            "ClientPayloadError to CannotConnect",
            "ClientConnectionError to CannotConnect",
            "SSLCertVerificationError to UntrustedCertificate",
        ],
    )
    async def test_aiohttp_web_exceptions(
        self, aiohttp_exception, expected_exception, gateway, es_mock_builder
    ) -> None:
        """Test the error converter."""

        es_mock_builder.with_server_error(exc=aiohttp_exception)

        with pytest.raises(expected_exception):
            await gateway.info()

        await gateway.stop()

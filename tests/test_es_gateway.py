"""Tests for the Elasticsearch Gateway."""
# noqa: F401 # pylint: disable=redefined-outer-name

import os
import ssl
import threading
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import elastic_transport
import elasticsearch
import elasticsearch.helpers
import pytest
from aiohttp import client_exceptions
from custom_components.elasticsearch.const import ES_CHECK_PERMISSIONS_DATASTREAM
from custom_components.elasticsearch.datastreams.index_template import index_template_definition
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    CannotConnect,
    InsufficientPrivileges,
    InvalidCACertificate,
    ServerError,
    UnsupportedServer,
    UnsupportedVersion,
    UntrustedCertificate,
)
from custom_components.elasticsearch.es_gateway import (
    ElasticsearchGateway,
)
from custom_components.elasticsearch.es_gateway_8 import (
    CompatibilityTransport,
    Elasticsearch8Gateway,
    Gateway8Settings,
)
from elastic_transport import ApiResponseMeta, AsyncTransport, BaseNode, ObjectApiResponse
from elastic_transport.client_utils import DEFAULT
from elasticsearch import AsyncElasticsearch
from homeassistant.util.ssl import client_context

from tests import const as testconst

CURRENT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
CUSTOM_CA_PATH = f"{CURRENT_DIRECTORY}/certs/http_ca.crt"


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
    if issubclass(exception, elasticsearch.TransportError):
        return AsyncMock(side_effect=exception(message=message))

    # if it's an APIerror we provide meta, body, message
    if issubclass(exception, elasticsearch.ApiError):
        return AsyncMock(side_effect=exception(meta=MagicMock, body=None, message=message))


def mock_es_response(body):
    """Return an AsyncMock that mocks an Elasticsearch API response."""
    return AsyncMock(return_value=ObjectApiResponse(meta={}, body=body))


@pytest.fixture
def gateway_settings() -> Gateway8Settings:
    """Return a Gateway8Settings instance."""
    return Gateway8Settings(
        url=testconst.CONFIG_ENTRY_DATA_URL,
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
    gateway._client = gateway_settings.to_client()

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
async def gateway_mock_stateful(
    gateway_mock_shared: Elasticsearch8Gateway, mock_logger
) -> Elasticsearch8Gateway:
    """Return a mock Elasticsearch client for a Stateful ES Cluster."""

    gateway_mock_shared.client.info = mock_es_response(testconst.CLUSTER_INFO_8DOT14_RESPONSE_BODY)
    gateway_mock_shared.client.xpack = MagicMock()
    gateway_mock_shared.client.xpack.usage = mock_es_response(
        {"security": {"available": True, "enabled": True}}
    )

    gateway_mock_shared._logger = mock_logger

    return gateway_mock_shared


@pytest.fixture
async def gateway_mock_serverless(gateway_mock_shared: Elasticsearch8Gateway) -> Elasticsearch8Gateway:
    """Return a mock Elasticsearch client for serverless ES."""

    gateway_mock_shared.client.info = mock_es_response(testconst.CLUSTER_INFO_SERVERLESS_RESPONSE_BODY)
    gateway_mock_shared.client.xpack = MagicMock()

    gateway_mock_shared.client.xpack.usage = mock_es_exception(
        elasticsearch.ApiError, message="api_not_available_exception"
    )

    return gateway_mock_shared


class Test_Initialization:
    """Initialization tests for the Elasticsearch Gateway."""

    async def test_init_basic_auth(self) -> None:
        """Test initializing a gateway with basic authentication."""
        client = Gateway8Settings(
            url=testconst.CONFIG_ENTRY_DATA_URL, username="username", password="password"
        ).to_client()

        assert client._headers["Authorization"].startswith("Basic")

    async def test_init_api_key_auth(self) -> None:
        """Test initializing a gateway with API Key authentication."""

        # API Key Authentication
        client = Gateway8Settings(
            url=testconst.CONFIG_ENTRY_DATA_URL,
            api_key="api",
        ).to_client()

        assert client._headers["Authorization"].startswith("ApiKey")

    async def test_init_no_auth(self) -> None:
        """Test initializing a gateway with no authentication."""
        client = Gateway8Settings(
            url=testconst.CONFIG_ENTRY_DATA_URL_INSECURE,
        ).to_client()

        assert client._headers.get("Authorization", None) is None

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

        client = Gateway8Settings(
            url=testconst.CONFIG_ENTRY_DATA_URL,
            verify_certs=verify_certs,
            verify_hostname=verify_hostname,
        ).to_client()

        node: BaseNode = client._transport.node_pool.get()
        ssl_context = node._ssl_context  # type: ignore[attr-defined]

        assert ssl_context.check_hostname == expected_verify_hostname
        assert ssl_context.verify_mode == expected_verify_mode

    async def test_init_tls_custom_ca(self) -> None:
        """Test initializing a gateway with TLS and custom ca cert."""

        # cert is located in "certs/http_ca.crt" relative to this file, get the absolute path
        current_directory = os.path.dirname(os.path.abspath(__file__))

        client = Gateway8Settings(
            url=testconst.CONFIG_ENTRY_DATA_URL,
            verify_certs=True,
            verify_hostname=True,
            ca_certs=f"{current_directory}/certs/http_ca.crt",
        ).to_client()

        node: BaseNode = client._transport.node_pool.get()
        ssl_context = node._ssl_context  # type: ignore[attr-defined]

        assert any(
            cert["serialNumber"] == "25813FA4F725F5566FCF014C0B8B0973E710DF90"
            for cert in ssl_context.get_ca_certs()
        )

    @pytest.mark.parametrize(
        "settings",
        [
            {"verify_certs": False},
            {"verify_certs": True, "verify_hostname": False},
            {"ca_certs": CUSTOM_CA_PATH},
        ],
        ids=["No certificate verification", "No hostname verification", "Custom CA"],
    )
    async def test_shared_ssl_context_is_not_modified(self, settings) -> None:
        """Test that TLS settings stay out of the context shared across Home Assistant."""

        shared_context = client_context()
        shared_ca_certs = shared_context.get_ca_certs()

        Gateway8Settings(url=testconst.CONFIG_ENTRY_DATA_URL, **settings).to_client()

        assert shared_context.verify_mode == ssl.CERT_REQUIRED
        assert shared_context.check_hostname is True
        assert shared_context.get_ca_certs() == shared_ca_certs

    async def test_ssl_context_is_not_shared_between_clients(self) -> None:
        """Test that each client gets its own TLS context."""

        settings = Gateway8Settings(url=testconst.CONFIG_ENTRY_DATA_URL)

        first: BaseNode = settings.to_client()._transport.node_pool.get()
        second: BaseNode = settings.to_client()._transport.node_pool.get()

        assert first._ssl_context is not second._ssl_context  # type: ignore[attr-defined]

    @pytest.mark.parametrize(
        "ca_certs",
        [f"{CURRENT_DIRECTORY}/certs/missing.crt", __file__, CURRENT_DIRECTORY],
        ids=["Missing file", "Not a certificate", "Directory"],
    )
    async def test_invalid_ca_certs(self, ca_certs) -> None:
        """Test that a CA file that cannot be loaded raises our own error."""

        settings = Gateway8Settings(url=testconst.CONFIG_ENTRY_DATA_URL, ca_certs=ca_certs)

        with pytest.raises(InvalidCACertificate):
            settings.to_client()

    async def test_client_is_built_off_the_event_loop(self, gateway_settings) -> None:
        """Test that the blocking client construction runs on a worker thread."""

        client = MagicMock(AsyncElasticsearch)
        threads = []

        def to_client() -> MagicMock:
            threads.append(threading.get_ident())
            return client

        gateway_settings.to_client = to_client
        gateway = Elasticsearch8Gateway(gateway_settings=gateway_settings)

        assert threads == []

        with patch.object(ElasticsearchGateway, "async_init", AsyncMock()):
            await gateway.async_init()

        assert threads != [threading.get_ident()]
        assert len(threads) == 1
        assert gateway.client is client

    async def test_stop_before_init(self, gateway_settings) -> None:
        """Test that a gateway which never connected can still be stopped."""

        await Elasticsearch8Gateway(gateway_settings=gateway_settings).stop()

    async def test_cluster_details_before_init(self, gateway_settings) -> None:
        """Test that nothing is known about the cluster before the gateway connects."""

        gateway = Elasticsearch8Gateway(gateway_settings=gateway_settings)

        assert gateway.cluster_version is None
        assert gateway.build_flavor is None
        assert gateway.connected is None

    async def test_async_init(self, gateway_mock_stateful) -> None:
        """Test the async initialization with proper permissions on a supported version."""

        assert await gateway_mock_stateful.async_init() is None

        assert (
            gateway_mock_stateful.cluster_uuid == testconst.CLUSTER_INFO_8DOT14_RESPONSE_BODY["cluster_uuid"]
        )
        assert gateway_mock_stateful.cluster_version == "8.14.0"
        assert gateway_mock_stateful.build_flavor == "default"
        assert gateway_mock_stateful.connected is True

    async def test_async_init_unformed_cluster(self, gateway_mock_stateful) -> None:
        """Test that the placeholder UUID of an unformed cluster is not treated as its identity."""

        gateway_mock_stateful._client.info = mock_es_response(
            {**testconst.CLUSTER_INFO_8DOT14_RESPONSE_BODY, "cluster_uuid": "_na_"}
        )

        await gateway_mock_stateful.async_init()

        assert gateway_mock_stateful.cluster_uuid is None

    async def test_async_init_then_stop(self, es_mock_builder) -> None:
        """Test that the UUID of the cluster is returned to the caller."""

        es_mock_builder.as_elasticsearch_8_17().with_correct_permissions()

        cluster_uuid = await Elasticsearch8Gateway.async_init_then_stop(
            url=testconst.CONFIG_ENTRY_DATA_URL, verify_certs=False
        )

        assert cluster_uuid is not None

    async def test_async_init_unsupported_version(self, gateway_mock_stateful) -> None:
        """Test the async_init method when the target cluster is running an unsupported version."""

        gateway_mock_stateful._client.info = mock_es_response(testconst.CLUSTER_INFO_8DOT0_RESPONSE_BODY)

        with pytest.raises(UnsupportedVersion) as err:
            assert await gateway_mock_stateful.async_init() is None

        assert err.value.version == "8.0.0"

    @pytest.mark.parametrize(
        "cluster_info",
        [
            {"version": {"number": "8.9.0"}},  # VictoriaLogs ingestion endpoint
            {},
            {"version": None},
            {"version": []},
            {"version": {"number": "8.14.0", "build_flavor": None}},
            {"version": {"number": "8.14.0", "build_flavor": ""}},
            {"version": {"number": "8.14.0", "build_flavor": " "}},
            {"version": {"number": "8.14.0", "build_flavor": []}},
            {"version": {"build_flavor": "default"}},
            {"version": {"number": None, "build_flavor": "default"}},
            {"version": {"number": "8", "build_flavor": "default"}},
            {"version": {"number": "8.invalid.0", "build_flavor": "default"}},
            {"version": {"build_flavor": "serverless"}},
        ],
    )
    async def test_async_init_incompatible_metadata(self, gateway_mock_stateful, cluster_info):
        """Reject ingestion-only and malformed endpoints before checking security."""
        gateway_mock_stateful._client.info = mock_es_response(cluster_info)

        with pytest.raises(UnsupportedServer):
            await gateway_mock_stateful.async_init()

        gateway_mock_stateful._client.xpack.usage.assert_not_called()
        gateway_mock_stateful._client.security.has_privileges.assert_not_called()

    async def test_unfamiliar_build_flavor_uses_version_check(self, gateway_mock_stateful):
        """Accept new build flavors while retaining the minimum supported version."""
        gateway_mock_stateful._client.info = mock_es_response(
            {"version": {"number": "8.14.0", "build_flavor": "future"}}
        )
        await gateway_mock_stateful.async_init()

        # Version validation reuses the first response; security detection fetches its own.
        assert gateway_mock_stateful._client.info.await_count == 2
        gateway_mock_stateful._client.info = mock_es_response(
            {"version": {"number": "8.0.0", "build_flavor": "future"}}
        )
        with pytest.raises(UnsupportedVersion):
            await gateway_mock_stateful.async_init()

    async def test_async_init_unauthenticated(self, gateway_mock_stateful) -> None:
        """Test the async_init method with an unauthenticated session."""

        gateway_mock_stateful._client.info = mock_es_exception(elasticsearch.AuthenticationException)

        with pytest.raises(AuthenticationRequired):
            await gateway_mock_stateful.async_init()

    async def test_async_init_ssl_error(self, gateway_mock_stateful):
        """Test async_init when there is a TLS Certificate issue."""

        gateway_mock_stateful._client.info = mock_es_exception(elastic_transport.TlsError)

        with pytest.raises(UntrustedCertificate):
            await gateway_mock_stateful.async_init()

    async def test_async_init_unauthorized(self, gateway_mock_stateful) -> None:
        """Test the async_init method unauthorized."""

        gateway_mock_stateful._client.info = mock_es_exception(elasticsearch.AuthorizationException)

        with pytest.raises(InsufficientPrivileges):
            assert await gateway_mock_stateful.async_init() is None

    async def test_async_init_unreachable(self, gateway_mock_stateful) -> None:
        """Test the async_init method with unreachable Elasticsearch."""

        gateway_mock_stateful._client.info = mock_es_exception(elasticsearch.ConnectionTimeout)

        with pytest.raises(CannotConnect):
            assert await gateway_mock_stateful.async_init() is None


class Test_Compatibility:
    """Tests for the REST API compatibility version the client asks for."""

    @pytest.mark.parametrize(
        ("headers", "expected"),
        [
            (
                {"accept": "application/vnd.elasticsearch+json; compatible-with=9"},
                {"accept": "application/vnd.elasticsearch+json; compatible-with=8"},
            ),
            (
                {
                    "accept": "application/vnd.elasticsearch+json; compatible-with=9",
                    "content-type": "application/vnd.elasticsearch+x-ndjson; compatible-with=9",
                    "authorization": "ApiKey compatible-with=9",
                },
                {
                    "accept": "application/vnd.elasticsearch+json; compatible-with=8",
                    "content-type": "application/vnd.elasticsearch+x-ndjson; compatible-with=8",
                    "authorization": "ApiKey compatible-with=9",
                },
            ),
            (
                {"Accept": "application/json"},
                {"accept": "application/json"},
            ),
        ],
        ids=["Accept", "Accept, Content-Type and other headers", "No compatibility version"],
    )
    async def test_rewrites_compatibility_version(self, headers, expected) -> None:
        """Test that only the compatibility version in Accept and Content-Type changes."""

        transport = Gateway8Settings(url=testconst.CONFIG_ENTRY_DATA_URL).to_client().transport
        assert isinstance(transport, CompatibilityTransport)

        with patch.object(AsyncTransport, "perform_request", AsyncMock()) as perform_request:
            await transport.perform_request("GET", "/", headers=headers, request_timeout=5)

        sent = perform_request.call_args.kwargs
        assert {name.lower(): value for name, value in sent["headers"].items()} == expected
        assert sent["request_timeout"] == 5

    async def test_no_headers(self) -> None:
        """Test that a request without headers is passed through unchanged."""

        transport = Gateway8Settings(url=testconst.CONFIG_ENTRY_DATA_URL).to_client().transport

        with patch.object(AsyncTransport, "perform_request", AsyncMock()) as perform_request:
            await transport.perform_request("GET", "/")

        assert perform_request.call_args.kwargs["headers"] is DEFAULT

    async def test_requests_ask_for_compatibility_with_8(self, gateway_settings, es_mock_builder) -> None:
        """Test that every request sent by the client asks for compatibility with version 8."""

        es_mock_builder.as_elasticsearch_8_17().respond_to_bulk()
        gateway = Elasticsearch8Gateway(gateway_settings=gateway_settings)
        gateway._client = gateway_settings.to_client()

        async def actions():
            yield {"_op_type": "create", "_index": "metrics-homeassistant.sensor-default", "a": 1}

        try:
            await gateway.info()
            await gateway.bulk(actions())
        finally:
            await gateway.stop()

        calls = es_mock_builder.get_calls(include_headers=True)
        assert [method for method, _, _, _ in calls] == ["GET", "PUT"]

        for _, _, _, headers in calls:
            headers = {name.lower(): value for name, value in headers.items()}
            assert headers["accept"].endswith("compatible-with=8")

        assert calls[1][3]["content-type"] == "application/vnd.elasticsearch+x-ndjson; compatible-with=8"


class Test_Public_Functions:
    """Public function tests for the Elasticsearch Gateway."""

    async def test_ping(self, gateway_mock_stateful) -> None:
        """Test the ping method."""
        assert await gateway_mock_stateful.ping() is True

    async def test_ping_fail(self, gateway_mock_stateful) -> None:
        """Test the ping method."""
        gateway_mock_stateful._client.info = mock_es_exception(elasticsearch.AuthenticationException)
        with pytest.raises(AuthenticationRequired):
            await gateway_mock_stateful.ping()

        gateway_mock_stateful._client.info = mock_es_exception(elasticsearch.AuthorizationException)
        with pytest.raises(AuthenticationRequired):
            await gateway_mock_stateful.ping()

        gateway_mock_stateful._client.info = mock_es_exception(elasticsearch.ConnectionTimeout)
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

    async def test_bulk(self, gateway_mock_stateful):
        """Test the bulk method."""

        async def yield_doc():
            yield AsyncMock()
            yield AsyncMock()
            yield AsyncMock()

        async def yield_response():
            yield (
                True,  # OK
                {
                    "action": "create",
                    "outcome": {
                        "_index": ".ds-metrics-homeassistant.counter-default-2025.01.12-000001",
                        "_id": "oEmJWJQB7GOvwEliMbKW",
                        "_version": 1,
                        "result": "created",
                        "_shards": {"total": 2, "successful": 1, "failed": 0},
                        "_seq_no": 0,
                        "_primary_term": 1,
                        "status": 201,
                    },
                },
            )

        with patch(
            "custom_components.elasticsearch.es_gateway_8.async_streaming_bulk"
        ) as mock_streaming_bulk:
            mock_streaming_bulk.side_effect = [yield_response()]

            await gateway_mock_stateful.bulk(actions=yield_doc())

            assert mock_streaming_bulk.call_count == 1
            gateway_mock_stateful._logger.info.assert_called_once_with(
                "Successfully published %d documents", 1
            )

    async def test_bulk_nothing_to_do(self, gateway_mock_stateful):
        """Test the bulk method."""

        with patch(
            "custom_components.elasticsearch.es_gateway_8.async_streaming_bulk"
        ) as mock_streaming_bulk:
            await gateway_mock_stateful.bulk(actions=[])

            assert mock_streaming_bulk.call_count == 1
            gateway_mock_stateful._logger.debug.assert_called_once_with(
                "Publish skipped, no new events to publish."
            )

    class Test_Check_Connection:
        """Tests for the check_connection method."""

        @pytest.fixture(name="gateway")
        async def gateway_fixture(self, gateway_settings, mock_logger):
            """Return a gateway instance."""
            gateway = Elasticsearch8Gateway(gateway_settings=gateway_settings)

            gateway._logger = mock_logger

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
                elasticsearch.UnsupportedProductError(
                    message="Unknown product", meta=mock_api_response_meta(), body={}
                ),
                UnsupportedServer,
                "Unsupported product",
            ),
            (
                elasticsearch.TransportError(message="Test Case"),
                CannotConnect,
                "Unknown transport error connecting to Elasticsearch",
            ),
            (
                elasticsearch.AuthenticationException(message="Test Case", meta=MagicMock(), body=None),
                AuthenticationRequired,
                "Authentication error connecting to Elasticsearch",
            ),
            (
                elasticsearch.AuthorizationException(message="Test Case", meta=MagicMock(), body=None),
                InsufficientPrivileges,
                "Authorization error connecting to Elasticsearch",
            ),
            (
                elasticsearch.ConnectionTimeout(message="Test Case"),
                CannotConnect,
                "Connection timeout connecting to Elasticsearch",
            ),
            (
                elasticsearch.SSLError(message="Test Case"),
                UntrustedCertificate,
                "Could not complete TLS Handshake",
            ),
            (
                elasticsearch.ConnectionError(message="Test Case"),
                CannotConnect,
                "Error connecting to Elasticsearch",
            ),
            (
                elasticsearch.ApiError(
                    message="Test Case",
                    meta=mock_api_response_meta(status_code=None),
                    body=None,
                ),
                ServerError,
                "Unknown API Error in request to Elasticsearch",
            ),
            (
                elasticsearch.ApiError(
                    message="Test Case", meta=mock_api_response_meta(status_code=400), body=None
                ),
                ServerError,
                "Error in request to Elasticsearch",
            ),
            (Exception(), Exception, ""),
        ],
        ids=[
            "UnsupportedProductError to UnsupportedServer",
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
        gateway._client = gateway_settings.to_client()
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

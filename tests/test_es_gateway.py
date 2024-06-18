# type: ignore  # noqa: PGH003
"""Tests for the Elasticsearch Gateway."""

import asyncio
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import client_exceptions
from custom_components.elasticsearch.errors import (
    ESIntegrationException,
    InsufficientPrivileges,
    UnsupportedVersion,
    UntrustedCertificate,
)
from custom_components.elasticsearch.es_gateway import (
    CAPABILITIES,
    Elasticsearch7Gateway,
    ElasticsearchGateway,
)
from elasticsearch7 import SSLError
from elasticsearch7 import TransportError as TransportError7
from elasticsearch7._async.client import AsyncElasticsearch as AsyncElasticsearch7
from homeassistant.core import HomeAssistant
from syrupy.assertion import SnapshotAssertion

from tests.const import (
    CLUSTER_INFO_7DOT11_RESPONSE_BODY,
    CLUSTER_INFO_7DOT17_RESPONSE_BODY,
    CLUSTER_INFO_8DOT0_RESPONSE_BODY,
    CLUSTER_INFO_8DOT8_RESPONSE_BODY,
    CLUSTER_INFO_8DOT11_RESPONSE_BODY,
    CLUSTER_INFO_SERVERLESS_RESPONSE_BODY,
)


class Test_Elasticsearch_Gateway:
    """Test ElasticsearchGateway."""

    @pytest.fixture(autouse=True)
    def minimum_privileges(self) -> None:
        """Provide a default empty minimum_privileges object."""
        return

    @pytest.mark.asyncio
    async def test_async_init(
        self,
        hass: HomeAssistant,
        uninitialized_gateway: ElasticsearchGateway,
        minimum_privileges: dict,
        use_connection_monitor: bool,
        config_entry,
    ):
        """Test async_init."""
        with (
            mock.patch.object(
                uninitialized_gateway,
                "_get_cluster_info",
                return_value=CLUSTER_INFO_8DOT0_RESPONSE_BODY,
            ),
            mock.patch.object(uninitialized_gateway, "test_connection", return_value=True),
        ):
            await uninitialized_gateway.async_init(config_entry=config_entry)

        assert uninitialized_gateway._info is not None
        assert uninitialized_gateway._capabilities is not None
        assert uninitialized_gateway._cancel_connection_monitor is None

        await uninitialized_gateway.stop()

    @pytest.mark.asyncio
    async def test_async_init_with_monitor(
        self,
        hass: HomeAssistant,
        uninitialized_gateway: ElasticsearchGateway,
        minimum_privileges: dict,
        config_entry,
    ):
        """Test async_init."""

        uninitialized_gateway._use_connection_monitor = True

        with (
            mock.patch.object(
                uninitialized_gateway,
                "_get_cluster_info",
                return_value=CLUSTER_INFO_8DOT0_RESPONSE_BODY,
            ),
            mock.patch.object(uninitialized_gateway, "test_connection", return_value=True),
        ):
            await uninitialized_gateway.async_init(config_entry=config_entry)

        initialized_gateway = uninitialized_gateway
        assert initialized_gateway._info is not None
        assert initialized_gateway._capabilities is not None
        assert initialized_gateway._cancel_connection_monitor is not None

        await initialized_gateway.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("minimum_privileges", [{}])
    async def test_async_init_with_insufficient_privileges(
        self,
        hass: HomeAssistant,
        uninitialized_gateway: ElasticsearchGateway,
        minimum_privileges: dict,
        config_entry,
    ):
        """Test async_init with insufficient privileges."""
        with (
            mock.patch.object(uninitialized_gateway, "_has_required_privileges", return_value=False),
            mock.patch.object(
                uninitialized_gateway,
                "_get_cluster_info",
                return_value=CLUSTER_INFO_8DOT0_RESPONSE_BODY,
            ),
            mock.patch.object(uninitialized_gateway, "test_connection", return_value=True),
            pytest.raises(InsufficientPrivileges),
        ):
            await uninitialized_gateway.async_init(config_entry=config_entry)

        assert uninitialized_gateway._info is not None
        assert uninitialized_gateway._capabilities is not None
        assert uninitialized_gateway._cancel_connection_monitor is None

    @pytest.mark.asyncio
    async def test_async_init_successful(self, hass: HomeAssistant, config_entry, uninitialized_gateway):
        """Test async_init when initialization is successful."""
        uninitialized_gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "7.11"}})
        uninitialized_gateway.test_connection = AsyncMock(return_value=True)
        uninitialized_gateway._has_required_privileges = AsyncMock(return_value=True)

        await uninitialized_gateway.async_init(config_entry=config_entry)

        initialized_gateway = uninitialized_gateway

        assert initialized_gateway._info == {"version": {"number": "7.11"}}
        assert initialized_gateway._capabilities is not None
        assert initialized_gateway._cancel_connection_monitor is None

    @pytest.mark.asyncio
    async def test_async_init_connection_test_failed(
        self,
        hass: HomeAssistant,
        config_entry,
        uninitialized_gateway,
    ):
        """Test async_init when connection test fails."""
        uninitialized_gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "7.11"}})
        uninitialized_gateway.test_connection = AsyncMock(return_value=False)

        with pytest.raises(ConnectionError):
            await uninitialized_gateway.async_init(config_entry=config_entry)

        assert uninitialized_gateway._info == {"version": {"number": "7.11"}}
        # make sure capabilities is an empty dict
        assert uninitialized_gateway._capabilities == {}
        assert uninitialized_gateway._cancel_connection_monitor is None

    @pytest.mark.asyncio
    async def test_async_init_unsupported_version(self, hass: HomeAssistant, config_entry):
        """Test async_init when the Elasticsearch version is unsupported."""
        gateway = Elasticsearch7Gateway(hass=hass, url="http://my_es_host:9200")
        gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "6.8"}})
        gateway.test_connection = AsyncMock(return_value=True)

        with pytest.raises(UnsupportedVersion):
            await gateway.async_init(config_entry=config_entry)

        assert gateway._info == {"version": {"number": "6.8"}}
        assert gateway._capabilities is not None
        assert not gateway._capabilities[CAPABILITIES.SUPPORTED]
        assert gateway._cancel_connection_monitor is None

    @pytest.mark.asyncio
    async def test_async_init_insufficient_privileges(self, hass: HomeAssistant, config_entry):
        """Test async_init when there are insufficient privileges."""
        gateway = Elasticsearch7Gateway(hass=hass, url="http://my_es_host:9200", minimum_privileges="test")
        gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "7.11"}})
        gateway.test_connection = AsyncMock(return_value=True)
        gateway._has_required_privileges = AsyncMock(return_value=False)

        with pytest.raises(InsufficientPrivileges):
            await gateway.async_init(config_entry=config_entry)

        assert gateway._info == {"version": {"number": "7.11"}}
        assert gateway._capabilities is not None
        assert gateway._cancel_connection_monitor is None

    @pytest.mark.asyncio
    async def test_async_init_ssl_error(self, hass: HomeAssistant, config_entry):
        """Test async_init when there are insufficient privileges."""

        gateway = Elasticsearch7Gateway(hass=hass, url="http://my_es_host:9200", minimum_privileges="test")
        # gateway._get_cluster_info = AsyncMock()

        # create a mock certificate error
        # client_exceptions.ClientConnectorCertificateError()
        certificate_error = client_exceptions.ClientConnectorCertificateError(
            connection_key="test", certificate_error=MagicMock()
        )

        gateway.client.info = AsyncMock(side_effect=SSLError(None, None, certificate_error))

        with pytest.raises(UntrustedCertificate):
            await gateway.async_init(config_entry=config_entry)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mock_test_connection", [False])
    async def test_test_success(
        self,
        hass: HomeAssistant,
        initialized_gateway: ElasticsearchGateway,
        mock_test_connection,
    ):
        """Test the gateway connection test function for success."""

        async_test_result = asyncio.Future()
        async_test_result.set_result(True)

        # assert not await initialized_gateway.test_connection()

        with (
            mock.patch.object(initialized_gateway, "_get_cluster_info", return_value=async_test_result),
        ):
            assert await initialized_gateway.test_connection()

    @pytest.mark.parametrize("mock_test_connection", [False])
    async def test_test_failed(
        self,
        hass: HomeAssistant,
        initialized_gateway: ElasticsearchGateway,
        mock_test_connection,
    ):
        """Test the gateway connection test function for failure."""

        # assert await initialized_gateway.test_connection()

        with (
            mock.patch.object(
                initialized_gateway,
                "_get_cluster_info",
                side_effect=ESIntegrationException(TransportError7(404, "Not Found")),
            ),
        ):
            assert not await initialized_gateway.test_connection()

    @pytest.mark.parametrize(
        ("name", "cluster_info"),
        [
            ("7DOT11_CAPABILITIES", CLUSTER_INFO_7DOT11_RESPONSE_BODY),
            ("7DOT17_CAPABILITIES", CLUSTER_INFO_7DOT17_RESPONSE_BODY),
            ("8DOT0_CAPABILITIES", CLUSTER_INFO_8DOT0_RESPONSE_BODY),
            ("8DOT8_CAPABILITIES", CLUSTER_INFO_8DOT8_RESPONSE_BODY),
            ("8DOT11_CAPABILITIES", CLUSTER_INFO_8DOT11_RESPONSE_BODY),
            ("SERVERLESS_CAPABILITIES", CLUSTER_INFO_SERVERLESS_RESPONSE_BODY),
        ],
    )
    async def test_capabilities(
        self,
        hass: HomeAssistant,
        uninitialized_gateway: ElasticsearchGateway,
        name: str,
        cluster_info: dict,
        snapshot: SnapshotAssertion,
        config_entry,
    ):
        """Test capabilities."""
        with (
            mock.patch.object(uninitialized_gateway, "_get_cluster_info", return_value=cluster_info),
            mock.patch.object(uninitialized_gateway, "test_connection", return_value=True),
        ):
            await uninitialized_gateway.async_init(config_entry=config_entry)

        assert uninitialized_gateway._capabilities is not None

        assert {
            "name": name,
            "cluster info": cluster_info,
            "capabilities": uninitialized_gateway._capabilities,
        } == snapshot

    async def test_has_capability(self, hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
        """Test has_capability."""
        uninitialized_gateway._capabilities = {
            "supported": True,
            "timeseries_datastream": True,
            "ignore_missing_component_templates": False,
            "datastream_lifecycle_management": True,
            "max_primary_shard_size": False,
        }

        assert uninitialized_gateway.has_capability("supported") is True
        assert uninitialized_gateway.has_capability("timeseries_datastream") is True
        assert uninitialized_gateway.has_capability("ignore_missing_component_templates") is False
        assert uninitialized_gateway.has_capability("datastream_lifecycle_management") is True
        assert uninitialized_gateway.has_capability("max_primary_shard_size") is False
        assert uninitialized_gateway.has_capability("invalid_capability") is False

    async def test_client(self, hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
        """Test Getter for client."""
        uninitialized_gateway._client = mock.Mock(spec=AsyncElasticsearch7)

        assert uninitialized_gateway.client == uninitialized_gateway._client

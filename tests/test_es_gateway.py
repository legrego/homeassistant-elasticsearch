# type: ignore  # noqa: PGH003
"""Tests for the Elasticsearch Gateway."""

import asyncio
from unittest import mock
from unittest.mock import AsyncMock

import pytest
from elasticsearch7 import TransportError as TransportError7
from elasticsearch7._async.client import AsyncElasticsearch as AsyncElasticsearch7
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from custom_components.elasticsearch.errors import (
    ESIntegrationException,
    InsufficientPrivileges,
    UnsupportedVersion,
)
from custom_components.elasticsearch.es_gateway import (
    CAPABILITIES,
    Elasticsearch7Gateway,
    Elasticsearch8Gateway,
    ElasticsearchGateway,
)
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

    @pytest.fixture(autouse=True)
    def use_connection_monitor(self):
        """Provide a default use_connection_monitor object."""

        return False

    @pytest.fixture
    async def mock_config_entry(self, hass):
        """Mock a config entry."""

        config_entry = MockConfigEntry()
        config_entry.add_to_hass(hass)

        yield config_entry

        # Kill all tasks associated with this config_entry
        for task in config_entry._background_tasks:
            task.cancel("Tests finished")

    @pytest.mark.asyncio()
    async def test_async_init(
        self,
        hass: HomeAssistant,
        uninitialized_gateway: ElasticsearchGateway,
        minimum_privileges: dict,
        use_connection_monitor: bool,
        mock_config_entry,
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
            await uninitialized_gateway.async_init(config_entry=mock_config_entry)

        assert uninitialized_gateway._info is not None
        assert uninitialized_gateway._capabilities is not None
        assert uninitialized_gateway._cancel_connection_monitor is None

        await uninitialized_gateway.stop()

    @pytest.mark.asyncio()
    async def test_async_init_with_monitor(
        self,
        hass: HomeAssistant,
        uninitialized_gateway: ElasticsearchGateway,
        minimum_privileges: dict,
        mock_config_entry,
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
            await uninitialized_gateway.async_init(config_entry=mock_config_entry)

        initialized_gateway = uninitialized_gateway
        assert initialized_gateway._info is not None
        assert initialized_gateway._capabilities is not None
        assert initialized_gateway._cancel_connection_monitor is not None

        await initialized_gateway.stop()

    @pytest.mark.asyncio()
    @pytest.mark.parametrize("minimum_privileges", [{}])
    async def test_async_init_with_insufficient_privileges(
        self,
        hass: HomeAssistant,
        uninitialized_gateway: ElasticsearchGateway,
        minimum_privileges: dict,
        mock_config_entry,
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
            await uninitialized_gateway.async_init(config_entry=mock_config_entry)

        assert uninitialized_gateway._info is not None
        assert uninitialized_gateway._capabilities is not None
        assert uninitialized_gateway._cancel_connection_monitor is None

    @pytest.mark.asyncio()
    async def test_async_init_successful(self, hass: HomeAssistant, mock_config_entry, uninitialized_gateway):
        """Test async_init when initialization is successful."""
        uninitialized_gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "7.11"}})
        uninitialized_gateway.test_connection = AsyncMock(return_value=True)
        uninitialized_gateway._has_required_privileges = AsyncMock(return_value=True)

        await uninitialized_gateway.async_init(config_entry=mock_config_entry)

        initialized_gateway = uninitialized_gateway

        assert initialized_gateway._info == {"version": {"number": "7.11"}}
        assert initialized_gateway._capabilities is not None
        assert initialized_gateway._cancel_connection_monitor is None

    @pytest.mark.asyncio()
    async def test_async_init_connection_test_failed(
        self,
        hass: HomeAssistant,
        mock_config_entry,
        uninitialized_gateway,
    ):
        """Test async_init when connection test fails."""
        uninitialized_gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "7.11"}})
        uninitialized_gateway.test_connection = AsyncMock(return_value=False)

        with pytest.raises(ConnectionError):
            await uninitialized_gateway.async_init(config_entry=mock_config_entry)

        assert uninitialized_gateway._info == {"version": {"number": "7.11"}}
        # make sure capabilities is an empty dict
        assert uninitialized_gateway._capabilities == {}
        assert uninitialized_gateway._cancel_connection_monitor is None

    @pytest.mark.asyncio()
    async def test_async_init_unsupported_version(self, hass: HomeAssistant, mock_config_entry):
        """Test async_init when the Elasticsearch version is unsupported."""
        gateway = Elasticsearch7Gateway(hass=hass, url="http://localhost:9200")
        gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "6.8"}})
        gateway.test_connection = AsyncMock(return_value=True)

        with pytest.raises(UnsupportedVersion):
            await gateway.async_init(config_entry=mock_config_entry)

        assert gateway._info == {"version": {"number": "6.8"}}
        assert gateway._capabilities is not None
        assert not gateway._capabilities[CAPABILITIES.SUPPORTED]
        assert gateway._cancel_connection_monitor is None

    @pytest.mark.asyncio()
    async def test_async_init_insufficient_privileges(self, hass: HomeAssistant, mock_config_entry):
        """Test async_init when there are insufficient privileges."""
        gateway = Elasticsearch7Gateway(hass=hass, url="http://localhost:9200", minimum_privileges="test")
        gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "7.11"}})
        gateway.test_connection = AsyncMock(return_value=True)
        gateway._has_required_privileges = AsyncMock(return_value=False)

        with pytest.raises(InsufficientPrivileges):
            await gateway.async_init(config_entry=mock_config_entry)

        assert gateway._info == {"version": {"number": "7.11"}}
        assert gateway._capabilities is not None
        assert gateway._cancel_connection_monitor is None

    @pytest.mark.asyncio()
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

        with (
            mock.patch.object(
                initialized_gateway,
                "_get_cluster_info",
                side_effect=ESIntegrationException(TransportError7(404, "Not Found")),
            ),
        ):
            assert not await initialized_gateway.test_connection()

    @pytest.mark.parametrize("minimum_privileges", [None, {}])
    async def test_build_gateway_parameters(self, hass: HomeAssistant, minimum_privileges: dict | None):
        """Test build_gateway_parameters."""
        hass = mock.Mock()
        config_entry = mock.Mock()
        config_entry.data = {
            "url": "http://localhost:9200",
            "username": "admin",
            "password": "password",
            "verify_ssl": True,
            "ca_certs": "/path/to/ca_certs",
            "timeout": 30,
        }
        """ Test build_gateway_parameters."""

        parameters = ElasticsearchGateway.build_gateway_parameters(
            hass=hass,
            config_entry=config_entry,
            minimum_privileges=minimum_privileges,
        )

        assert parameters["hass"] == hass
        assert parameters["url"] == "http://localhost:9200"
        assert parameters["username"] == "admin"
        assert parameters["password"] == "password"  # noqa: S105
        assert parameters["verify_certs"] is True
        assert parameters["ca_certs"] == "/path/to/ca_certs"
        assert parameters["request_timeout"] == 30
        assert parameters["minimum_privileges"] == minimum_privileges

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
        mock_config_entry,
    ):
        """Test capabilities."""
        with (
            mock.patch.object(uninitialized_gateway, "_get_cluster_info", return_value=cluster_info),
            mock.patch.object(uninitialized_gateway, "test_connection", return_value=True),
        ):
            await uninitialized_gateway.async_init(config_entry=mock_config_entry)

        assert uninitialized_gateway._capabilities is not None

        assert {
            "name": name,
            "cluster info": cluster_info,
            "capabilities": uninitialized_gateway._capabilities,
        } == snapshot

    def test_has_capability(self, hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
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

    def test_client(self, hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
        """Test Getter for client."""
        uninitialized_gateway._client = mock.Mock(spec=AsyncElasticsearch7)

        assert uninitialized_gateway.client == uninitialized_gateway._client

    def test_authentication_type(self, hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
        """Test Getter for authentication_type."""

        if isinstance(uninitialized_gateway, Elasticsearch7Gateway):
            GatewayType = Elasticsearch7Gateway
        elif isinstance(uninitialized_gateway, Elasticsearch8Gateway):
            GatewayType = Elasticsearch8Gateway

        base_args = {
            "hass": hass,
            "url": "http://localhost:9200",
            "minimum_privileges": {},
            "use_connection_monitor": False,
        }

        basic_gateway = GatewayType(**base_args, username="admin", password="password")  # noqa: S106

        assert basic_gateway.authentication_type == "basic"

        api_key_gateway = GatewayType(**base_args, api_key="api_key")

        assert api_key_gateway.authentication_type == "api_key"

        no_auth_gateway = GatewayType(**base_args)

        assert no_auth_gateway.authentication_type == "none"

    def test_hass(self, hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
        """Test Getter for hass."""
        uninitialized_gateway._hass = mock.Mock()

        assert uninitialized_gateway.hass == uninitialized_gateway._hass

    def test_url(self, hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
        """Test Getter for url."""
        uninitialized_gateway._url = "http://localhost:9200"

        assert uninitialized_gateway.url == "http://localhost:9200"

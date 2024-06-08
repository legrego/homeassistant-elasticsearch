# type: ignore  # noqa: PGH003
"""Tests for the Elasticsearch Gateway."""

import asyncio
from unittest import mock
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.json import JSONSnapshotExtension

from custom_components.elasticsearch.es_gateway import (
    CAPABILITIES,
    ConnectionMonitor,
    Elasticsearch7Gateway,
    Elasticsearch8Gateway,
    ElasticsearchGateway,
    InsufficientPrivileges,
    UnsupportedVersion,
)
from tests.const import (
    CLUSTER_INFO_7DOT11_RESPONSE_BODY,
    CLUSTER_INFO_7DOT17_RESPONSE_BODY,
    CLUSTER_INFO_8DOT0_RESPONSE_BODY,
    CLUSTER_INFO_8DOT8_RESPONSE_BODY,
    CLUSTER_INFO_8DOT11_RESPONSE_BODY,
    CLUSTER_INFO_SERVERLESS_RESPONSE_BODY,
)


@pytest.fixture(autouse=True)
def snapshot(snapshot: SnapshotAssertion):
    """Provide a pre-configured snapshot object."""

    return snapshot.with_defaults(extension_class=JSONSnapshotExtension)


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

    @pytest.fixture(params=[Elasticsearch7Gateway, Elasticsearch8Gateway])
    async def uninitialized_gateway(
        self,
        hass: HomeAssistant,
        request: pytest.FixtureRequest,
        minimum_privileges: dict,
        use_connection_monitor: bool,
        url: str = "http://localhost:9200",
    ):
        """Return a gateway instance."""

        gateway_type: ElasticsearchGateway = request.param

        return gateway_type(
            hass=hass,
            url=url,
            minimum_privileges=minimum_privileges,
            use_connection_monitor=use_connection_monitor,
        )

    @pytest.fixture(params=[Elasticsearch7Gateway, Elasticsearch8Gateway])
    async def initialized_gateway(
        self,
        hass: HomeAssistant,
        request: pytest.FixtureRequest,
        minimum_privileges: dict,
        use_connection_monitor: bool,
        url: str = "http://localhost:9200",
    ):
        """Return a gateway instance."""

        gateway_type: ElasticsearchGateway = request.param

        new_gateway = gateway_type(
            hass=hass,
            url=url,
            minimum_privileges=minimum_privileges,
            use_connection_monitor=use_connection_monitor,
        )

        with (
            mock.patch.object(
                new_gateway,
                "_get_cluster_info",
                return_value=CLUSTER_INFO_8DOT0_RESPONSE_BODY,
            ),
            mock.patch.object(new_gateway, "test", return_value=True),
        ):
            await new_gateway.async_init()

        return new_gateway

    @pytest.mark.asyncio()
    async def test_async_init(
        self,
        hass: HomeAssistant,
        uninitialized_gateway: ElasticsearchGateway,
        minimum_privileges: dict,
        use_connection_monitor: bool,
    ):
        """Test async_init."""
        with (
            mock.patch.object(
                uninitialized_gateway,
                "_get_cluster_info",
                return_value=CLUSTER_INFO_8DOT0_RESPONSE_BODY,
            ),
            mock.patch.object(uninitialized_gateway, "test", return_value=True),
        ):
            await uninitialized_gateway.async_init()

        assert uninitialized_gateway._info is not None
        assert uninitialized_gateway._capabilities is not None
        assert uninitialized_gateway._connection_monitor is not None

        await uninitialized_gateway.stop()

    @pytest.mark.asyncio()
    @pytest.mark.parametrize("minimum_privileges", [{}])
    async def test_async_init_with_insufficient_privileges(
        self,
        hass: HomeAssistant,
        uninitialized_gateway: ElasticsearchGateway,
        minimum_privileges: dict,
    ):
        """Test async_init with insufficient privileges."""
        with (
            mock.patch.object(uninitialized_gateway, "_has_required_privileges", return_value=False),
            mock.patch.object(
                uninitialized_gateway,
                "_get_cluster_info",
                return_value=CLUSTER_INFO_8DOT0_RESPONSE_BODY,
            ),
            mock.patch.object(uninitialized_gateway, "test", return_value=True),
            pytest.raises(InsufficientPrivileges),
        ):
            await uninitialized_gateway.async_init()

        assert uninitialized_gateway._info is not None
        assert uninitialized_gateway._capabilities is not None
        assert uninitialized_gateway._connection_monitor is not None

    @pytest.mark.asyncio()
    async def test_async_init_successful(self, hass: HomeAssistant):
        """Test async_init when initialization is successful."""
        gateway = Elasticsearch7Gateway(hass=hass, url="http://localhost:9200")
        gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "7.11"}})
        gateway.test = AsyncMock(return_value=True)
        gateway._has_required_privileges = AsyncMock(return_value=True)

        await gateway.async_init()

        assert gateway._info == {"version": {"number": "7.11"}}
        assert gateway._capabilities is not None
        assert gateway._connection_monitor is not None

    @pytest.mark.asyncio()
    async def test_async_init_connection_test_failed(self, hass: HomeAssistant):
        """Test async_init when connection test fails."""
        gateway = Elasticsearch7Gateway(hass=hass, url="http://localhost:9200")
        gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "7.11"}})
        gateway.test = AsyncMock(return_value=False)

        with pytest.raises(ConnectionError):
            await gateway.async_init()

        assert gateway._info == {"version": {"number": "7.11"}}
        # make sure capabilities is an empty dict
        assert gateway._capabilities == {}
        assert gateway._connection_monitor is not None

    @pytest.mark.asyncio()
    async def test_async_init_unsupported_version(self, hass: HomeAssistant):
        """Test async_init when the Elasticsearch version is unsupported."""
        gateway = Elasticsearch7Gateway(hass=hass, url="http://localhost:9200")
        gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "6.8"}})
        gateway.test = AsyncMock(return_value=True)

        with pytest.raises(UnsupportedVersion):
            await gateway.async_init()

        assert gateway._info == {"version": {"number": "6.8"}}
        assert gateway._capabilities is not None
        assert not gateway._capabilities[CAPABILITIES.SUPPORTED]
        assert gateway._connection_monitor is not None

    @pytest.mark.asyncio()
    async def test_async_init_insufficient_privileges(self, hass: HomeAssistant):
        """Test async_init when there are insufficient privileges."""
        gateway = Elasticsearch7Gateway(hass=hass, url="http://localhost:9200", minimum_privileges="test")
        gateway._get_cluster_info = AsyncMock(return_value={"version": {"number": "7.11"}})
        gateway.test = AsyncMock(return_value=True)
        gateway._has_required_privileges = AsyncMock(return_value=False)

        with pytest.raises(InsufficientPrivileges):
            await gateway.async_init()

        assert gateway._info == {"version": {"number": "7.11"}}
        assert gateway._capabilities is not None
        assert gateway._connection_monitor is not None

    @pytest.mark.asyncio()
    async def test_test_success(self, hass: HomeAssistant, initialized_gateway: ElasticsearchGateway):
        """Test the gateway connection test function for success."""

        async_test_result = asyncio.Future()
        async_test_result.set_result(True)

        with (
            mock.patch.object(initialized_gateway, "_get_cluster_info", return_value=async_test_result),
        ):
            assert await initialized_gateway.test()

    @pytest.mark.asyncio()
    async def test_test_failed(self, hass: HomeAssistant, initialized_gateway: ElasticsearchGateway):
        """Test the gateway connection test function for failure."""

        with (
            mock.patch.object(initialized_gateway, "_get_cluster_info", side_effect=Exception("Info Failed")),
        ):
            assert not await initialized_gateway.test()

    @pytest.mark.parametrize("minimum_privileges", [None, {}])
    async def test_build_gateway_parameters(self, hass: HomeAssistant, minimum_privileges: dict | None):
        """Test build_gateway_parameters."""
        hass = mock.Mock()
        config_entry = mock.Mock()
        config_entry.data = {
            "url": "http://localhost:9200",
            "username": "admin",
            "password": "password",
            "verify_certs": True,
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
    ):
        """Test capabilities."""
        with (
            mock.patch.object(uninitialized_gateway, "_get_cluster_info", return_value=cluster_info),
            mock.patch.object(uninitialized_gateway, "test", return_value=True),
        ):
            await uninitialized_gateway.async_init()

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
        uninitialized_gateway._client = mock.Mock()

        assert uninitialized_gateway.client == uninitialized_gateway._client

    def test_connection_monitor(self, hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
        """Test Getter for connection_monitor."""
        uninitialized_gateway._connection_monitor = mock.Mock()

        assert uninitialized_gateway.connection_monitor == uninitialized_gateway._connection_monitor

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


class Test_Connection_Monitor:
    """Test ConnectionMonitor."""

    @pytest.fixture
    async def connection_monitor(self):
        """Return a connection monitor instance."""
        gateway = mock.Mock()
        connection_monitor = ConnectionMonitor(gateway)

        yield connection_monitor

        connection_monitor.stop()

    async def test_active(self):
        """Test active."""
        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)
        monitor._active = True

        assert monitor.active is True

        monitor.stop()

    async def test_previous(self):
        """Test previous."""
        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)
        monitor._previous = True

        assert monitor.previous is True

        monitor.stop()

    async def test_should_test(self):
        """Test should_test."""

        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)
        monitor._next_test = 0

        assert monitor.should_test() is True

        monitor.stop()

    async def test_spin(self):
        """Test spin."""

        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)

        await monitor.spin()

        # Add assertions here

    async def test_connection_monitor_task(self):
        """Test _connection_monitor_task."""
        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)

        async_test_result = asyncio.Future()
        async_test_result.set_result(True)

        with (
            mock.patch.object(monitor, "should_test", return_value=True),
            mock.patch.object(monitor, "test", return_value=True),
        ):
            await monitor._connection_monitor_task(single_test=True)

            assert monitor._previous is False
            assert monitor._active is True

            await monitor._connection_monitor_task(single_test=True)

            assert monitor._previous is True
            assert monitor._active is True

        monitor.stop()

    async def test_test_success(self):
        """Test test."""
        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)

        async_test_result = asyncio.Future()
        async_test_result.set_result(True)

        with (
            mock.patch.object(monitor, "should_test", return_value=True),
            mock.patch.object(gateway, "test", return_value=async_test_result),
        ):
            assert await monitor.test() is True

        monitor.stop()

    async def test_test_failure(self):
        """Test test."""
        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)

        async_test_result = asyncio.Future()
        async_test_result.set_result(False)

        with (
            mock.patch.object(monitor, "should_test", return_value=True),
            mock.patch.object(gateway, "test", return_value=async_test_result),
        ):
            assert await monitor.test() is False

        monitor.stop()

    async def test_stop(self):
        """Test stop."""
        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)
        monitor._active = True

        monitor.stop()

        assert monitor.active is False

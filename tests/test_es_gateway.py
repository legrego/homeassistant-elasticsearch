"""Tests for the Elasticsearch Gateway."""

import asyncio
from unittest import mock

import pytest
from homeassistant.core import HomeAssistant
from syrupy.extensions.json import JSONSnapshotExtension

from custom_components.elasticsearch.es_gateway import (
    ConnectionMonitor,
    Elasticsearch7Gateway,
    Elasticsearch8Gateway,
    ElasticsearchGateway,
    InsufficientPrivileges,
)

from .const import (
    CLUSTER_INFO_7DOT11_RESPONSE_BODY,
    CLUSTER_INFO_7DOT17_RESPONSE_BODY,
    CLUSTER_INFO_8DOT0_RESPONSE_BODY,
    CLUSTER_INFO_8DOT8_RESPONSE_BODY,
    CLUSTER_INFO_8DOT11_RESPONSE_BODY,
    CLUSTER_INFO_SERVERLESS_RESPONSE_BODY,
)


@pytest.fixture(autouse=True)
def snapshot(snapshot):
    """Provide a pre-configured snapshot object."""

    return snapshot.with_defaults(extension_class=JSONSnapshotExtension)


class Test_Elasticsearch_Gateway:
    """Test ElasticsearchGateway."""

    @pytest.fixture(autouse=True)
    def minimum_privileges(self):
        """Provide a default empty minimum_privileges object."""

        return None

    @pytest.fixture(autouse=True)
    def use_connection_monitor(self):
        """Provide a default use_connection_monitor object."""

        return False

    @pytest.fixture(params=[Elasticsearch7Gateway, Elasticsearch8Gateway])
    async def uninitialized_gateway(
        hass: HomeAssistant,
        request: pytest.FixtureRequest,
        minimum_privileges,
        use_connection_monitor,
        url: str = "http://localhost:9200",
    ):
        """Return a gateway instance."""

        gateway_type: ElasticsearchGateway = request.param

        new_gateway = gateway_type(hass=hass, url=url, minimum_privileges=minimum_privileges, use_connection_monitor=use_connection_monitor)

        return new_gateway

    @pytest.fixture(params=[Elasticsearch7Gateway, Elasticsearch8Gateway])
    async def initialized_gateway(
        hass: HomeAssistant,
        request: pytest.FixtureRequest,
        minimum_privileges,
        use_connection_monitor,
        url: str = "http://localhost:9200",
    ):
        """Return a gateway instance."""

        gateway_type: ElasticsearchGateway = request.param

        new_gateway = gateway_type(hass=hass, url=url, minimum_privileges=minimum_privileges, use_connection_monitor=use_connection_monitor)

        with (
            mock.patch.object(new_gateway, "_get_cluster_info", return_value=CLUSTER_INFO_8DOT0_RESPONSE_BODY),
            mock.patch.object(new_gateway, "test", return_value=True),
        ):
            await new_gateway.async_init()

        return new_gateway

    @pytest.mark.asyncio
    async def test_async_init(hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway, minimum_privileges, use_connection_monitor):
        """Test async_init."""
        with (
            mock.patch.object(uninitialized_gateway, "_get_cluster_info", return_value=CLUSTER_INFO_8DOT0_RESPONSE_BODY),
            mock.patch.object(uninitialized_gateway, "test", return_value=True),
        ):
            await uninitialized_gateway.async_init()

        assert uninitialized_gateway._info is not None
        assert uninitialized_gateway._capabilities is not None
        assert uninitialized_gateway._connection_monitor is None

        uninitialized_gateway.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("minimum_privileges", [{}])
    async def test_async_init_with_insufficient_privileges(
        hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway, minimum_privileges: dict
    ):
        """Test async_init with insufficient privileges."""
        with (
            mock.patch.object(uninitialized_gateway, "_has_required_privileges", return_value=False),
            mock.patch.object(uninitialized_gateway, "_get_cluster_info", return_value=CLUSTER_INFO_8DOT0_RESPONSE_BODY),
            mock.patch.object(uninitialized_gateway, "test", return_value=True),
            pytest.raises(InsufficientPrivileges),
        ):
            await uninitialized_gateway.async_init()

        assert uninitialized_gateway._info is not None
        assert uninitialized_gateway._capabilities is not None
        assert uninitialized_gateway._connection_monitor is None

    @pytest.mark.asyncio
    async def test_test_success(hass: HomeAssistant, initialized_gateway: ElasticsearchGateway):
        """Test the gateway connection test function for success."""

        async_test_result = asyncio.Future()
        async_test_result.set_result(True)

        with (
            mock.patch.object(initialized_gateway, "_get_cluster_info", return_value=async_test_result),
        ):
            assert await initialized_gateway.test()

    @pytest.mark.asyncio
    async def test_test_failed(hass: HomeAssistant, initialized_gateway: ElasticsearchGateway):
        """Test the gateway connection test function for failure."""

        with (
            mock.patch.object(initialized_gateway, "_get_cluster_info", side_effect=Exception("Info Failed")),
        ):
            assert not await initialized_gateway.test()

    @pytest.mark.parametrize("minimum_privileges", [None, {}])
    async def test_build_gateway_parameters(hass: HomeAssistant, minimum_privileges: dict | None):
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

        parameters = ElasticsearchGateway.build_gateway_parameters(hass=hass, config_entry=config_entry, minimum_privileges=minimum_privileges)

        assert parameters["hass"] == hass
        assert parameters["url"] == "http://localhost:9200"
        assert parameters["username"] == "admin"
        assert parameters["password"] == "password"
        assert parameters["verify_certs"] is True
        assert parameters["ca_certs"] == "/path/to/ca_certs"
        assert parameters["request_timeout"] == 30
        assert parameters["minimum_privileges"] == minimum_privileges

    @pytest.mark.parametrize(
        "name, cluster_info",
        [
            ("7DOT11_CAPABILITIES", CLUSTER_INFO_7DOT11_RESPONSE_BODY),
            ("7DOT17_CAPABILITIES", CLUSTER_INFO_7DOT17_RESPONSE_BODY),
            ("8DOT0_CAPABILITIES", CLUSTER_INFO_8DOT0_RESPONSE_BODY),
            ("8DOT8_CAPABILITIES", CLUSTER_INFO_8DOT8_RESPONSE_BODY),
            ("8DOT11_CAPABILITIES", CLUSTER_INFO_8DOT11_RESPONSE_BODY),
            ("SERVERLESS_CAPABILITIES", CLUSTER_INFO_SERVERLESS_RESPONSE_BODY),
        ],
    )
    async def test_capabilities(hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway, name: str, cluster_info: dict, snapshot):
        """Test capabilities."""
        with (
            mock.patch.object(uninitialized_gateway, "_get_cluster_info", return_value=cluster_info),
            mock.patch.object(uninitialized_gateway, "test", return_value=True),
        ):
            await uninitialized_gateway.async_init()

        assert uninitialized_gateway._capabilities is not None

        assert {"name": name, "cluster info": cluster_info, "capabilities": uninitialized_gateway._capabilities} == snapshot

    def test_has_capability(hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
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

    def test_client(hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
        """Test Getter for client."""
        uninitialized_gateway._client = mock.Mock()

        assert uninitialized_gateway.client == uninitialized_gateway._client

    def test_connection_monitor(hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
        """Test Getter for connection_monitor."""
        uninitialized_gateway._connection_monitor = mock.Mock()

        assert uninitialized_gateway.connection_monitor == uninitialized_gateway._connection_monitor

    def test_authentication_type(hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
        """Test Getter for authentication_type."""
        uninitialized_gateway.username = "admin"
        uninitialized_gateway.password = "password"
        uninitialized_gateway.api_key = None

        assert uninitialized_gateway.authentication_type == "basic"

        uninitialized_gateway.username = None
        uninitialized_gateway.password = None
        uninitialized_gateway.api_key = "api_key"

        assert uninitialized_gateway.authentication_type == "api_key"

        uninitialized_gateway.username = None
        uninitialized_gateway.password = None
        uninitialized_gateway.api_key = None

        assert uninitialized_gateway.authentication_type == "none"

    def test_hass(hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
        """Test Getter for hass."""
        uninitialized_gateway._hass = mock.Mock()

        assert uninitialized_gateway.hass == uninitialized_gateway._hass

    def test_url(hass: HomeAssistant, uninitialized_gateway: ElasticsearchGateway):
        """Test Getter for url."""
        uninitialized_gateway._url = "http://localhost:9200"

        assert uninitialized_gateway.url == "http://localhost:9200"


class Test_Connection_Monitor:
    """Test ConnectionMonitor."""

    @pytest.fixture()
    async def connection_monitor(self):
        """Return a connection monitor instance."""
        gateway = mock.Mock()
        connection_monitor = ConnectionMonitor(gateway)

        yield connection_monitor

        await connection_monitor.stop()

    async def test_async_init(self):
        """Test async_init."""

        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)
        hass = mock.Mock()

        with (
            mock.patch.object(monitor, "should_test", return_value=True),
            mock.patch.object(monitor, "test", return_value=True),
            mock.patch.object(hass, "async_create_background_task", return_value=True),
        ):
            await monitor.async_init()

        assert monitor.active is True
        assert monitor.task is not None

        await monitor.stop()

    async def test_active(self):
        """Test active."""
        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)
        monitor._active = True

        assert monitor.active is True

        await monitor.stop()

    async def test_previous(self):
        """Test previous."""
        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)
        monitor._previous = True

        assert monitor.previous is True

        await monitor.stop()

    async def test_should_test(self):
        """Test should_test."""

        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)
        monitor._next_test = 0

        assert monitor.should_test() is True

        await monitor.stop()

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

        await monitor.stop()

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

        await monitor.stop()

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

        await monitor.stop()

    async def test_stop(self):
        """Test stop."""
        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)
        monitor._active = True
        monitor._task = mock.Mock()

        await monitor.stop()

        assert monitor.active is False
        assert monitor.task is None

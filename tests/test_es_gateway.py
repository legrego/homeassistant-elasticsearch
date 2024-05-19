"""Tests for the Elasticsearch Gateway."""

import asyncio
import time
from unittest import mock
from homeassistant.core import HomeAssistant

from custom_components.elasticsearch.es_gateway import ConnectionMonitor


class TestConnectionMonitor:
    """Test ConnectionMonitor."""

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

    def test_active(self):
        """Test active."""
        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)
        monitor._active = True

        assert monitor.active is True

    def test_previous(self):
        """Test previous."""
        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)
        monitor._previous = True

        assert monitor.previous is True

    def test_should_test(self):
        """Test should_test."""

        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)
        monitor._next_test = time.monotonic() - 10

        assert monitor.should_test() is True

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

    async def test_test(self):
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

    async def test_stop(self):
        """Test stop."""
        gateway = mock.Mock()
        monitor = ConnectionMonitor(gateway)
        monitor._active = True
        monitor._task = mock.Mock()

        await monitor.stop()

        assert monitor.active is False
        assert monitor.task is None

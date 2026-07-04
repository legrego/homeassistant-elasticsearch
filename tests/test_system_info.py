# type: ignore  # noqa: PGH003
"""Test Entity Details."""

from unittest import mock
from unittest.mock import AsyncMock, Mock

import pytest
from custom_components.elasticsearch.system_info import SystemInfo, SystemInfoResult
from homeassistant.const import __version__ as current_version
from homeassistant.core import HomeAssistant


class Test_Initialization:
    """Integration tests for system_info.py."""

    async def test_init(self, hass: HomeAssistant):
        """Verify the SystemInfo class is initialized correctly."""
        sys_info = SystemInfo(hass)

        assert sys_info is not None
        assert sys_info._hass == hass


class Test_SystemInfo:
    """Test the SystemInfo class methods."""

    @pytest.fixture(name="sys_info")
    def sys_info_fixture(self, hass: HomeAssistant):
        """Return a SystemInfo instance."""
        return SystemInfo(hass)

    async def test_async_get_system_info(self, sys_info):
        """Verify system information is retrieved correctly."""
        result = await sys_info.async_get_system_info()

        assert isinstance(result, SystemInfoResult)
        assert result.version == current_version
        assert result.arch is not None
        assert result.os_name is not None
        assert result.os_version is not None
        assert result.hostname is not None

    async def test_async_get_system_info_non_hassio(self, sys_info):
        """Verify we rely on the hostname from the socket module on non-HASSio systems."""
        sys_info._get_system_info = AsyncMock(
            return_value={
                "hassio": False,
                "version": "1.0",
                "arch": "x86_64",
                "os_name": "Linux",
                "os_version": "4.4.0-109-generic",
                "hostname": None,
            }
        )
        sys_info._get_host_info = Mock(return_value={})

        with mock.patch("socket.gethostname", return_value="test-hostname"):
            result = await sys_info.async_get_system_info()

            assert isinstance(result, SystemInfoResult)
            assert result.version == "1.0"
            assert result.arch == "x86_64"
            assert result.hostname == "test-hostname"

        # Regression test for #563: on non-Hassio installs, get_host_info() is
        # unsafe to call (it raises HassioNotReadyError), so it must be skipped
        # entirely rather than merely having its return value discarded.
        sys_info._get_host_info.assert_not_called()

    async def test_async_get_system_info_hassio(self, sys_info):
        """Verify the hostname is sourced from host info when running under Hassio."""
        sys_info._get_system_info = AsyncMock(
            return_value={
                "hassio": True,
                "version": "1.0",
                "arch": "x86_64",
                "os_name": "Linux",
                "os_version": "4.4.0-109-generic",
                "hostname": None,
            }
        )
        sys_info._get_host_info = Mock(return_value={"hostname": "hassio-hostname"})

        result = await sys_info.async_get_system_info()

        assert isinstance(result, SystemInfoResult)
        assert result.hostname == "hassio-hostname"

    async def test_async_get_system_info_hassio_not_ready(self, sys_info):
        """Verify we fall back to the socket hostname if Hassio host info is unavailable.

        Regression test for #563: the Supervisor coordinator can raise
        HassioNotReadyError (e.g. before its first refresh completes), and that
        must not crash integration setup.
        """
        sys_info._get_system_info = AsyncMock(
            return_value={
                "hassio": True,
                "version": "1.0",
                "arch": "x86_64",
                "os_name": "Linux",
                "os_version": "4.4.0-109-generic",
                "hostname": None,
            }
        )
        sys_info._get_host_info = Mock(return_value=None)

        with mock.patch("socket.gethostname", return_value="test-hostname"):
            result = await sys_info.async_get_system_info()

            assert isinstance(result, SystemInfoResult)
            assert result.hostname == "test-hostname"

    async def test_get_host_info(self, sys_info):
        """Verify host information returns None on non-HASSio systems."""
        host_info = sys_info._get_host_info()

        assert host_info is None

    async def test_get_host_info_swallows_errors(self, sys_info):
        """Verify errors raised by HASS's get_host_info are handled gracefully.

        Regression test for #563: newer Home Assistant versions may raise
        (e.g. HassioNotReadyError) instead of returning None when host info
        isn't available yet, e.g. on non-Hassio installs or before the
        Supervisor coordinator's first refresh.
        """
        with mock.patch(
            "custom_components.elasticsearch.system_info.get_host_info",
            side_effect=RuntimeError("HassioNotReadyError"),
        ):
            host_info = sys_info._get_host_info()

        assert host_info is None

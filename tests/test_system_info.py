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

    async def test_get_host_info(self, sys_info):
        """Verify host information is returns an error on non-HASSio systems."""
        host_info = sys_info._get_host_info()

        assert host_info is None

# type: ignore  # noqa: PGH003
"""Test Entity Details."""

from custom_components.elasticsearch.system_info import SystemInfo, SystemInfoResult
from homeassistant.const import __version__ as current_version
from homeassistant.core import HomeAssistant


class Test_Integration_Tests:
    """Integration tests for system_info.py."""

    async def test_async_get_system_info(self, hass: HomeAssistant):
        """Verify system information is retrieved correctly."""
        sys_info = SystemInfo(hass)
        result = await sys_info.async_get_system_info()

        assert isinstance(result, SystemInfoResult)
        assert result.version == current_version
        assert result.arch is not None
        assert result.os_name is not None
        assert result.os_version is not None
        assert result.hostname is not None

    async def test_get_host_info(self, hass: HomeAssistant):
        """Verify host information is returns an error on non-HASSio systems."""
        sys_info = SystemInfo(hass)
        host_info = sys_info._get_host_info()

        assert host_info is None

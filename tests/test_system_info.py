# type: ignore  # noqa: PGH003
"""Test Entity Details."""

from unittest import mock

import pytest
from homeassistant.const import __version__ as current_version
from homeassistant.core import HomeAssistant

from custom_components.elasticsearch.system_info import SystemInfo, SystemInfoResult


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


class Test_Unit_Tests:
    """Unit tests for system_info.py."""

    async def test_async_get_system_info_hassio(self, hass: HomeAssistant):
        """Verify system information is retrieved correctly."""
        sys_info = SystemInfo(hass)

        # Mock the return value of _get_system_info_from_hass
        mock_system_info = {
            "version": "1.0.0",
            "arch": "x86_64",
            "os_name": "Linux",
            "os_version": "4.19.0-14-amd64",
            "hassio": True,
        }
        sys_info._get_system_info = mock.AsyncMock(return_value=mock_system_info)
        sys_info._get_host_info = mock.MagicMock(return_value={"hostname": "my-host"})

        result = await sys_info.async_get_system_info()

        assert isinstance(result, SystemInfoResult)
        assert result.version == "1.0.0"
        assert result.arch == "x86_64"
        assert result.os_name == "Linux"
        assert result.os_version == "4.19.0-14-amd64"
        assert result.hostname == "my-host"

    async def test_get_system_info(self, hass: HomeAssistant):
        """Verify system information is retrieved correctly from HASS."""

        mock_system_info = {
            "version": "1.0.0",
            "arch": "x86_64",
            "os_name": "Linux",
            "os_version": "4.19.0-14-amd64",
        }

        with mock.patch(
            "homeassistant.helpers.system_info.async_get_system_info",
            return_value=mock_system_info,
        ):
            sys_info = SystemInfo(hass)
            result = await sys_info._get_system_info()

            assert result == mock_system_info

    async def test_get_system_info_exception(self, hass: HomeAssistant):
        """Verify an exception is raised when system information cannot be retrieved from HASS."""
        sys_info = SystemInfo(hass)

        with (
            mock.patch(
                "homeassistant.helpers.system_info.async_get_system_info",
                side_effect=Exception,
            ),
            pytest.raises(ValueError),
        ):
            await sys_info._get_system_info()

"""Test Entity Details."""

from unittest import mock

import pytest
from homeassistant.const import __version__ as current_version
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.elasticsearch.system_info import SystemInfo, SystemInfoResult


@pytest.mark.asyncio
async def test_success(hass: HomeAssistant):
    """Verify system info can be returned."""
    # Test adapted from:
    # https://github.com/home-assistant/core/blob/cec617cfbb86a57bebd80d1e1492dfe0ec7dc11d/tests/helpers/test_system_info.py#L23

    sys_info = SystemInfo(hass)
    result = await sys_info.async_get_system_info()
    assert isinstance(result, SystemInfoResult)
    assert result.version == current_version
    assert result.arch is not None
    assert result.os_name is not None
    assert result.os_version is not None
    assert result.hostname is not None



@pytest.mark.asyncio
async def test_error_handling(hass: HomeAssistant):
    """Verify unexpected errors return empty object."""

    def mock_get_system_info():
        raise HomeAssistantError("Something bad happened")

    with mock.patch(
        "homeassistant.helpers.system_info.async_get_system_info",
        side_effect=mock_get_system_info,
    ):
        sys_info = SystemInfo(hass)
        assert await sys_info.async_get_system_info() is None

"""Test Entity Details."""

import json
from unittest import mock

import pytest
from homeassistant.const import __version__ as current_version
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.typing import HomeAssistantType

from custom_components.elasticsearch.system_info import SystemInfo


@pytest.mark.asyncio
async def test_success(hass: HomeAssistantType):
    """Verify system info can be returned."""
    # Test adapted from:
    # https://github.com/home-assistant/core/blob/cec617cfbb86a57bebd80d1e1492dfe0ec7dc11d/tests/helpers/test_system_info.py#L23

    sys_info = SystemInfo(hass)
    result = await sys_info.async_get_system_info()
    assert isinstance(result, dict)
    assert result["version"] == current_version
    assert result["user"] is not None
    assert json.dumps(result) is not None

@pytest.mark.asyncio
async def test_error_handling(hass: HomeAssistantType):
    """Verify unexpected errors return empty object."""

    def mock_get_system_info():
        raise HomeAssistantError("Something bad happened")

    with mock.patch('homeassistant.helpers.system_info.async_get_system_info', side_effect=mock_get_system_info):
        sys_info = SystemInfo(hass)
        assert await sys_info.async_get_system_info() == {}

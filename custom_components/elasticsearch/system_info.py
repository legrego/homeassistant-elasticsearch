"""Retrieve system information."""

import socket
from dataclasses import dataclass

from homeassistant.components.hassio import get_host_info
from homeassistant.core import HomeAssistant

from .logger import LOGGER


@dataclass
class SystemInfoResult:
    """System info for use in documents published to Elasticsearch."""

    version: str
    arch: str
    os_name: str
    os_version: str
    hostname: str | None


class SystemInfo:
    """Retrieve system information."""

    def __init__(self, hass: HomeAssistant) -> None:
        """System Info init."""
        self._hass: HomeAssistant = hass

    async def async_get_system_info(self) -> SystemInfoResult | None:
        """Retrieve system information from HASS."""
        try:
            system_info = await self._hass.helpers.system_info.async_get_system_info()

            # see homeassistant/helpers/system_info.py in main home-assistant repo
            if system_info.get("hassio"):
                hostname = get_host_info(self._hass).get("hostname", None)
            else:
                hostname = socket.gethostname()

            return SystemInfoResult(
                version=system_info.get("version"),
                arch=system_info.get("arch"),
                os_name=system_info.get("os_name"),
                os_version=system_info.get("os_version"),
                hostname=hostname,
            )
        except Exception as err:  # pylint disable=broad-exception-caught
            LOGGER.exception("Error retrieving system info: %s", err)
            return None

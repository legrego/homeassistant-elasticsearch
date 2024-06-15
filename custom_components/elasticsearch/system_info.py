"""Retrieve system information."""

import socket
from dataclasses import dataclass

from homeassistant.components.hassio.coordinator import get_host_info
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

    async def _get_system_info(self) -> dict:
        try:
            return await self._hass.helpers.system_info.async_get_system_info()
        except Exception as err:
            msg = "Unknown error retrieving system info"
            LOGGER.exception(msg)
            raise ValueError(msg) from err

    def _get_host_info(self) -> dict | None:
        """Retrieve host information from HASS."""
        return get_host_info(self._hass)

    async def async_get_system_info(self) -> SystemInfoResult | None:
        """Retrieve system information from HASS."""
        system_info = await self._get_system_info()

        host_info = self._get_host_info()

        hostname = None

        if host_info is not None and system_info["hassio"] is True:
            hostname = host_info.get("hostname", None)
        else:
            hostname = socket.gethostname()

        return SystemInfoResult(
            version=system_info["version"],
            arch=system_info["arch"],
            os_name=system_info["os_name"],
            os_version=system_info["os_version"],
            hostname=hostname,
        )

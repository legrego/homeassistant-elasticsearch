"""Retrieve system information."""

import socket
from dataclasses import dataclass

from homeassistant.components.hassio.coordinator import get_host_info
from homeassistant.core import HomeAssistant
from homeassistant.helpers.system_info import async_get_system_info

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
            return await async_get_system_info(self._hass)
        except Exception as err:  # noqa: BLE001
            msg = "Unknown error retrieving system info"
            LOGGER.exception(msg)
            raise ValueError(msg) from err

    def _get_host_info(self) -> dict | None:
        """Retrieve host information from HASS.

        Only expected to succeed when running under Hassio, and even then the
        Supervisor coordinator may not have completed its first refresh yet.
        Errors are caught and swallowed so callers always get None instead.
        """
        try:
            return get_host_info(self._hass)
        except Exception:  # noqa: BLE001
            LOGGER.debug("Unable to retrieve host info from the Hassio supervisor", exc_info=True)
            return None

    async def async_get_system_info(self) -> SystemInfoResult | None:
        """Retrieve system information from HASS."""
        system_info = await self._get_system_info()

        hostname = None

        if system_info["hassio"] is True:
            host_info = self._get_host_info()
            if host_info is not None:
                hostname = host_info.get("hostname", None)

        if hostname is None:
            hostname = socket.gethostname()

        return SystemInfoResult(
            version=system_info["version"],
            arch=system_info["arch"],
            os_name=system_info["os_name"],
            os_version=system_info["os_version"],
            hostname=hostname,
        )

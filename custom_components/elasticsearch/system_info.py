"""Retrieve system information."""
import socket

from homeassistant.core import HomeAssistant

from .logger import LOGGER


class SystemInfo:
    """Retrieve system information."""

    def __init__(self, hass: HomeAssistant):
        """System Info init."""
        self._hass: HomeAssistant = hass

    async def async_get_system_info(self):
        """Retrieve system information from HASS."""
        try:
            system_info = await self._hass.helpers.system_info.async_get_system_info()

            # see homeassistant/helpers/system_info.py in main home-assistant repo
            if self._hass.components.hassio.is_hassio():
                hostname = self._hass.components.hassio.get_host_info().get("hostname", "UNKNOWN")
            else:
                hostname = socket.gethostname()

            system_info["hostname"] = hostname
            return system_info
        except Exception as err:  # pylint disable=broad-exception-caught
            LOGGER.exception("Error retrieving system info: %s", err)
            return {}

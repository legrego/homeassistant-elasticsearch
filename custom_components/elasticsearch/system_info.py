"""Retrieve system information."""
import socket

from homeassistant.helpers.typing import HomeAssistantType

from .logger import LOGGER


async def async_get_system_info(hass: HomeAssistantType):
    """Retrieve system information from HASS."""
    try:
        system_info = await hass.helpers.system_info.async_get_system_info()

        # see homeassistant/helpers/system_info.py in main home-assistant repo
        if hass.components.hassio.is_hassio():
            hostname = hass.components.hassio.get_host_info().get("hostname", "UNKNOWN")
        else:
            hostname = socket.gethostname()

        system_info["hostname"] = hostname
        return system_info
    except Exception as err:  # pylint disable=broad-exception-caught
        LOGGER.exception("Error retrieving system info: %s", err)
        return {}

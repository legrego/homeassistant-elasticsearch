"""Diagnostics for the Elasticsearch integration."""

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_API_KEY,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant

CONFIG_TO_REDACT = {CONF_API_KEY, CONF_PASSWORD, CONF_URL, CONF_USERNAME}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, any]:
    """Return diagnostics for the config entry."""

    return {
        "data": async_redact_data(entry.data, CONFIG_TO_REDACT),
        "options": async_redact_data(entry.options, CONFIG_TO_REDACT),
    }

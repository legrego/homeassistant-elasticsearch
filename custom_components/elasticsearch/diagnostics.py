"""Diagnostics for the Elasticsearch integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import (
    CONF_API_KEY,
    CONF_PASSWORD,
    CONF_URL,
    CONF_USERNAME,
)
from yarl import URL

from custom_components.elasticsearch.es_integration import ElasticIntegration

if TYPE_CHECKING:  # pragma: no cover
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

CONFIG_TO_REDACT = {CONF_API_KEY, CONF_PASSWORD, CONF_USERNAME}


def redact_url(url: str) -> str:
    """Redact credentials embedded in a URL, such as `https://user:pass@host`."""
    try:
        parsed = URL(url)
    except ValueError:
        return REDACTED

    if parsed.user is None and parsed.password is None:
        return url

    return str(parsed.with_user(REDACTED).with_password(REDACTED if parsed.password is not None else None))


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:  # noqa: ARG001
    """Return diagnostics for the config entry."""

    data = async_redact_data(entry.data, CONFIG_TO_REDACT)
    if isinstance(data.get(CONF_URL), str):
        data[CONF_URL] = redact_url(data[CONF_URL])

    diagnostics: dict[str, Any] = {
        "data": data,
        "options": async_redact_data(entry.options, CONFIG_TO_REDACT),
    }

    runtime_data = getattr(entry, "runtime_data", None)
    if isinstance(runtime_data, ElasticIntegration):
        diagnostics["runtime"] = runtime_data.diagnostics()

    return diagnostics

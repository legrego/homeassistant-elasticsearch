"""Utilities."""

from homeassistant.config_entries import ConfigEntry


def get_merged_config(config_entry: ConfigEntry) -> dict:
    """Merge config from setup & options into a single dict."""

    return {**config_entry.data, **config_entry.options}

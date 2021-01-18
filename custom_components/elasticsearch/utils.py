""" Utilities """
from homeassistant.config_entries import ConfigEntry


def get_merged_config(config_entry: ConfigEntry) -> dict:
    """ Merges config from setup & options into a single dict """

    conf = {**config_entry.data, **config_entry.options}
    return conf

"""
Support for sending event data to an Elasticsearch cluster
"""

from copy import deepcopy

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_ALIAS,
    CONF_DOMAINS,
    CONF_ENTITIES,
    CONF_EXCLUDE,
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.helpers.typing import HomeAssistantType

from .const import (
    CONF_EXCLUDED_DOMAINS,
    CONF_EXCLUDED_ENTITIES,
    CONF_HEALTH_SENSOR_ENABLED,
    CONF_ILM_DELETE_AFTER,
    CONF_ILM_ENABLED,
    CONF_ILM_MAX_SIZE,
    CONF_ILM_POLICY_NAME,
    CONF_INDEX_FORMAT,
    CONF_ONLY_PUBLISH_CHANGED,
    CONF_PUBLISH_ENABLED,
    CONF_PUBLISH_FREQUENCY,
    CONF_SSL_CA_PATH,
    CONF_TAGS,
    DOMAIN,
    ONE_MINUTE,
)
from .es_integration import ElasticIntegration
from .logger import LOGGER

# Legacy (yml-based) configuration schema
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_URL): cv.url,
                vol.Optional(CONF_USERNAME): cv.string,
                vol.Optional(CONF_PASSWORD): cv.string,
                vol.Optional(CONF_TIMEOUT, default=30): cv.positive_int,
                vol.Optional(CONF_PUBLISH_ENABLED, default=True): cv.boolean,
                vol.Optional(CONF_HEALTH_SENSOR_ENABLED, default=True): cv.boolean,
                vol.Optional(CONF_PASSWORD): cv.string,
                vol.Optional(CONF_INDEX_FORMAT, default="hass-events"): cv.string,
                vol.Optional(CONF_ALIAS, default="active-hass-index"): cv.string,
                vol.Optional(
                    CONF_PUBLISH_FREQUENCY, default=ONE_MINUTE
                ): cv.positive_int,
                vol.Optional(CONF_ONLY_PUBLISH_CHANGED, default=False): cv.boolean,
                vol.Optional(CONF_ILM_ENABLED, default=True): cv.boolean,
                vol.Optional(CONF_ILM_POLICY_NAME, default="home-assistant"): cv.string,
                vol.Optional(CONF_ILM_MAX_SIZE, default="30gb"): cv.string,
                vol.Optional(CONF_ILM_DELETE_AFTER, default="365d"): cv.string,
                vol.Optional(CONF_VERIFY_SSL, default=True): cv.boolean,
                vol.Optional(CONF_SSL_CA_PATH): cv.string,
                vol.Optional(CONF_TAGS, default=["hass"]): vol.All(
                    cv.ensure_list, [cv.string]
                ),
                vol.Optional(CONF_EXCLUDED_DOMAINS, default=[]): vol.All(
                    cv.ensure_list, [cv.string]
                ),
                vol.Optional(CONF_EXCLUDED_ENTITIES, default=[]): cv.entity_ids,
                vol.Optional(CONF_EXCLUDE, default={}): vol.Schema(
                    {
                        vol.Optional(CONF_DOMAINS, default=[]): vol.All(
                            cv.ensure_list, [cv.string]
                        ),
                        vol.Optional(CONF_ENTITIES, default=[]): cv.entity_ids,
                    }
                ),
            }
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistantType, config):
    """Set up Elasticsearch integration via legacy yml-based setup."""
    if DOMAIN not in config:
        return True

    conf = config[DOMAIN]

    # Migrate legacy yml-based config to a flattened structure.
    excluded = conf.get(CONF_EXCLUDE, {})
    conf[CONF_EXCLUDED_DOMAINS] = excluded.get(CONF_DOMAINS, [])
    conf[CONF_EXCLUDED_ENTITIES] = excluded.get(CONF_ENTITIES, [])

    # Run legacy yml-based config through the config flow.
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=deepcopy(conf)
        )
    )

    return True


async def async_setup_entry(hass: HomeAssistantType, config_entry: ConfigEntry):
    """ Setup integration via config flow. """

    LOGGER.debug("Setting up integtation")
    init = await _async_init_integration(hass, config_entry)
    config_entry.add_update_listener(async_config_entry_updated)
    return init


async def async_unload_entry(hass: HomeAssistantType, config_entry: ConfigEntry):
    """ Teardown integration. """
    existing_instance = hass.data.get(DOMAIN)
    if isinstance(existing_instance, ElasticIntegration):
        LOGGER.debug("Shutting down previous integration")
        await existing_instance.async_shutdown(config_entry)
        hass.data[DOMAIN] = None
    return True


async def async_config_entry_updated(
    hass: HomeAssistantType, config_entry: ConfigEntry
):
    """ Respond to config changes. """
    LOGGER.debug("Configuration change detected")
    return await _async_init_integration(hass, config_entry)


async def _async_init_integration(hass: HomeAssistantType, config_entry: ConfigEntry):
    """ Initialize integration. """
    await async_unload_entry(hass, config_entry)

    integration = ElasticIntegration(hass, config_entry)
    await integration.async_init()

    hass.data[DOMAIN] = integration

    return True

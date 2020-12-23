"""
Support for sending event data to an Elasticsearch cluster
"""
import voluptuous as vol
from copy import deepcopy

from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import (
    CONF_URL,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_ALIAS,
    CONF_EXCLUDE,
    CONF_DOMAINS,
    CONF_ENTITIES,
    CONF_VERIFY_SSL,
    CONF_TIMEOUT,
)
import homeassistant.helpers.config_validation as cv

from .es_doc_publisher import DocumentPublisher
from .es_index_manager import IndexManager
from .es_gateway import ElasticsearchGateway

from .const import (
    DOMAIN,
    CONF_PUBLISH_ENABLED,
    CONF_HEALTH_SENSOR_ENABLED,
    CONF_INDEX_FORMAT,
    CONF_PUBLISH_FREQUENCY,
    CONF_EXCLUDED_DOMAINS,
    CONF_EXCLUDED_ENTITIES,
    ONE_MINUTE,
    CONF_ONLY_PUBLISH_CHANGED,
    CONF_ILM_ENABLED,
    CONF_ILM_POLICY_NAME,
    CONF_ILM_MAX_SIZE,
    CONF_ILM_DELETE_AFTER,
    CONF_SSL_CA_PATH,
    CONF_TAGS,
)

from .logger import LOGGER

ELASTIC_COMPONENTS = ["sensor"]

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


async def async_setup(hass, config):
    """Set up Elasticsearch integration."""
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


async def async_setup_entry(hass, config_entry):
    LOGGER.debug("Setting up integtation")
    init = await async_init_integration(hass, config_entry)
    config_entry.add_update_listener(async_config_entry_updated)
    return init


async def async_unload_entry(hass, config_entry):
    existing_instance = hass.data.get(DOMAIN)
    if isinstance(existing_instance, ElasticIntegration):
        LOGGER.debug("Shutting down previous integration")
        await existing_instance.async_shutdown()
        hass.data[DOMAIN] = None
    return True


async def async_config_entry_updated(hass, config_entry):
    LOGGER.debug("Configuration change detected")
    return await async_init_integration(hass, config_entry)


async def async_init_integration(hass, config_entry):
    await async_unload_entry(hass, config_entry)

    integration = ElasticIntegration(hass, config_entry)
    await integration.async_init()

    hass.data[DOMAIN] = integration

    return True


class ElasticIntegration:
    def __init__(self, hass, config_entry):
        conf = {**config_entry.data, **config_entry.options}
        self.hass = hass
        self.gateway = ElasticsearchGateway(conf)
        self.index_manager = IndexManager(hass, conf, self.gateway)
        self.publisher = DocumentPublisher(conf, self.gateway, self.index_manager, hass)

    async def async_init(self):
        system_info = await self.hass.helpers.system_info.async_get_system_info()
        await self.gateway.async_init()
        await self.index_manager.async_setup()
        await self.publisher.async_init(system_info)

    async def async_shutdown(self):
        await self.publisher.async_stop_publisher()
        await self.gateway.async_stop_gateway()

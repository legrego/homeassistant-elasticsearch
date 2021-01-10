"""
Support for sending event data to an Elasticsearch cluster
"""
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
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
    EVENT_STATE_CHANGED,
)
from homeassistant.helpers import discovery

from .const import (
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
from .es_doc_publisher import DocumentPublisher
from .es_gateway import ElasticsearchGateway
from .es_index_manager import IndexManager
from .logger import LOGGER

ELASTIC_COMPONENTS = ["sensor"]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_URL): cv.url,
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
    """Setup the Elasticsearch component."""
    conf = config[DOMAIN]

    hass.data[DOMAIN] = {}

    LOGGER.debug("Creating ES gateway")
    gateway = ElasticsearchGateway(hass, conf)
    await gateway.async_init()
    hass.data[DOMAIN]["gateway"] = gateway

    hass.data[DOMAIN][CONF_PUBLISH_ENABLED] = conf.get(CONF_PUBLISH_ENABLED)
    hass.data[DOMAIN][CONF_HEALTH_SENSOR_ENABLED] = conf.get(CONF_HEALTH_SENSOR_ENABLED)

    if conf.get(CONF_PUBLISH_ENABLED):
        LOGGER.debug("Creating ES index manager")
        index_manager = IndexManager(hass, conf, gateway)
        await index_manager.async_setup()
        hass.data[DOMAIN]["index_manager"] = index_manager

        LOGGER.debug("Creating document publisher")
        system_info = await hass.helpers.system_info.async_get_system_info()
        publisher = DocumentPublisher(conf, gateway, index_manager, hass, system_info)
        hass.data[DOMAIN]["publisher"] = publisher

        def elastic_event_listener(event):
            """Listen for new messages on the bus and queue them for send."""
            state = event.data.get("new_state")
            if state is None:
                return

            publisher.enqueue_state({"state": state, "event": event})

            return

        hass.bus.async_listen(EVENT_STATE_CHANGED, elastic_event_listener)

    for component in ELASTIC_COMPONENTS:
        discovery.load_platform(hass, component, DOMAIN, {}, config)

    LOGGER.info("Elastic component fully initialized")
    return True

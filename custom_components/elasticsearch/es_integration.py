"""Support for sending event data to an Elasticsearch cluster."""


from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import HomeAssistantType
from custom_components.elasticsearch.errors import convert_es_error

from custom_components.elasticsearch.logger import LOGGER

from .es_doc_publisher import DocumentPublisher
from .es_gateway import ElasticsearchGateway
from .es_index_manager import IndexManager
from .utils import get_merged_config


class ElasticIntegration:
    """Integration for publishing entity state change events to Elasticsearch."""

    def __init__(self, hass: HomeAssistantType, config_entry: ConfigEntry):
        """Integration initialization."""
        conf = get_merged_config(config_entry)
        self.hass = hass
        self.gateway = ElasticsearchGateway(conf)
        self.index_manager = IndexManager(hass, conf, self.gateway)
        self.publisher = DocumentPublisher(conf, self.gateway, self.index_manager, hass)
        self.config_entry = config_entry

    # TODO investivage hepers.event.async_call_later()
    async def async_init(self):
        """Async init procedure."""
        try:
            await self.gateway.async_init()
            await self.index_manager.async_setup()
            await self.publisher.async_init()
        except Exception as err:
            raise convert_es_error(err) from err


    async def async_shutdown(self, config_entry: ConfigEntry): # pylint disable=unused-argument
        """Async shutdown procedure."""
        LOGGER.debug("async_shutdown: starting shutdown")
        self.publisher.stop_publisher()
        await self.gateway.async_stop_gateway()
        LOGGER.debug("async_shutdown: shutdown complete")
        return True

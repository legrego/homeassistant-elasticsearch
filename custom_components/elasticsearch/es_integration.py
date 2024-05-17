"""Support for sending event data to an Elasticsearch cluster."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.elasticsearch.errors import convert_es_error
from custom_components.elasticsearch.es_privilege_check import ESPrivilegeCheck
from custom_components.elasticsearch.logger import LOGGER

from .es_doc_publisher import DocumentPublisher
from .es_gateway import Elasticsearch7Gateway
from .es_index_manager import IndexManager


class ElasticIntegration:
    """Integration for publishing entity state change events to Elasticsearch."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        """Integration initialization."""

        self._hass = hass

        # Extract parameters from the config_entry and initialize components
        # Starting with the Gateway
        gateway_parameters = {
            "url": config_entry.data.get("url"),
            "username": config_entry.data.get("username"),
            "password": config_entry.data.get("password"),
            "api_key": config_entry.data.get("api_key"),
            "verify_ssl": config_entry.data.get("verify_ssl"),
            "ca_certs": config_entry.data.get("ca_certs"),
            "timeout": config_entry.data.get("timeout"),
            # minimum_privileges = config_entry.data.get("timeout"),
        }

        self._gateway = Elasticsearch7Gateway(hass=hass, **gateway_parameters)

        self._index_manager = IndexManager(hass, config_entry=config_entry, gateway=self.gateway)
        self._publisher = DocumentPublisher(config_entry=config_entry, gateway=self.gateway, hass=self.hass)
        self._config_entry = config_entry

    # TODO investigate helpers.event.async_call_later()
    async def async_init(self):
        """Async init procedure."""

        try:
            await self._gateway.async_init()
            await self.index_manager.async_setup()
            await self.publisher.async_init()
        except Exception as err:
            try:
                self.publisher.stop_publisher()
                await self.gateway.close()
            except Exception as shutdown_err:
                LOGGER.error(
                    "Error shutting down gateway following failed initialization",
                    shutdown_err,
                )

            raise convert_es_error("Failed to initialize integration", err) from err

    async def async_shutdown(self, config_entry: ConfigEntry):  # pylint disable=unused-argument
        """Async shutdown procedure."""
        LOGGER.debug("async_shutdown: starting shutdown")
        self.publisher.stop_publisher()
        await self.gateway.close()
        LOGGER.debug("async_shutdown: shutdown complete")
        return True

"""Support for sending event data to an Elasticsearch cluster."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.elasticsearch.errors import convert_es_error
from custom_components.elasticsearch.logger import LOGGER

from .const import ES_CHECK_PERMISSIONS_DATASTREAM
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
        self._config_entry = config_entry

        gateway_parameters = self.build_gateway_parameters(config_entry)
        self._gateway = Elasticsearch7Gateway(**gateway_parameters)

        index_parameters = self.build_index_manager_parameters(config_entry)
        self._index_manager = IndexManager(**index_parameters)

        publisher_parameters = self.build_publisher_parameters(config_entry)
        self._publisher = DocumentPublisher(**publisher_parameters)

    # TODO investigate helpers.event.async_call_later()
    async def async_init(self):
        """Async init procedure."""

        try:
            await self._gateway.async_init()
            await self._index_manager.async_setup()
            await self._publisher.async_init()
        except Exception as err:
            try:
                self._publisher.stop_publisher()
                await self._gateway.stop()
            except Exception as shutdown_err:
                LOGGER.error(
                    "Error shutting down gateway following failed initialization",
                    shutdown_err,
                )

            raise convert_es_error("Failed to initialize integration", err) from err

    async def async_shutdown(self, config_entry: ConfigEntry):  # pylint disable=unused-argument
        """Async shutdown procedure."""
        LOGGER.debug("async_shutdown: starting shutdown")
        self._publisher.stop_publisher()
        await self._gateway.stop()
        LOGGER.debug("async_shutdown: shutdown complete")
        return True

    def build_gateway_parameters(self, config_entry):
        """Build the parameters for the Elasticsearch gateway."""
        return {
            "hass": self._hass,
            "url": config_entry.data.get("url"),
            "username": config_entry.data.get("username"),
            "password": config_entry.data.get("password"),
            "api_key": config_entry.data.get("api_key"),
            "verify_certs": config_entry.data.get("verify_ssl"),
            "ca_certs": config_entry.data.get("ca_certs"),
            "request_timeout": config_entry.data.get("timeout"),
            "minimum_privileges": ES_CHECK_PERMISSIONS_DATASTREAM,
            "use_connection_monitor": config_entry.data.get("use_connection_monitor", True),
        }

    def build_index_manager_parameters(self, config_entry):
        """Build the parameters for the Elasticsearch index manager."""
        return {
            "hass": self._hass,
            "config_entry": config_entry,
            "gateway": self._gateway,
        }

    def build_publisher_parameters(self, config_entry):
        """Build the parameters for the Elasticsearch document publisher."""
        return {"hass": self._hass, "config_entry": config_entry, "gateway": self._gateway}

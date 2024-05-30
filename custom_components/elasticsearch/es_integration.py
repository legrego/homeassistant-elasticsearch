"""Support for sending event data to an Elasticsearch cluster."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.elasticsearch.errors import convert_es_error

from .const import ES_CHECK_PERMISSIONS_DATASTREAM
from .es_doc_publisher import DocumentPublisher
from .es_gateway import Elasticsearch7Gateway
from .es_index_manager import IndexManager
from .logger import LOGGER as BASE_LOGGER


class ElasticIntegration:
    """Integration for publishing entity state change events to Elasticsearch."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, log=BASE_LOGGER) -> None:
        """Integration initialization."""

        self._hass = hass

        self._logger = log
        self._config_entry = config_entry

        self._logger.info("Initializing integration.")

        gateway_parameters = self.build_gateway_parameters(self._config_entry)
        self._gateway = Elasticsearch7Gateway(log=self._logger, **gateway_parameters)

        index_parameters = self.build_index_manager_parameters(self._config_entry)
        self._index_manager = IndexManager(log=self._logger, **index_parameters)

        publisher_parameters = self.build_publisher_parameters(self._config_entry)
        self._publisher = DocumentPublisher(log=self._logger, **publisher_parameters)

    # TODO investigate helpers.event.async_call_later()
    async def async_init(self) -> None:
        """Async init procedure."""

        # Include the title of the config_entry we are running under

        try:
            await self._gateway.async_init()
            self._gateway.connection_monitor.start(config_entry=self._config_entry)

            await self._index_manager.async_setup()
            await self._publisher.async_init()

        except Exception as err:
            try:
                self._publisher.stop_publisher()
                await self._gateway.stop()
            except Exception as shutdown_err:
                self._logger.exception(
                    "Error shutting down gateway following failed initialization",
                    shutdown_err,
                )

            msg = "Failed to initialize integration"
            raise convert_es_error(msg, err) from err

    async def async_shutdown(self, config_entry: ConfigEntry) -> bool:  # pylint disable=unused-argument
        """Async shutdown procedure."""
        self._logger.debug("async_shutdown: starting shutdown")
        self._publisher.stop_publisher()
        await self._gateway.stop()
        self._logger.debug("async_shutdown: shutdown complete")
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

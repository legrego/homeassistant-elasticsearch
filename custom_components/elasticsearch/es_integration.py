"""Support for sending event data to an Elasticsearch cluster."""

from logging import Logger

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.elasticsearch.es_publish_pipeline import Pipeline, PipelineSettings

from .es_gateway import Elasticsearch7Gateway
from .es_index_manager import IndexManager
from .logger import LOGGER as BASE_LOGGER
from .logger import async_log_enter_exit_debug, async_log_enter_exit_info, log_enter_exit_info


class ElasticIntegration:
    """Integration for publishing entity state change events to Elasticsearch."""

    @log_enter_exit_info
    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, log: Logger = BASE_LOGGER) -> None:
        """Integration initialization."""

        self._hass = hass

        self._logger = log
        self._config_entry = config_entry

        self._logger.info("Initializing integration.")

        gateway_parameters = Elasticsearch7Gateway.build_gateway_parameters(
            hass,
            config_entry=self._config_entry,
        )
        self._gateway = Elasticsearch7Gateway(log=self._logger, **gateway_parameters)

        manager_parameters = self.build_pipeline_manager_parameters(config_entry=self._config_entry)
        self._pipeline_manager = Pipeline.Manager(log=self._logger, **manager_parameters)

        index_parameters = self.build_index_manager_parameters()
        self._index_manager = IndexManager(log=self._logger, **index_parameters)

    @async_log_enter_exit_debug
    async def async_init(self) -> None:
        """Async init procedure."""

        try:
            await self._gateway.async_init(config_entry=self._config_entry)
            await self._index_manager.async_init()
            await self._pipeline_manager.async_init(config_entry=self._config_entry)

        except Exception:
            self._logger.exception("Error initializing integration")
            await self.async_shutdown()

            raise

    @async_log_enter_exit_info
    async def async_shutdown(self) -> bool:  # pylint disable=unused-argument
        """Async shutdown procedure."""
        try:
            await self._gateway.stop()
        except Exception:
            self._logger.exception("Error stopping gateway")

        try:
            self._pipeline_manager.stop()
        except Exception:
            self._logger.exception("Error stopping pipeline manager")

        try:
            self._index_manager.stop()
        except Exception:
            self._logger.exception("Error stopping index manager")

        return True

    def build_pipeline_manager_parameters(self, config_entry: ConfigEntry) -> dict:
        """Build the parameters for the Elasticsearch pipeline manager."""

        if config_entry.options is None:
            msg = "Config entry options are required for the pipeline manager."
            raise ValueError(msg)

        settings = PipelineSettings(
            included_domains=config_entry.options["included_domains"],
            included_entities=config_entry.options["included_entities"],
            excluded_domains=config_entry.options["excluded_domains"],
            excluded_entities=config_entry.options["excluded_entities"],
            polling_frequency=config_entry.options["polling_frequency"],
            change_detection_type=config_entry.options["change_detection_type"],
            publish_frequency=config_entry.options["publish_frequency"],
        )

        return {"hass": self._hass, "gateway": self._gateway, "settings": settings}

    def build_index_manager_parameters(self) -> dict:
        """Build the parameters for the Elasticsearch index manager."""
        return {
            "hass": self._hass,
            "gateway": self._gateway,
        }

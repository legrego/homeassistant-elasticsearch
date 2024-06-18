"""Support for sending event data to an Elasticsearch cluster."""

from __future__ import annotations

from typing import TYPE_CHECKING

from elasticsearch.const import ES_CHECK_PERMISSIONS_DATASTREAM
from elasticsearch.errors import ESIntegrationException

from custom_components.elasticsearch.es_datastream_manager import IndexManager
from custom_components.elasticsearch.es_gateway import Elasticsearch7Gateway
from custom_components.elasticsearch.es_publish_pipeline import Pipeline, PipelineSettings
from custom_components.elasticsearch.logger import LOGGER as BASE_LOGGER
from custom_components.elasticsearch.logger import async_log_enter_exit_debug, log_enter_exit_debug

if TYPE_CHECKING:
    from logging import Logger
    from typing import Any

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from custom_components.elasticsearch.es_gateway import Elasticsearch7Gateway


class ElasticIntegration:
    """Integration for publishing entity state change events to Elasticsearch."""

    @log_enter_exit_debug
    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, log: Logger = BASE_LOGGER) -> None:
        """Integration initialization."""

        self._hass = hass

        self._logger = log
        self._config_entry = config_entry

        self._logger.info("Initializing integration.")

        # Initialize our Elasticsearch Gateway
        gateway_parameters = self.build_gateway_parameters(
            hass,
            config_entry=self._config_entry,
        )
        self._gateway = Elasticsearch7Gateway(log=self._logger, **gateway_parameters)

        # Initialize our publishing pipeline
        manager_parameters = self.build_pipeline_manager_parameters(
            hass=self._hass, gateway=self._gateway, config_entry=self._config_entry
        )
        self._pipeline_manager = Pipeline.Manager(log=self._logger, **manager_parameters)

        # Initialize our Datastream manager
        index_parameters = self.build_datastream_manager_parameters(hass=self._hass, gateway=self._gateway)
        self._datastream_manager = IndexManager(log=self._logger, **index_parameters)

    @async_log_enter_exit_debug
    async def async_init(self) -> None:
        """Async init procedure."""

        try:
            await self._gateway.async_init(config_entry=self._config_entry)
            await self._datastream_manager.async_init()
            await self._pipeline_manager.async_init(config_entry=self._config_entry)

        except ESIntegrationException:
            self._logger.exception("Error initializing integration")
            await self.async_shutdown()

            raise

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
            self._datastream_manager.stop()
        except Exception:
            self._logger.exception("Error stopping index manager")

        return True

    @classmethod
    def build_gateway_parameters(
        cls,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        minimum_privileges: dict[str, Any] | None = ES_CHECK_PERMISSIONS_DATASTREAM,
    ) -> dict:
        """Build the parameters for the Elasticsearch gateway."""
        return {
            "hass": hass,
            "url": config_entry.data.get("url"),
            "username": config_entry.data.get("username"),
            "password": config_entry.data.get("password"),
            "api_key": config_entry.data.get("api_key"),
            "verify_certs": config_entry.data.get("verify_ssl"),
            "ca_certs": config_entry.data.get("ca_certs"),
            "request_timeout": config_entry.data.get("timeout"),
            "minimum_privileges": minimum_privileges,
            "use_connection_monitor": config_entry.data.get("use_connection_monitor", True),
        }

    @classmethod
    def build_pipeline_manager_parameters(cls, hass, gateway, config_entry: ConfigEntry) -> dict:
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

        return {"hass": hass, "gateway": gateway, "settings": settings}

    @classmethod
    def build_datastream_manager_parameters(cls, hass, gateway) -> dict:
        """Build the parameters for the Elasticsearch index manager."""
        return {
            "hass": hass,
            "gateway": gateway,
        }

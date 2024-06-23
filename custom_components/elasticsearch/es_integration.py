"""Support for sending event data to an Elasticsearch cluster."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.elasticsearch.const import ES_CHECK_PERMISSIONS_DATASTREAM
from custom_components.elasticsearch.errors import ESIntegrationException
from custom_components.elasticsearch.es_datastream_manager import DatastreamManager
from custom_components.elasticsearch.es_gateway_7 import Elasticsearch7Gateway, Gateway7Settings
from custom_components.elasticsearch.es_publish_pipeline import Pipeline, PipelineSettings
from custom_components.elasticsearch.logger import LOGGER as BASE_LOGGER
from custom_components.elasticsearch.logger import async_log_enter_exit_debug, log_enter_exit_debug

if TYPE_CHECKING:
    from logging import Logger
    from typing import Any

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


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
        gateway_settings: Gateway7Settings = self.build_gateway_parameters(
            config_entry=self._config_entry,
        )
        self._gateway = Elasticsearch7Gateway(log=self._logger, gateway_settings=gateway_settings)

        # Initialize our publishing pipeline
        manager_parameters = self.build_pipeline_manager_parameters(
            hass=self._hass, gateway=self._gateway, config_entry=self._config_entry
        )
        self._pipeline_manager = Pipeline.Manager(log=self._logger, **manager_parameters)

        # Initialize our Datastream manager
        self._datastream_manager = DatastreamManager(log=self._logger, gateway=self._gateway)

    @async_log_enter_exit_debug
    async def async_init(self) -> None:
        """Async init procedure."""

        try:
            await self._gateway.async_init()
            await self._datastream_manager.async_init()
            await self._pipeline_manager.async_init(config_entry=self._config_entry)

        except ESIntegrationException:
            self._logger.exception("Error initializing integration")
            await self.async_shutdown()

            raise

    async def async_shutdown(self) -> bool:
        """Async shutdown procedure."""
        try:
            self._pipeline_manager.stop()
            await self._gateway.stop()
        except Exception:
            self._logger.exception("Error stopping pipeline manager")

        return True

    @classmethod
    def build_gateway_parameters(
        cls,
        config_entry: ConfigEntry,
        minimum_privileges: dict[str, Any] | None = ES_CHECK_PERMISSIONS_DATASTREAM,
    ) -> Gateway7Settings:
        """Build the parameters for the Elasticsearch gateway."""
        return Gateway7Settings(
            url=config_entry.data["url"],
            username=config_entry.data.get("username"),
            password=config_entry.data.get("password"),
            api_key=config_entry.data.get("api_key"),
            verify_certs=config_entry.data.get("verify_ssl", False),
            ca_certs=config_entry.data.get("ca_certs"),
            request_timeout=config_entry.data.get("timeout", 30),
            minimum_privileges=minimum_privileges,
        )

    @classmethod
    def build_pipeline_manager_parameters(cls, hass, gateway, config_entry: ConfigEntry) -> dict:
        """Build the parameters for the Elasticsearch pipeline manager."""

        if config_entry.options is None:
            msg = "Config entry options are required for the pipeline manager."
            raise ValueError(msg)

        settings = PipelineSettings(
            polling_frequency=config_entry.options["polling_frequency"],
            publish_frequency=config_entry.options["publish_frequency"],
            change_detection_type=config_entry.options["change_detection_type"],
            include_targets=config_entry.options["include_targets"],
            exclude_targets=config_entry.options["exclude_targets"],
            included_areas=config_entry.options["targets_to_include"].get("area_id", []),
            excluded_areas=config_entry.options["targets_to_exclude"].get("area_id", []),
            included_labels=config_entry.options["targets_to_include"].get("labels_id", []),
            excluded_labels=config_entry.options["targets_to_exclude"].get("labels_id", []),
            included_devices=config_entry.options["targets_to_include"].get("devices_id", []),
            excluded_devices=config_entry.options["targets_to_exclude"].get("devices_id", []),
            included_entities=config_entry.options["targets_to_include"].get("entities_id", []),
            excluded_entities=config_entry.options["targets_to_exclude"].get("entities_id", []),
        )

        return {"hass": hass, "gateway": gateway, "settings": settings}

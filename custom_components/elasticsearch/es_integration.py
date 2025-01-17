"""Support for sending event data to an Elasticsearch cluster."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from homeassistant.const import (
    CONF_API_KEY,
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)

from custom_components.elasticsearch.const import (
    CONF_CHANGE_DETECTION_TYPE,
    CONF_DEBUG_ATTRIBUTE_FILTERING,
    CONF_EXCLUDE_TARGETS,
    CONF_INCLUDE_TARGETS,
    CONF_POLLING_FREQUENCY,
    CONF_PUBLISH_FREQUENCY,
    CONF_SSL_CA_PATH,
    CONF_SSL_VERIFY_HOSTNAME,
    CONF_TAGS,
    CONF_TARGETS_TO_EXCLUDE,
    CONF_TARGETS_TO_INCLUDE,
    ES_CHECK_PERMISSIONS_DATASTREAM,
)
from custom_components.elasticsearch.errors import ESIntegrationException
from custom_components.elasticsearch.es_datastream_manager import DatastreamManager
from custom_components.elasticsearch.es_gateway_8 import Elasticsearch8Gateway, Gateway8Settings
from custom_components.elasticsearch.es_publish_pipeline import Pipeline, PipelineSettings
from custom_components.elasticsearch.logger import LOGGER as BASE_LOGGER
from custom_components.elasticsearch.logger import async_log_enter_exit_debug, log_enter_exit_debug

if TYPE_CHECKING:  # pragma: no cover
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

        self._logger.info("Initializing integration components.")

        # Initialize our Elasticsearch Gateway
        gateway_settings: Gateway8Settings = self.build_gateway_parameters(
            config_entry=self._config_entry,
        )
        self._gateway = Elasticsearch8Gateway(log=self._logger, gateway_settings=gateway_settings)

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

        except ESIntegrationException as err:
            self._logger.error("Error initializing integration: %s", err)
            self._logger.debug("Error initializing integration", exc_info=True)
            await self.async_shutdown()

            raise

    async def async_shutdown(self) -> None:
        """Async shutdown procedure."""
        self._pipeline_manager.stop()
        await self._gateway.stop()

    @classmethod
    def build_gateway_parameters(
        cls,
        config_entry: ConfigEntry,
        minimum_privileges: MappingProxyType[str, Any] = ES_CHECK_PERMISSIONS_DATASTREAM,
    ) -> Gateway8Settings:
        """Build the parameters for the Elasticsearch gateway."""
        return Gateway8Settings(
            url=config_entry.data[CONF_URL],
            username=config_entry.data.get(CONF_USERNAME),
            password=config_entry.data.get(CONF_PASSWORD),
            api_key=config_entry.data.get(CONF_API_KEY),
            verify_certs=config_entry.data.get(CONF_VERIFY_SSL, False),
            verify_hostname=config_entry.data.get(CONF_SSL_VERIFY_HOSTNAME, False),
            ca_certs=config_entry.data.get(CONF_SSL_CA_PATH),
            request_timeout=config_entry.data.get(CONF_TIMEOUT, 30),
            minimum_privileges=minimum_privileges,
        )

    @classmethod
    def build_pipeline_manager_parameters(cls, hass, gateway, config_entry: ConfigEntry) -> dict:
        """Build the parameters for the Elasticsearch pipeline manager."""

        # Options are never none, but mypy doesn't know that
        assert config_entry.options is not None

        settings = PipelineSettings(
            polling_frequency=config_entry.options[CONF_POLLING_FREQUENCY],
            publish_frequency=config_entry.options[CONF_PUBLISH_FREQUENCY],
            change_detection_type=config_entry.options[CONF_CHANGE_DETECTION_TYPE],
            tags=config_entry.options[CONF_TAGS],
            debug_attribute_filtering=config_entry.options.get(CONF_DEBUG_ATTRIBUTE_FILTERING, False),
            include_targets=config_entry.options[CONF_INCLUDE_TARGETS],
            exclude_targets=config_entry.options[CONF_EXCLUDE_TARGETS],
            included_areas=config_entry.options[CONF_TARGETS_TO_INCLUDE].get("area_id", []),
            excluded_areas=config_entry.options[CONF_TARGETS_TO_EXCLUDE].get("area_id", []),
            included_labels=config_entry.options[CONF_TARGETS_TO_INCLUDE].get("label_id", []),
            excluded_labels=config_entry.options[CONF_TARGETS_TO_EXCLUDE].get("label_id", []),
            included_devices=config_entry.options[CONF_TARGETS_TO_INCLUDE].get("device_id", []),
            excluded_devices=config_entry.options[CONF_TARGETS_TO_EXCLUDE].get("device_id", []),
            included_entities=config_entry.options[CONF_TARGETS_TO_INCLUDE].get("entity_id", []),
            excluded_entities=config_entry.options[CONF_TARGETS_TO_EXCLUDE].get("entity_id", []),
        )

        return {"hass": hass, "gateway": gateway, "settings": settings}

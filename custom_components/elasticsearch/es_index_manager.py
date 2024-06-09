"""Index management facilities."""

import json
from logging import Logger
from pathlib import Path

from homeassistant.core import HomeAssistant

from custom_components.elasticsearch.es_gateway import ElasticsearchGateway

from .const import (
    DATASTREAM_METRICS_INDEX_TEMPLATE_NAME,
)
from .logger import LOGGER as BASE_LOGGER
from .logger import async_log_enter_exit, log_enter_exit


class IndexManager:
    """Index management facilities."""

    _logger = BASE_LOGGER

    def __init__(
        self,
        hass: HomeAssistant,
        gateway: ElasticsearchGateway,
        log: Logger = BASE_LOGGER,
    ) -> None:
        """Initialize index management."""

        self._logger = log

        self._hass = hass
        self._gateway: ElasticsearchGateway = gateway

    @log_enter_exit
    async def async_init(self) -> None:
        """Perform init for index management."""
        await self._create_index_template()

    @async_log_enter_exit
    async def _needs_index_template(self) -> bool:
        matching_templates = await self._gateway.get_index_template(
            name=DATASTREAM_METRICS_INDEX_TEMPLATE_NAME,
            ignore=[404],
        )

        return len(matching_templates.get("index_templates", [])) > 0

    @log_enter_exit
    async def _create_index_template(self) -> None:
        """Initialize any required datastream templates."""

        with (Path(__file__).parent / "datastreams" / "index_template.json").open(
            encoding="utf-8",
        ) as json_file:
            index_template = json.load(json_file)

        action = "Creating" if (await self._needs_index_template()) else "Updating"
        self._logger.info("%s index template for Home Assistant datastreams", action)

        await self._gateway.put_index_template(
            name=DATASTREAM_METRICS_INDEX_TEMPLATE_NAME,
            body=index_template,
        )

    @log_enter_exit
    def stop(self) -> None:
        """Stop the index manager."""

    def __del__(self) -> None:
        """Destructor."""
        self.stop()

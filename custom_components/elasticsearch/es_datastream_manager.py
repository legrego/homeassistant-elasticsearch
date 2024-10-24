"""Index management facilities."""

import json
from logging import Logger
from pathlib import Path

from custom_components.elasticsearch.datastreams.index_template import index_template_definition
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway

from .const import (
    DATASTREAM_METRICS_INDEX_TEMPLATE_NAME,
)
from .logger import LOGGER as BASE_LOGGER
from .logger import async_log_enter_exit_debug


class DatastreamManager:
    """Index management facilities."""

    _logger = BASE_LOGGER

    def __init__(
        self,
        gateway: ElasticsearchGateway,
        log: Logger = BASE_LOGGER,
    ) -> None:
        """Initialize index management."""

        self._logger = log

        self._gateway: ElasticsearchGateway = gateway

    @async_log_enter_exit_debug
    async def async_init(self) -> None:
        """Perform init for index management."""
        if await self._needs_index_template() or await self._needs_index_template_update():
            await self._create_index_template()

    @async_log_enter_exit_debug
    async def _needs_index_template(self) -> bool:
        matching_templates = await self._gateway.get_index_template(
            name=DATASTREAM_METRICS_INDEX_TEMPLATE_NAME,
            ignore=[404],
        )

        return len(matching_templates.get("index_templates", [])) == 0

    @async_log_enter_exit_debug
    async def _needs_index_template_update(self) -> bool:
        matching_templates = await self._gateway.get_index_template(
            name=DATASTREAM_METRICS_INDEX_TEMPLATE_NAME,
            ignore=[404],
        )

        matching_template = matching_templates.get("index_templates", [{}])[0]

        imported_version = matching_template["index_template"].get("version", 0)
        new_version = index_template_definition.get("version", 0)

        if imported_version != new_version:
            self._logger.info(
                "Update required from [%s} to [%s] for Home Assistant datastream index template",
                imported_version,
                new_version,
            )
            return True

        return False

    @async_log_enter_exit_debug
    async def _create_index_template(self) -> None:
        """Initialize any required datastream templates."""

        action = "Creating" if (await self._needs_index_template()) else "Updating"
        self._logger.info("%s index template for Home Assistant datastreams", action)

        await self._gateway.put_index_template(
            name=DATASTREAM_METRICS_INDEX_TEMPLATE_NAME,
            body=index_template_definition,
        )

        if action == "Updating":
            await self._rollover_ha_datastreams()

    @async_log_enter_exit_debug
    async def _rollover_ha_datastreams(self):
        """Rollover Home Assistant datastreams."""
        datastreams = await self._gateway.get_datastreams(datastream="metrics-homeassistant.*")

        for datastream in datastreams.get("data_streams", []):
            self._logger.info("Rolling over datastream [%s]", datastream["name"])
            await self._gateway.rollover_datastream(datastream=datastream["name"])

    async def _get_index_template_from_disk(self) -> dict:
        """Retrieve the index template from disk."""
        with (Path(__file__).parent / "datastreams" / "index_template.json").open(
            encoding="utf-8",
        ) as json_file:
            return json.load(json_file)

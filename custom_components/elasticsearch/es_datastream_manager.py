"""Manage Elasticsearch datastreams and index templates.

This class provides methods to initialize, install, and update
Elasticsearch index templates for Home Assistant datastreams.
"""

from logging import Logger

from custom_components.elasticsearch.datastreams.index_template import index_template_definition
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway

from .const import (
    DATASTREAM_METRICS_INDEX_TEMPLATE_NAME,
)
from .logger import LOGGER as BASE_LOGGER
from .logger import async_log_enter_exit_debug


class DatastreamManager:
    """Datastream manager."""

    _logger: Logger

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
        """Perform initializiation of required datastream primitives."""
        if await self._needs_index_template():
            await self._install_index_template()
        elif await self._needs_index_template_update():
            await self._update_index_template()

    @async_log_enter_exit_debug
    async def _needs_index_template(self) -> bool:
        """Check if the ES cluster needs the index template installed."""
        matching_templates = await self._gateway.get_index_template(
            name=DATASTREAM_METRICS_INDEX_TEMPLATE_NAME,
            ignore=[404],
        )

        return len(matching_templates.get("index_templates", [])) == 0

    @async_log_enter_exit_debug
    async def _needs_index_template_update(self) -> bool:
        """Check if the ES cluster needs the index template updated."""
        matching_templates = await self._gateway.get_index_template(
            name=DATASTREAM_METRICS_INDEX_TEMPLATE_NAME,
            ignore=[404],
        )

        matching_template = matching_templates.get("index_templates", [{}])[0]

        imported_version = matching_template["index_template"].get("version", 0)
        new_version = index_template_definition.get("version", 0)

        if imported_version != new_version:
            self._logger.info(
                "Update required from [%s] to [%s] for Home Assistant datastream index template",
                imported_version,
                new_version,
            )
            return True

        return False

    @async_log_enter_exit_debug
    async def _install_index_template(self) -> None:
        """Initialize any required datastream templates."""
        self._logger.info("Installing index template for Home Assistant datastreams")

        await self._gateway.put_index_template(
            name=DATASTREAM_METRICS_INDEX_TEMPLATE_NAME,
            body=index_template_definition,
        )

    @async_log_enter_exit_debug
    async def _update_index_template(self) -> None:
        """Update the specified index template and rollover the indices."""
        self._logger.info("Updating Index template and rolling over Home Assistant datastreams")

        await self._install_index_template()

        datastream_wildcard = index_template_definition["index_patterns"][0]

        # Rollover all Home Assistant datastreams to ensure we don't get mapping conflicts
        datastreams = await self._gateway.get_datastream(datastream=datastream_wildcard)

        for datastream in datastreams.get("data_streams", []):
            self._logger.info("Rolling over datastream [%s]", datastream["name"])
            await self._gateway.rollover_datastream(datastream=datastream["name"])

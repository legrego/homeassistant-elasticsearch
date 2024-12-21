"""Tests for the index manager class."""
# noqa: F401 # pylint: disable=redefined-outer-name

from unittest.mock import AsyncMock, patch

import pytest
from custom_components.elasticsearch.es_datastream_manager import DatastreamManager


@pytest.fixture
async def datastream_manager(initialized_gateway):
    """Return an DatastreamManager instance."""
    return DatastreamManager(initialized_gateway)


class Test_DatastreamManager_Sync:
    """Test the DatastreamManager class sync methods."""

    async def test_init(self, datastream_manager, hass, gateway):
        """Test the __init__ method."""
        assert datastream_manager._gateway == gateway


@pytest.mark.asyncio
class Test_DatastreamManager_Async:
    """Test the DatastreamManager class async methods."""

    async def test_async_init(self, datastream_manager):
        """Test the async_init method."""
        # Mock the _create_index_template method
        with (
            patch.object(datastream_manager, "_create_index_template", AsyncMock()),
            patch.object(datastream_manager, "_needs_index_template", return_value=False),
            patch.object(datastream_manager, "_needs_index_template_update", return_value=False),
        ):
            await datastream_manager.async_init()

    async def test_needs_index_template(self, datastream_manager):
        """Test the _needs_index_template method."""

        # Mock the get_index_template method to return a matching template
        datastream_manager._gateway.get_index_template = AsyncMock(
            return_value={"index_templates": []},
        )

        result = await datastream_manager._needs_index_template()

        assert result

    @pytest.mark.asyncio
    async def test_create_index_template(self, datastream_manager, snapshot):
        """Test the _create_index_template method."""
        # Mock the _needs_index_template method to return False
        with patch.object(datastream_manager, "_needs_index_template", return_value=True):
            # Mock the put_index_template method
            datastream_manager._gateway.put_index_template = AsyncMock()

            await datastream_manager._create_index_template()

            datastream_manager._gateway.put_index_template.assert_called_once()

            call_args = datastream_manager._gateway.put_index_template.call_args.kwargs

            assert call_args == snapshot

    async def test_create_index_template_update(self, datastream_manager, snapshot):
        """Test the _create_index_template method causes a rollover on update."""
        with (
            patch.object(datastream_manager, "_needs_index_template", return_value=False),
            patch.object(datastream_manager, "_needs_index_template_update", return_value=True),
        ):
            # Mock the put_index_template method
            datastream_manager._gateway.put_index_template = AsyncMock()
            datastream_manager._rollover_ha_datastreams = AsyncMock()

            await datastream_manager._create_index_template()

            datastream_manager._gateway.put_index_template.assert_called_once()
            datastream_manager._rollover_ha_datastreams.assert_called_once()

            call_args = datastream_manager._gateway.put_index_template.call_args.kwargs

            assert call_args == snapshot

    async def test_datastream_rollover(self, datastream_manager):
        """Test the datastream_rollover method."""
        # Mock the rollover_index method

        # GET /_data_stream/my-data-stream

        datastream_manager._gateway.rollover_datastream = AsyncMock()

        datastream_manager._gateway.get_datastreams = AsyncMock(
            return_value={
                "data_streams": [
                    {
                        "name": "metrics-homeassistant.sensor-default",
                        "indices": ["metrics-homeassistant.sensor-default"],
                        "data_stream": {
                            "name": "metrics-homeassistant.sensor-default",
                            "timestamp_field": {"name": "@timestamp"},
                        },
                    },
                    {
                        "name": "metrics-homeassistant.counter-default",
                        "indices": ["metrics-homeassistant.counter-default"],
                        "data_stream": {
                            "name": "metrics-homeassistant.counter-default",
                            "timestamp_field": {"name": "@timestamp"},
                        },
                    },
                ]
            }
        )

        await datastream_manager._rollover_ha_datastreams()

        datastream_manager._gateway.get_datastreams.assert_called_once()

        assert datastream_manager._gateway.rollover_datastream.call_count == 2

        datastream_manager._gateway.rollover_datastream.assert_called_with(
            datastream="metrics-homeassistant.counter-default"
        )

    async def test_needs_index_template_update(self, datastream_manager, snapshot):
        """Test the _needs_index_template_update method."""
        # Mock the get_index_template method to return a matching template
        datastream_manager._gateway.get_index_template = AsyncMock(
            return_value={
                "index_templates": [
                    {
                        "name": "datastream_metrics",
                        "index_template": {"version": 1},
                    }
                ]
            },
        )

        result = await datastream_manager._needs_index_template_update()

        assert result

    async def test_needs_index_template_no_update(self, datastream_manager, snapshot):
        """Test the _needs_index_template_update method."""
        # Mock the get_index_template method to return a matching template
        datastream_manager._gateway.get_index_template = AsyncMock(
            return_value={
                "index_templates": [
                    {
                        "name": "datastream_metrics",
                        "index_template": {"version": 2},
                    }
                ]
            },
        )

        result = await datastream_manager._needs_index_template_update()

        assert not result

    # @async_log_enter_exit_debug
    # async def _needs_index_template_update(self) -> bool:
    #     matching_templates = await self._gateway.get_index_template(
    #         name=DATASTREAM_METRICS_INDEX_TEMPLATE_NAME,
    #         ignore=[404],
    #     )

    #     matching_template = matching_templates.get("index_templates", [{}])[0]

    #     new_template = await self._get_index_template_from_disk()

    #     imported_version = matching_template["index_template"].get("version", 0)
    #     new_version = new_template.get("version", 0)

    #     if imported_version != new_version:
    #         self._logger.info(
    #             "Update required from [%s} to [%s] for Home Assistant datastream index template",
    #             imported_version,
    #             new_version,
    #         )
    #         return True

    #     return False

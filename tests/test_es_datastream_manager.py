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
class Test_Integration_Tests:
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
        """Test the logic for whether ES cluster needs index templates to be installed."""

        # Mock the get_index_template method to return a matching template
        datastream_manager._gateway.get_index_template = AsyncMock(
            return_value={"index_templates": []},
        )

        result = await datastream_manager._needs_index_template()

        assert result

    @pytest.mark.asyncio
    async def test_create_index_template(self, datastream_manager, snapshot):
        """Test installation of index templates when they are missing."""

        # Mock the _needs_index_template method to return False
        with patch.object(datastream_manager, "_needs_index_template", return_value=True):
            # Mock the put_index_template method
            datastream_manager._gateway.put_index_template = AsyncMock()

            await datastream_manager._create_index_template()

            datastream_manager._gateway.put_index_template.assert_called_once()

            call_args = datastream_manager._gateway.put_index_template.call_args.kwargs

            assert call_args == snapshot

    async def test_create_index_template_update(self, datastream_manager, snapshot):
        """Test updating index templates when they are out-of-date and ensure it causes a data stream rollover."""
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

        datastream_manager._gateway.get_datastream = AsyncMock(
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

        datastream_manager._gateway.get_datastream.assert_called_once()

        assert datastream_manager._gateway.rollover_datastream.call_count == 2

        datastream_manager._gateway.rollover_datastream.assert_called_with(
            datastream="metrics-homeassistant.counter-default"
        )

    @pytest.mark.parametrize(
        ("installed_version", "needs_update"),
        [(1, True), (2, False)],
        ids=["Out of date", "Up to date"],
    )
    async def test_needs_index_template_update(
        self, datastream_manager: DatastreamManager, installed_version, needs_update
    ):
        """Test the logic for determining if we need to update the index template."""
        # Mock the get_index_template method to return a matching template
        datastream_manager._gateway.get_index_template = AsyncMock(
            return_value={
                "index_templates": [
                    {
                        "name": "datastream_metrics",
                        "index_template": {"version": installed_version},
                    }
                ]
            },
        )

        assert await datastream_manager._needs_index_template_update() == needs_update

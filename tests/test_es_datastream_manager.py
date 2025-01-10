"""Tests for the index manager class."""
# noqa: F401 # pylint: disable=redefined-outer-name

from unittest.mock import AsyncMock

import pytest
from custom_components.elasticsearch.es_datastream_manager import DatastreamManager
from elasticsearch.datastreams import index_template
from elasticsearch.es_gateway import ElasticsearchGateway


@pytest.fixture
async def mock_gateway() -> AsyncMock:
    """Return an ElasticsearchGateway instance."""
    gateway = AsyncMock(ElasticsearchGateway)

    gateway.get_index_template = AsyncMock()
    gateway.put_index_template = AsyncMock()
    gateway.get_datastream = AsyncMock()
    gateway.rollover_datastream = AsyncMock()

    return gateway


class Test_Initialization:
    """Test the DatastreamManager class sync methods."""

    def test_init(self, mock_gateway):
        """Test the __init__ method."""

        datastream_manager = DatastreamManager(mock_gateway)

        assert datastream_manager is not None
        assert datastream_manager._gateway == mock_gateway

    class Test_Async_init:
        """Test the DatastreamManager class initialization scenarios."""

        @pytest.fixture
        async def datastream_manager(self, mock_gateway) -> DatastreamManager:
            """Return an DatastreamManager instance."""
            return DatastreamManager(mock_gateway)

        async def test_async_init_first_run(self, datastream_manager):
            """Test initialization of the DatastreamManager with a fresh ES cluster."""

            datastream_manager._gateway.get_index_template = AsyncMock(
                return_value={"index_templates": []},
            )

            await datastream_manager.async_init()

            datastream_manager._gateway.get_index_template.assert_called_once()
            datastream_manager._gateway.put_index_template.assert_called_once()
            datastream_manager._gateway.rollover_datastream.assert_not_called()

        async def test_async_init_second_run(self, datastream_manager):
            """Test initialization of the DatastreamManager with an existing ES cluster."""
            datastream_manager._gateway.get_index_template = AsyncMock(
                return_value={
                    "index_templates": [
                        {
                            "name": "datastream_metrics",
                            "index_template": {
                                "version": index_template.index_template_definition["version"]
                            },
                        }
                    ]
                },
            )

            await datastream_manager.async_init()

            assert datastream_manager._gateway.get_index_template.call_count == 2
            datastream_manager._gateway.put_index_template.assert_not_called()
            datastream_manager._gateway.rollover_datastream.assert_not_called()

        async def test_async_init_update_required(self, datastream_manager):
            """Test initialization of the DatastreamManager with an existing ES cluster that requires an index template update and rollover."""
            datastream_manager._gateway.get_index_template = AsyncMock(
                return_value={
                    "index_templates": [{"name": "datastream_metrics", "index_template": {"version": 1}}]
                },
            )

            datastream_manager._gateway.get_datastream = AsyncMock(
                return_value={
                    "data_streams": [
                        {
                            "name": "metrics-homeassistant.sensor-default",
                        },
                        {
                            "name": "metrics-homeassistant.counter-default",
                        },
                    ]
                }
            )

            await datastream_manager.async_init()

            assert datastream_manager._gateway.get_index_template.call_count == 2
            datastream_manager._gateway.put_index_template.assert_called_once()
            assert datastream_manager._gateway.rollover_datastream.call_count == 2

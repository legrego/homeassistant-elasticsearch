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
        with patch.object(datastream_manager, "_create_index_template", AsyncMock()):
            await datastream_manager.async_init()

            datastream_manager._create_index_template.assert_called_once()

    async def test_needs_index_template(self, datastream_manager):
        """Test the _needs_index_template method."""

        # Mock the get_index_template method to return a matching template
        datastream_manager._gateway.get_index_template = AsyncMock(
            return_value={"index_templates": [{"name": "datastream_metrics"}]},
        )

        result = await datastream_manager._needs_index_template()

        assert result

    @pytest.mark.asyncio
    async def test_create_index_template(self, datastream_manager, snapshot):
        """Test the _create_index_template method."""
        # Mock the _needs_index_template method to return False
        with patch.object(datastream_manager, "_needs_index_template", return_value=False):
            # Mock the put_index_template method
            datastream_manager._gateway.put_index_template = AsyncMock()

            await datastream_manager._create_index_template()

            datastream_manager._gateway.put_index_template.assert_called_once()

            call_args = datastream_manager._gateway.put_index_template.call_args.kwargs

            assert call_args == snapshot

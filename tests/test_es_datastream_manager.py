"""Tests for the index manager class."""

from unittest.mock import AsyncMock, patch

import pytest
from custom_components.elasticsearch.es_datastream_manager import IndexManager
from custom_components.elasticsearch.es_gateway import Elasticsearch8Gateway
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_gateway(hass: HomeAssistant) -> Elasticsearch8Gateway:
    """Mock ElasticsearchGateway instance."""

    gateway_settings: dict = {
        "hass": hass,
        "url": "https://my_es_host:9200",
    }

    return Elasticsearch8Gateway(**gateway_settings)


@pytest.fixture
async def datastream_manager(hass, mock_gateway):
    """Return an IndexManager instance."""
    datastream_manager = IndexManager(hass, mock_gateway)

    yield datastream_manager

    datastream_manager.stop()


class Test_IndexManager_Sync:
    """Test the IndexManager class sync methods."""

    async def test_init(self, datastream_manager, hass, mock_gateway):
        """Test the __init__ method."""
        assert datastream_manager._hass == hass
        assert datastream_manager._gateway == mock_gateway


@pytest.mark.asyncio
class Test_IndexManager_Async:
    """Test the IndexManager class async methods."""

    async def test_async_init(self, datastream_manager):
        """Test the async_init method."""
        # Mock the _create_index_template method
        with patch.object(datastream_manager, "_create_index_template", AsyncMock()):
            await datastream_manager.async_init()

            datastream_manager._create_index_template.assert_called_once()

    async def test_needs_index_template(self, datastream_manager, mock_gateway):
        """Test the _needs_index_template method."""

        # Mock the get_index_template method to return a matching template
        mock_gateway.get_index_template = AsyncMock(
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

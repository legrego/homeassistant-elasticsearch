"""Tests for the index manager class."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.elasticsearch.es_gateway import Elasticsearch8Gateway
from custom_components.elasticsearch.es_index_manager import IndexManager


@pytest.fixture
def mock_gateway(hass: HomeAssistant) -> Elasticsearch8Gateway:
    """Mock ElasticsearchGateway instance."""

    gateway_settings: dict = {
        "hass": hass,
        "url": "https://localhost:9200",
    }

    return Elasticsearch8Gateway(**gateway_settings)


@pytest.fixture
async def index_manager(hass, mock_gateway):
    """Return an IndexManager instance."""
    index_manager = IndexManager(hass, mock_gateway)

    yield index_manager

    index_manager.stop()


class Test_IndexManager_Sync:
    """Test the IndexManager class sync methods."""

    def test_init(self, index_manager, hass, mock_gateway):
        """Test the __init__ method."""
        assert index_manager._hass == hass
        assert index_manager._gateway == mock_gateway


@pytest.mark.asyncio()
class Test_IndexManager_Async:
    """Test the IndexManager class async methods."""

    async def test_async_init(self, index_manager):
        """Test the async_init method."""
        # Mock the _create_index_template method
        with patch.object(index_manager, "_create_index_template", AsyncMock()):
            await index_manager.async_init()

            index_manager._create_index_template.assert_called_once()

    async def test_needs_index_template(self, index_manager, mock_gateway):
        """Test the _needs_index_template method."""

        # Mock the get_index_template method to return a matching template
        mock_gateway.get_index_template = AsyncMock(
            return_value={"index_templates": [{"name": "datastream_metrics"}]},
        )

        result = await index_manager._needs_index_template()

        assert result

    @pytest.mark.asyncio()
    async def test_create_index_template(self, index_manager, snapshot):
        """Test the _create_index_template method."""
        # Mock the _needs_index_template method to return False
        with patch.object(index_manager, "_needs_index_template", return_value=False):
            # Mock the put_index_template method
            index_manager._gateway.put_index_template = AsyncMock()

            await index_manager._create_index_template()

            index_manager._gateway.put_index_template.assert_called_once()

            call_args = index_manager._gateway.put_index_template.call_args.kwargs

            assert call_args == snapshot

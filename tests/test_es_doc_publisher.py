"""Tests for the DocumentPublisher class."""

from datetime import datetime
import pytest
from homeassistant.setup import async_setup_component
from homeassistant.util.dt import UTC
from custom_components.elasticsearch.config_flow import build_full_config
from custom_components.elasticsearch.es_doc_publisher import DocumentPublisher
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from custom_components.elasticsearch.es_index_manager import IndexManager
from tests.test_util.aioclient_mock_utils import extract_es_bulk_requests
from tests.test_util.es_startup_mocks import mock_es_initialization
from freezegun.api import FrozenDateTimeFactory
from jsondiff import diff

from homeassistant.components.counter import (
    DOMAIN as COUNTER_DOMAIN
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

@pytest.mark.asyncio
async def test_publish_state_change(hass, es_aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory):
    """Test entity change is published."""

    freezer.move_to(datetime(2023, 4, 12, 12, tzinfo=UTC))  # Monday

    counter_config = {COUNTER_DOMAIN: {"test_1": {}}}
    assert await async_setup_component(hass, COUNTER_DOMAIN, counter_config)
    await hass.async_block_till_done()

    mock_es_initialization(
        es_aioclient_mock,
        "http://localhost:9200"
    )

    config = build_full_config({
        "url": "http://localhost:9200"
    })


    gateway = ElasticsearchGateway(config)
    index_manager = IndexManager(hass, config, gateway)
    publisher = DocumentPublisher(config, gateway, index_manager, hass)

    await gateway.async_init()
    await publisher.async_init()

    assert publisher.queue_size() == 0

    hass.states.async_set("counter.test_1", "2")
    await hass.async_block_till_done()

    assert publisher.queue_size() == 1

    await publisher.async_do_publish()

    bulk_requests = extract_es_bulk_requests(es_aioclient_mock)

    assert len(bulk_requests) == 1
    request = bulk_requests[0]

    expected = [
        {"index":{"_index":"active-hass-index-v4_2"}},
        {
            "hass.domain":"counter",
            "hass.object_id":"test_1",
            "hass.object_id_lower":"test_1",
            "hass.entity_id":"counter.test_1",
            "hass.entity_id_lower":"counter.test_1",
            "hass.attributes":{},
            "hass.value":2.0,
            "@timestamp":"2023-04-12T12:00:00+00:00",
            "hass.entity":{
                "id":"counter.test_1",
                "domain":"counter",
                "attributes":{},
                "device":{},
                "value":2.0,
                "platform":"counter"
            },
            "agent.name":"My Home Assistant",
            "agent.type":"hass",
            "agent.version":"2023.2.0",
            "ecs.version":"1.0.0",
            "host.geo.location":{"lat":32.87336,"lon":-117.22743},
            "host.architecture":"aarch64",
            "host.os.name":"Linux",
            "host.hostname":"53561d460d26",
            "tags":None
        }
    ]

    assert diff(request.data, expected) == {}

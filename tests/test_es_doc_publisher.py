"""Tests for the DocumentPublisher class."""

from datetime import datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.counter import DOMAIN as COUNTER_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.dt import UTC
from jsondiff import diff
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.elasticsearch.config_flow import build_full_config
from custom_components.elasticsearch.const import (
    CONF_PUBLISH_MODE,
    PUBLISH_MODE_ALL,
    PUBLISH_MODE_ANY_CHANGES,
    PUBLISH_MODE_STATE_CHANGES,
)
from custom_components.elasticsearch.es_doc_publisher import DocumentPublisher
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from custom_components.elasticsearch.es_index_manager import IndexManager
from tests.test_util.aioclient_mock_utils import extract_es_bulk_requests
from tests.test_util.es_startup_mocks import mock_es_initialization


@pytest.mark.asyncio
async def test_publish_state_change(hass, es_aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory, skip_system_info):
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

    events = [{
        "domain": "counter",
        "object_id": "test_1",
        "value": 2.0,
        "platform": "counter",
        "attributes": {}
    }]

    assert diff(request.data, _build_expected_payload(events)) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize('publish_mode', [PUBLISH_MODE_STATE_CHANGES, PUBLISH_MODE_ANY_CHANGES, PUBLISH_MODE_ALL])
async def test_publish_modes(hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory, publish_mode, skip_system_info):
    """Test publish modes behave correctly."""
    freezer.move_to(datetime(2023, 4, 12, 12, tzinfo=UTC))  # Monday

    counter_config = {COUNTER_DOMAIN: {"test_1": {}, "test_2": {}}}
    assert await async_setup_component(hass, COUNTER_DOMAIN, counter_config)
    await hass.async_block_till_done()

    hass.states.async_set("counter.test_1", "2")
    hass.states.async_set("counter.test_2", "2")
    await hass.async_block_till_done()

    mock_es_initialization(
        es_aioclient_mock,
        "http://localhost:9200"
    )

    config = build_full_config({
        "url": "http://localhost:9200",
        CONF_PUBLISH_MODE: publish_mode
    })

    gateway = ElasticsearchGateway(config)
    index_manager = IndexManager(hass, config, gateway)
    publisher = DocumentPublisher(config, gateway, index_manager, hass)

    await gateway.async_init()
    await publisher.async_init()

    assert publisher.queue_size() == 0

    # State change
    hass.states.async_set("counter.test_1", "3", force_update=True)
    await hass.async_block_till_done()

    # Attribute change
    hass.states.async_set("counter.test_1", "3", {
        "new_attr": "attr_value"
    }, force_update=True)

    await hass.async_block_till_done()

    if publish_mode == PUBLISH_MODE_ALL or publish_mode == PUBLISH_MODE_ANY_CHANGES:
        assert publisher.queue_size() == 2
    if publish_mode == PUBLISH_MODE_STATE_CHANGES:
        assert publisher.queue_size() == 1

    await publisher.async_do_publish()

    bulk_requests = extract_es_bulk_requests(es_aioclient_mock)
    assert len(bulk_requests) == 1

    events = [{
        "domain": "counter",
        "object_id": "test_1",
        "value": 3.0,
        "platform": "counter",
        "attributes": {}
    }]

    if publish_mode != PUBLISH_MODE_STATE_CHANGES:
        events.append({
            "domain": "counter",
            "object_id": "test_1",
            "value": 3.0,
            "platform": "counter",
            "attributes": {
                "new_attr": "attr_value"
            }
        })

    if publish_mode == PUBLISH_MODE_ALL:
        events.append({
            "domain": "counter",
            "object_id": "test_2",
            "value": 2.0,
            "platform": "counter",
            "attributes": {}
        })


    payload = bulk_requests[0].data

    assert diff(_build_expected_payload(events), payload) == {}

def _build_expected_payload(events: list):
    def event_to_payload(event):
        entity_id = event["domain"] + "." + event["object_id"]
        return [
            {"index":{"_index":"active-hass-index-v4_2"}},
            {
                "hass.domain":event["domain"],
                "hass.object_id":event["object_id"],
                "hass.object_id_lower":event["object_id"],
                "hass.entity_id":entity_id,
                "hass.entity_id_lower":entity_id,
                "hass.attributes":event["attributes"],
                "hass.value":event["value"],
                "@timestamp":"2023-04-12T12:00:00+00:00",
                "hass.entity":{
                    "id":entity_id,
                    "domain":event["domain"],
                    "attributes":event["attributes"],
                    "device":{},
                    "value":event["value"],
                    "platform":event["platform"]
                },
                "agent.name":"My Home Assistant",
                "agent.type":"hass",
                "agent.version":"UNKNOWN",
                "ecs.version":"1.0.0",
                "host.geo.location":{"lat":32.87336,"lon":-117.22743},
                "host.architecture":"UNKNOWN",
                "host.os.name":"UNKNOWN",
                "host.hostname": "UNKNOWN",
                "tags":None
            }
        ]

    payload = []
    for event in events:
        for entry in event_to_payload(event):
            payload.append(entry)

    return payload

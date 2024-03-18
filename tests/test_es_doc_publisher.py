"""Tests for the DocumentPublisher class."""

from datetime import datetime
from unittest import mock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components import (
    counter,
    input_boolean,
    input_button,
    input_text,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry, device_registry, entity_registry
from homeassistant.setup import async_setup_component
from homeassistant.util.dt import UTC
from jsondiff import diff
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.elasticsearch.config_flow import build_full_config
from custom_components.elasticsearch.const import (
    CONF_EXCLUDED_DOMAINS,
    CONF_EXCLUDED_ENTITIES,
    CONF_INCLUDED_DOMAINS,
    CONF_INCLUDED_ENTITIES,
    CONF_INDEX_MODE,
    CONF_PUBLISH_MODE,
    DOMAIN,
    INDEX_MODE_LEGACY,
    PUBLISH_MODE_ALL,
    PUBLISH_MODE_ANY_CHANGES,
    PUBLISH_MODE_STATE_CHANGES,
)
from custom_components.elasticsearch.es_doc_publisher import DocumentPublisher
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from custom_components.elasticsearch.es_index_manager import IndexManager
from custom_components.elasticsearch.es_serializer import get_serializer
from tests.conftest import mock_config_entry
from tests.test_util.aioclient_mock_utils import extract_es_bulk_requests
from tests.test_util.es_startup_mocks import mock_es_initialization


@pytest.fixture(autouse=True)
def freeze_time(freezer: FrozenDateTimeFactory):
    """Freeze time so we can properly assert on payload contents."""
    freezer.move_to(datetime(2023, 4, 12, 12, tzinfo=UTC))  # Monday


@pytest.fixture(autouse=True)
def skip_system_info():
    """Fixture to skip returning system info."""

    async def get_system_info():
        return {}

    with mock.patch(
        "custom_components.elasticsearch.system_info.SystemInfo.async_get_system_info",
        side_effect=get_system_info,
    ):
        yield


async def _setup_config_entry(hass: HomeAssistant, mock_entry: mock_config_entry):
    mock_entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {}) is True
    await hass.async_block_till_done()

    config_entries = hass.config_entries.async_entries(DOMAIN)
    assert len(config_entries) == 1
    entry = config_entries[0]

    return entry


@pytest.mark.asyncio
async def test_publish_state_change(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test entity change is published."""

    counter_config = {counter.DOMAIN: {"test_1": {}}}
    assert await async_setup_component(hass, counter.DOMAIN, counter_config)
    await hass.async_block_till_done()

    es_url = "http://localhost:9200"

    mock_es_initialization(es_aioclient_mock, es_url)

    mock_entry = MockConfigEntry(
        unique_id="test_publish_state_change",
        domain=DOMAIN,
        version=3,
        data=build_full_config({"url": es_url, CONF_INDEX_MODE: INDEX_MODE_LEGACY}),
        title="ES Config",
    )

    entry = await _setup_config_entry(hass, mock_entry)

    config = entry.data
    gateway = ElasticsearchGateway(config)
    index_manager = IndexManager(hass, config, gateway)
    publisher = DocumentPublisher(
        config, gateway, index_manager, hass, config_entry=entry
    )

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

    events = [
        {
            "domain": "counter",
            "object_id": "test_1",
            "value": 2.0,
            "valueas": {},
            "platform": "counter",
            "attributes": {},
        }
    ]

    assert diff(request.data, _build_expected_payload(events)) == {}

    await gateway.async_stop_gateway()


@pytest.mark.asyncio
async def test_entity_detail_publishing(
    hass, es_aioclient_mock: AiohttpClientMocker, mock_config_entry: mock_config_entry
):
    """Test entity details are captured correctly."""

    entity_area = area_registry.async_get(hass).async_create("entity area")
    area_registry.async_get(hass).async_create("device area")

    dr = device_registry.async_get(hass)
    device = dr.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        connections={(device_registry.CONNECTION_NETWORK_MAC, "12:34:56:AB:CD:EF")},
        identifiers={("bridgeid", "0123")},
        sw_version="sw-version",
        name="name",
        manufacturer="manufacturer",
        model="model",
        suggested_area="device area",
    )

    config = {counter.DOMAIN: {"test_1": {}}}
    assert await async_setup_component(hass, counter.DOMAIN, config)
    entity_id = "counter.test_1"
    entity_name = "My Test Counter"
    entity_registry.async_get(hass).async_update_entity(
        entity_id, area_id=entity_area.id, device_id=device.id, name=entity_name
    )

    counter_config = {counter.DOMAIN: {"test_1": {}}}
    assert await async_setup_component(hass, counter.DOMAIN, counter_config)
    await hass.async_block_till_done()

    es_url = "http://localhost:9200"

    mock_es_initialization(es_aioclient_mock, es_url)

    config = build_full_config({"url": es_url, CONF_INDEX_MODE: INDEX_MODE_LEGACY})

    mock_entry = MockConfigEntry(
        unique_id="test_entity_detail_publishing",
        domain=DOMAIN,
        version=3,
        data=config,
        title="ES Config",
    )

    entry = await _setup_config_entry(hass, mock_entry)

    gateway = ElasticsearchGateway(config)
    index_manager = IndexManager(hass, config, gateway)
    publisher = DocumentPublisher(
        config, gateway, index_manager, hass, config_entry=entry
    )

    await gateway.async_init()
    await publisher.async_init()
    assert publisher.queue_size() == 0

    # State change
    hass.states.async_set("counter.test_1", "3", force_update=True)
    await hass.async_block_till_done()

    await publisher.async_do_publish()

    bulk_requests = extract_es_bulk_requests(es_aioclient_mock)
    assert len(bulk_requests) == 1

    events = [
        {
            "domain": "counter",
            "object_id": "test_1",
            "value": 3.0,
            "valueas": {},
            "platform": "counter",
            "attributes": {},
        }
    ]

    payload = bulk_requests[0].data

    assert (
        diff(
            _build_expected_payload(
                events,
                include_entity_details=True,
                device_id=device.id,
                entity_name=entity_name,
            ),
            payload,
        )
        == {}
    )
    await gateway.async_stop_gateway()


@pytest.mark.asyncio
async def test_attribute_publishing(hass, es_aioclient_mock: AiohttpClientMocker):
    """Test entity attributes can be serialized correctly."""

    counter_config = {counter.DOMAIN: {"test_1": {}}}
    assert await async_setup_component(hass, counter.DOMAIN, counter_config)
    await hass.async_block_till_done()

    es_url = "http://localhost:9200"

    mock_es_initialization(es_aioclient_mock, es_url)

    config = build_full_config({"url": es_url, CONF_INDEX_MODE: INDEX_MODE_LEGACY})

    mock_entry = MockConfigEntry(
        unique_id="test_entity_detail_publishing",
        domain=DOMAIN,
        version=3,
        data=config,
        title="ES Config",
    )

    entry = await _setup_config_entry(hass, mock_entry)

    gateway = ElasticsearchGateway(config)
    index_manager = IndexManager(hass, config, gateway)
    publisher = DocumentPublisher(
        config, gateway, index_manager, hass, config_entry=entry
    )

    await gateway.async_init()
    await publisher.async_init()

    assert publisher.queue_size() == 0

    class CustomAttributeClass:
        def __init__(self) -> None:
            self.field = "This class should be skipped, as it cannot be serialized."
            pass

    hass.states.async_set(
        "counter.test_1",
        "3",
        {
            "string": "abc123",
            "int": 123,
            "float": 123.456,
            "dict": {
                "string": "abc123",
                "int": 123,
                "float": 123.456,
            },
            "list": [1, 2, 3, 4],
            "set": {5, 5},
            "none": None,
            # Keyless entry should be excluded from output
            "": "Key is empty, and should be excluded",
            # Custom classes should be excluded from output
            "naughty": CustomAttributeClass(),
            # Entries with non-string keys should be excluded from output
            datetime.now(): "Key is a datetime, and should be excluded",
            123: "Key is a number, and should be excluded",
            True: "Key is a bool, and should be excluded",
        },
    )
    await hass.async_block_till_done()

    assert publisher.queue_size() == 1

    await publisher.async_do_publish()

    bulk_requests = extract_es_bulk_requests(es_aioclient_mock)

    assert len(bulk_requests) == 1
    request = bulk_requests[0]

    serializer = get_serializer()

    events = [
        {
            "domain": "counter",
            "object_id": "test_1",
            "value": 3.0,
            "valueas": {},
            "platform": "counter",
            "attributes": {
                "string": "abc123",
                "int": 123,
                "float": 123.456,
                "dict": serializer.dumps(
                    {
                        "string": "abc123",
                        "int": 123,
                        "float": 123.456,
                    }
                ),
                "list": [1, 2, 3, 4],
                "set": [5],  # set should be converted to a list,
                "none": None,
            },
        }
    ]

    assert diff(request.data, _build_expected_payload(events)) == {}
    await gateway.async_stop_gateway()


@pytest.mark.asyncio
async def test_include_exclude_publishing_mode_all(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test entities can be included/excluded from publishing."""

    counter_config = {counter.DOMAIN: {"test_1": {}, "test_2": {}}}
    assert await async_setup_component(hass, counter.DOMAIN, counter_config)

    input_boolean_config = {
        input_boolean.DOMAIN: {
            "test_1": {"name": "test boolean 1", "initial": False},
            "test_2": {"name": "test boolean 2", "initial": True},
        }
    }
    assert await async_setup_component(hass, input_boolean.DOMAIN, input_boolean_config)

    input_button_config = {input_button.DOMAIN: {"test_1": {}, "test_2": {}}}
    assert await async_setup_component(hass, input_button.DOMAIN, input_button_config)

    input_text_config = {
        input_text.DOMAIN: {
            "test_1": {"name": "test text 1", "initial": "Hello"},
            "test_2": {"name": "test text 2", "initial": "World"},
        }
    }
    assert await async_setup_component(hass, input_text.DOMAIN, input_text_config)
    await hass.async_block_till_done()

    es_url = "http://localhost:9200"

    mock_es_initialization(es_aioclient_mock, es_url)

    config = build_full_config(
        {
            "url": es_url,
            CONF_INDEX_MODE: INDEX_MODE_LEGACY,
            CONF_PUBLISH_MODE: PUBLISH_MODE_ALL,
            CONF_INCLUDED_ENTITIES: ["counter.test_1"],
            CONF_INCLUDED_DOMAINS: [input_boolean.DOMAIN, input_button.DOMAIN],
            CONF_EXCLUDED_ENTITIES: ["input_boolean.test_2"],
            CONF_EXCLUDED_DOMAINS: [counter.DOMAIN],
        }
    )

    mock_entry = MockConfigEntry(
        unique_id="test_entity_detail_publishing",
        domain=DOMAIN,
        version=3,
        data=config,
        title="ES Config",
    )

    entry = await _setup_config_entry(hass, mock_entry)

    # input_text is intentionally excluded from this configuration.
    # It should still be included when publish_mode == PUBLISH_MODE_ALL

    gateway = ElasticsearchGateway(config)
    index_manager = IndexManager(hass, config, gateway)
    publisher = DocumentPublisher(
        config, gateway, index_manager, hass, config_entry=entry
    )

    await gateway.async_init()
    await publisher.async_init()

    assert publisher.queue_size() == 0
    await hass.async_block_till_done()
    assert publisher.queue_size() == 0

    await publisher.async_do_publish()

    bulk_requests = extract_es_bulk_requests(es_aioclient_mock)

    assert len(bulk_requests) == 1
    request = bulk_requests[0]
    events = [
        {
            "domain": "counter",
            "object_id": "test_1",
            "value": 0.0,
            "valueas": {},
            "platform": "counter",
            "attributes": {"editable": False, "initial": 0, "step": 1},
        },
        {
            "domain": "input_boolean",
            "object_id": "test_1",
            "value": 0,
            "valueas": {},
            "platform": "input_boolean",
            "attributes": {"editable": False, "friendly_name": "test boolean 1"},
        },
        {
            "domain": "input_button",
            "object_id": "test_1",
            "value": 0,
            "valueas": {},
            "platform": "input_button",
            "attributes": {"editable": False},
        },
        {
            "domain": "input_button",
            "object_id": "test_2",
            "value": 0,
            "valueas": {},
            "platform": "input_button",
            "attributes": {"editable": False},
        },
        {
            "domain": "input_text",
            "object_id": "test_1",
            "value": "Hello",
            "valueas": {},
            "platform": "input_text",
            "attributes": {
                "editable": False,
                "min": 0,
                "max": 100,
                "pattern": None,
                "mode": "text",
                "friendly_name": "test text 1",
            },
        },
        {
            "domain": "input_text",
            "object_id": "test_2",
            "value": "World",
            "valueas": {},
            "platform": "input_text",
            "attributes": {
                "editable": False,
                "min": 0,
                "max": 100,
                "pattern": None,
                "mode": "text",
                "friendly_name": "test text 2",
            },
        },
    ]

    assert diff(request.data, _build_expected_payload(events)) == {}
    await gateway.async_stop_gateway()


@pytest.mark.asyncio
async def test_include_exclude_publishing_mode_any(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test entities can be included/excluded from publishing."""

    counter_config = {counter.DOMAIN: {"test_1": {}, "test_2": {}}}
    assert await async_setup_component(hass, counter.DOMAIN, counter_config)

    input_boolean_config = {
        input_boolean.DOMAIN: {
            "test_1": {"name": "test boolean 1", "initial": False},
            "test_2": {"name": "test boolean 2", "initial": True},
        }
    }
    assert await async_setup_component(hass, input_boolean.DOMAIN, input_boolean_config)

    input_button_config = {input_button.DOMAIN: {"test_1": {}, "test_2": {}}}
    assert await async_setup_component(hass, input_button.DOMAIN, input_button_config)

    input_text_config = {
        input_text.DOMAIN: {
            "test_1": {"name": "test text 1", "initial": "Hello"},
            "test_2": {"name": "test text 2", "initial": "World"},
        }
    }
    assert await async_setup_component(hass, input_text.DOMAIN, input_text_config)
    await hass.async_block_till_done()

    es_url = "http://localhost:9200"

    mock_es_initialization(es_aioclient_mock, es_url)

    config = build_full_config(
        {
            "url": es_url,
            CONF_PUBLISH_MODE: PUBLISH_MODE_ANY_CHANGES,
            CONF_INDEX_MODE: INDEX_MODE_LEGACY,
            CONF_INCLUDED_ENTITIES: ["counter.test_1"],
            CONF_INCLUDED_DOMAINS: [input_boolean.DOMAIN, input_button.DOMAIN],
            CONF_EXCLUDED_ENTITIES: ["input_boolean.test_2"],
            CONF_EXCLUDED_DOMAINS: [counter.DOMAIN],
        }
    )

    mock_entry = MockConfigEntry(
        unique_id="test_entity_detail_publishing",
        domain=DOMAIN,
        version=3,
        data=config,
        title="ES Config",
    )

    entry = await _setup_config_entry(hass, mock_entry)

    # input_text is intentionally excluded from this configuration.
    # It should still be included when publish_mode == PUBLISH_MODE_ALL

    gateway = ElasticsearchGateway(config)
    index_manager = IndexManager(hass, config, gateway)
    publisher = DocumentPublisher(
        config, gateway, index_manager, hass, config_entry=entry
    )

    await gateway.async_init()
    await publisher.async_init()

    assert publisher.queue_size() == 0
    await hass.async_block_till_done()
    assert publisher.queue_size() == 0

    await publisher.async_do_publish()

    bulk_requests = extract_es_bulk_requests(es_aioclient_mock)
    # At this point, no state changes have taken place
    assert len(bulk_requests) == 0

    # At this point in the test, no entity changes have taken place.

    # Trigger state changes
    hass.states.async_set("counter.test_1", "3.0")
    hass.states.async_set("counter.test_1", "Infinity")
    hass.states.async_set("counter.test_2", "3")
    hass.states.async_set("input_boolean.test_2", "False")
    hass.states.async_set("input_button.test_2", "1")

    await hass.async_block_till_done()

    await publisher.async_do_publish()
    bulk_requests = extract_es_bulk_requests(es_aioclient_mock)
    assert len(bulk_requests) == 1

    request = bulk_requests[0]
    events = [
        {
            "domain": "counter",
            "object_id": "test_1",
            "value": 3.0,
            "valueas": {},
            "platform": "counter",
            "attributes": {},
        },
        {
            "domain": "counter",
            "object_id": "test_1",
            "value": "Infinity",
            "valueas": {},
            "platform": "counter",
            "attributes": {},
        },
        {
            "domain": "input_button",
            "object_id": "test_2",
            "value": 1,
            "valueas": {},
            "platform": "input_button",
            "attributes": {},
        },
    ]

    assert diff(request.data, _build_expected_payload(events)) == {}
    await gateway.async_stop_gateway()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "publish_mode",
    [PUBLISH_MODE_STATE_CHANGES, PUBLISH_MODE_ANY_CHANGES, PUBLISH_MODE_ALL],
)
async def test_publish_modes(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker, publish_mode
):
    """Test publish modes behave correctly."""

    counter_config = {counter.DOMAIN: {"test_1": {}, "test_2": {}}}
    assert await async_setup_component(hass, counter.DOMAIN, counter_config)
    await hass.async_block_till_done()

    hass.states.async_set("counter.test_1", "2")
    hass.states.async_set("counter.test_2", "2")
    await hass.async_block_till_done()

    es_url = "http://localhost:9200"

    mock_es_initialization(es_aioclient_mock, es_url)

    config = build_full_config(
        {
            "url": es_url,
            CONF_PUBLISH_MODE: publish_mode,
            CONF_INDEX_MODE: INDEX_MODE_LEGACY,
        }
    )

    mock_entry = MockConfigEntry(
        unique_id="test_entity_detail_publishing",
        domain=DOMAIN,
        version=3,
        data=config,
        title="ES Config",
    )

    entry = await _setup_config_entry(hass, mock_entry)

    gateway = ElasticsearchGateway(config)
    index_manager = IndexManager(hass, config, gateway)
    publisher = DocumentPublisher(
        config, gateway, index_manager, hass, config_entry=entry
    )

    await gateway.async_init()
    await publisher.async_init()

    assert publisher.queue_size() == 0

    # State change
    hass.states.async_set("counter.test_1", "3", force_update=True)
    await hass.async_block_till_done()

    # Attribute change
    hass.states.async_set(
        "counter.test_1", "3", {"new_attr": "attr_value"}, force_update=True
    )

    await hass.async_block_till_done()

    if publish_mode == PUBLISH_MODE_ALL or publish_mode == PUBLISH_MODE_ANY_CHANGES:
        assert publisher.queue_size() == 2
    if publish_mode == PUBLISH_MODE_STATE_CHANGES:
        assert publisher.queue_size() == 1

    await publisher.async_do_publish()

    bulk_requests = extract_es_bulk_requests(es_aioclient_mock)
    assert len(bulk_requests) == 1

    events = [
        {
            "domain": "counter",
            "object_id": "test_1",
            "value": 3.0,
            "valueas": {},
            "platform": "counter",
            "attributes": {},
        }
    ]

    if publish_mode != PUBLISH_MODE_STATE_CHANGES:
        events.append(
            {
                "domain": "counter",
                "object_id": "test_1",
                "value": 3.0,
                "valueas": {},
                "platform": "counter",
                "attributes": {"new_attr": "attr_value"},
            }
        )

    if publish_mode == PUBLISH_MODE_ALL:
        events.append(
            {
                "domain": "counter",
                "object_id": "test_2",
                "value": 2.0,
                "valueas": {},
                "platform": "counter",
                "attributes": {},
            }
        )

    payload = bulk_requests[0].data

    assert diff(_build_expected_payload(events), payload) == {}
    await gateway.async_stop_gateway()


def _build_expected_payload(
    events: list, include_entity_details=False, device_id=None, entity_name=None
):
    def event_to_payload(event):
        entity_id = event["domain"] + "." + event["object_id"]
        payload = [{"index": {"_index": "active-hass-index-v4_2"}}]

        entry = {
            "hass.domain": event["domain"],
            "hass.object_id": event["object_id"],
            "hass.object_id_lower": event["object_id"],
            "hass.entity_id": entity_id,
            "hass.entity_id_lower": entity_id,
            "hass.attributes": event["attributes"],
            "hass.value": event["value"],
            "@timestamp": "2023-04-12T12:00:00+00:00",
            "hass.entity": {
                "id": entity_id,
                "domain": event["domain"],
                "attributes": event["attributes"],
                "device": {},
                "value": event["value"],
                "valueas": event["valueas"],
                "platform": event["platform"],
            },
            "agent.name": "My Home Assistant",
            "agent.type": "hass",
            "agent.version": "UNKNOWN",
            "ecs.version": "1.0.0",
            "host.geo.location": {"lat": 32.87336, "lon": -117.22743},
            "host.architecture": "UNKNOWN",
            "host.os.name": "UNKNOWN",
            "host.hostname": "UNKNOWN",
            "tags": None,
        }

        if include_entity_details:
            entry["hass.entity"].update(
                {
                    "name": entity_name,
                    "area": {"id": "entity_area", "name": "entity area"},
                    "device": {
                        "id": device_id,
                        "name": "name",
                        "area": {"id": "device_area", "name": "device area"},
                    },
                }
            )

        payload.append(entry)

        return payload

    payload = []
    for event in events:
        for entry in event_to_payload(event):
            payload.append(entry)

    return payload

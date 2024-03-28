"""Tests for the DocumentPublisher class."""

from datetime import datetime
from unittest import mock

import pytest
from elasticsearch.utils import get_merged_config
from homeassistant.components import (
    counter,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import area_registry, device_registry, entity_registry
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from jsondiff import diff
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.elasticsearch.config_flow import build_full_config
from custom_components.elasticsearch.const import (
    CONF_INDEX_MODE,
    DOMAIN,
    INDEX_MODE_LEGACY,
)
from custom_components.elasticsearch.es_doc_creator import DocumentCreator
from tests.conftest import mock_config_entry
from tests.const import (
    MOCK_LOCATION_DEVICE,
    MOCK_LOCATION_SERVER,
    MOCK_NOON_APRIL_12TH_2023,
)


@pytest.fixture(autouse=True)
def skip_system_info():
    """Fixture to skip returning system info."""

    async def get_system_info():
        return {}

    with mock.patch(
        "custom_components.elasticsearch.system_info.SystemInfo.async_get_system_info",
        side_effect=get_system_info,
    ):
        yield {}


async def _setup_config_entry(hass: HomeAssistant, mock_entry: mock_config_entry):
    mock_entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {}) is True
    await hass.async_block_till_done()

    config_entries = hass.config_entries.async_entries(DOMAIN)
    assert len(config_entries) == 1
    entry = config_entries[0]

    return entry


@pytest.fixture()
async def document_creator(hass: HomeAssistant):
    """Fixture to create a DocumentCreator instance."""

    # Fix the location for the tests
    hass.config.latitude = MOCK_LOCATION_SERVER["lat"]
    hass.config.longitude = MOCK_LOCATION_SERVER["lon"]

    es_url = "http://localhost:9200"
    mock_entry = MockConfigEntry(
        unique_id="test_doc_creator",
        domain=DOMAIN,
        version=3,
        data=build_full_config({"url": es_url, CONF_INDEX_MODE: INDEX_MODE_LEGACY}),
        title="ES Config",
    )

    config = get_merged_config(mock_entry)

    creator = DocumentCreator(hass, config)

    # TODO: Consider initializing the document creator before returning it, requires rewriting tests and initializing the whole integration
    # await creator.async_init()

    yield creator


async def create_and_return_document(
    hass: HomeAssistant,
    document_creator: DocumentCreator,
    value: str | float,
    attributes: dict,
    domain="sensor",
    entity_id="test_1",
    timestamp=MOCK_NOON_APRIL_12TH_2023,
    version=2,
):
    """Create and return a test document."""

    state = await create_and_return_state(
        hass, domain=domain, entity_id=entity_id, value=value, attributes=attributes
    )

    return document_creator.state_to_document(
        state, dt_util.parse_datetime(timestamp), version
    )


async def create_and_return_state(
    hass: HomeAssistant,
    value: str | float,
    attributes: dict,
    domain="sensor",
    entity_id="test_1",
):
    """Create and return a standard test state."""
    entity = domain + "." + entity_id

    hass.states.async_set(entity, value, attributes, True)

    await hass.async_block_till_done()

    return hass.states.get(entity)


# Unit tests for state conversions
@pytest.mark.asyncio
async def test_try_state_as_number(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test trying state to float conversion."""

    assert document_creator.try_state_as_number(State("domain.entity_id", "1")) is True
    assert document_creator.try_state_as_number(State("domain.entity_id", "0")) is True
    assert (
        document_creator.try_state_as_number(State("domain.entity_id", "1.0")) is True
    )
    assert (
        document_creator.try_state_as_number(State("domain.entity_id", "0.0")) is True
    )
    assert (
        document_creator.try_state_as_number(State("domain.entity_id", "2.0")) is True
    )
    assert document_creator.try_state_as_number(State("domain.entity_id", "2")) is True
    assert (
        document_creator.try_state_as_number(State("domain.entity_id", "tomato"))
        is False
    )

    assert (
        document_creator.try_state_as_number(
            State("domain.entity_id", MOCK_NOON_APRIL_12TH_2023)
        )
        is False
    )


@pytest.mark.asyncio
async def test_state_as_boolean(hass: HomeAssistant, document_creator: DocumentCreator):
    """Test state to boolean conversion."""

    assert document_creator.state_as_boolean(State("domain.entity_id", "true")) is True
    assert (
        document_creator.state_as_boolean(State("domain.entity_id", "false")) is False
    )
    assert document_creator.state_as_boolean(State("domain.entity_id", "on")) is True
    assert document_creator.state_as_boolean(State("domain.entity_id", "off")) is False

    with pytest.raises(ValueError):
        assert document_creator.state_as_boolean(State("domain.entity_id", "1"))
    with pytest.raises(ValueError):
        assert document_creator.state_as_boolean(State("domain.entity_id", "0"))
    with pytest.raises(ValueError):
        assert document_creator.state_as_boolean(State("domain.entity_id", "1.0"))
    with pytest.raises(ValueError):
        assert document_creator.state_as_boolean(
            State("domain.entity_id", MOCK_NOON_APRIL_12TH_2023)
        )


@pytest.mark.asyncio
async def test_try_state_as_boolean(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test trying state to boolean conversion."""
    assert (
        document_creator.try_state_as_boolean(State("domain.entity_id", "true")) is True
    )
    assert (
        document_creator.try_state_as_boolean(State("domain.entity_id", "false"))
        is True
    )
    assert (
        document_creator.try_state_as_boolean(State("domain.entity_id", "on")) is True
    )
    assert (
        document_creator.try_state_as_boolean(State("domain.entity_id", "off")) is True
    )
    assert (
        document_creator.try_state_as_boolean(State("domain.entity_id", "1")) is False
    )
    assert (
        document_creator.try_state_as_boolean(State("domain.entity_id", "0")) is False
    )
    assert (
        document_creator.try_state_as_boolean(State("domain.entity_id", "1.0")) is False
    )

    assert (
        document_creator.try_state_as_boolean(
            State("domain.entity_id", MOCK_NOON_APRIL_12TH_2023)
        )
        is False
    )


@pytest.mark.asyncio
async def test_state_as_datetime(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test state to datetime conversion."""

    assert document_creator.state_as_datetime(
        State("domain.entity_id", MOCK_NOON_APRIL_12TH_2023)
    ) == dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023)

    with pytest.raises(ValueError):
        document_creator.state_as_datetime(State("domain.entity_id", "tomato"))

    with pytest.raises(ValueError):
        document_creator.state_as_datetime(State("domain.entity_id", "1"))

    with pytest.raises(ValueError):
        document_creator.state_as_datetime(State("domain.entity_id", "0"))

    with pytest.raises(ValueError):
        document_creator.state_as_datetime(State("domain.entity_id", "on"))

    with pytest.raises(ValueError):
        document_creator.state_as_datetime(State("domain.entity_id", "off"))


async def test_try_state_as_datetime(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test state to datetime conversion."""

    assert (
        document_creator.try_state_as_datetime(State("domain.entity_id", "tomato"))
        is False
    )
    assert (
        document_creator.try_state_as_datetime(State("domain.entity_id", "1")) is False
    )
    assert (
        document_creator.try_state_as_datetime(State("domain.entity_id", "0")) is False
    )
    assert (
        document_creator.try_state_as_datetime(State("domain.entity_id", "on")) is False
    )
    assert (
        document_creator.try_state_as_datetime(State("domain.entity_id", "off"))
        is False
    )
    assert (
        document_creator.try_state_as_datetime(
            State("domain.entity_id", "2023-04-12T12:00:00Z")
        )
        is True
    )


async def test_state_to_entity_details(hass: HomeAssistant):
    """Test entity details creation."""
    es_url = "http://localhost:9200"

    mock_entry = MockConfigEntry(
        unique_id="test_entity_details",
        domain=DOMAIN,
        version=3,
        data=build_full_config({"url": es_url, CONF_INDEX_MODE: INDEX_MODE_LEGACY}),
        title="ES Config",
    )

    await _setup_config_entry(hass, mock_entry)

    entity_area = area_registry.async_get(hass).async_create("entity area")
    area_registry.async_get(hass).async_create("device area")

    dr = device_registry.async_get(hass)
    device = dr.async_get_or_create(
        config_entry_id=mock_entry.entry_id,
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

    creator = DocumentCreator(hass, mock_entry)

    document = creator._state_to_entity_details(hass.states.get(entity_id))

    expected = {
        "area": {"id": "entity_area", "name": "entity area"},
        "device": {
            "area": {"id": "device_area", "name": "device area"},
            "id": device.id,
            "name": "name",
        },
        "name": "My Test Counter",
        "platform": "counter",
    }

    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_state_to_attributes(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test state to attribute doc component creation."""

    class CustomAttributeClass:
        def __init__(self) -> None:
            self.field = "This class should be skipped, as it cannot be serialized."
            pass

    testAttributes = {
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
        "Collision Test": "first value",
        "collision_test": "second value",
        "*_Non ECS-Compliant    Attribute.ñame! 😀": True,
        # Keyless entry should be excluded from output
        "": "Key is empty, and should be excluded",
        # Custom classes should be excluded from output
        "naughty": CustomAttributeClass(),
        # Entries with non-string keys should be excluded from output
        datetime.now(): "Key is a datetime, and should be excluded",
        123: "Key is a number, and should be excluded",
        True: "Key is a bool, and should be excluded",
    }

    state = await create_and_return_state(hass, value="2", attributes=testAttributes)

    attributes = document_creator._state_to_attributes(state)

    expected = {
        "dict": '{"string":"abc123","int":123,"float":123.456}',
        "float": 123.456,
        "int": 123,
        "list": [1, 2, 3, 4],
        "none": None,
        "collision_test": "second value",
        "non_ecs_compliant_attribute_name": True,
        "set": [5],
        "string": "abc123",
    }

    assert diff(attributes, expected) == {}


@pytest.mark.asyncio
async def test_state_to_value_v1(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test state to value doc component creation."""

    assert document_creator._state_to_value_v1(State("sensor.test_1", "2")) == 2.0

    assert document_creator._state_to_value_v1(State("sensor.test_1", "2.0")) == 2.0
    assert document_creator._state_to_value_v1(State("sensor.test_1", "off")) == 0.0
    assert document_creator._state_to_value_v1(State("sensor.test_1", "on")) == 1.0
    assert (
        document_creator._state_to_value_v1(
            State("sensor.test_1", MOCK_NOON_APRIL_12TH_2023)
        )
        == MOCK_NOON_APRIL_12TH_2023
    )
    assert (
        document_creator._state_to_value_v1(State("sensor.test_1", "tomato"))
        == "tomato"
    )

    assert document_creator._state_to_value_v1(State("sensor.test_1", "true")) == "true"
    assert (
        document_creator._state_to_value_v1(State("sensor.test_1", "false")) == "false"
    )


@pytest.mark.asyncio
async def test_state_to_value_v2(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test state to value v2 doc component creation."""
    assert document_creator._state_to_value_v2(State("sensor.test_1", "2")) == {
        "value": "2",
        "valueas": {"float": 2.0},
    }

    assert document_creator._state_to_value_v2(State("sensor.test_1", "2.0")) == {
        "value": "2.0",
        "valueas": {"float": 2.0},
    }

    assert document_creator._state_to_value_v2(State("sensor.test_1", "off")) == {
        "value": "off",
        "valueas": {"boolean": False},
    }

    assert document_creator._state_to_value_v2(State("sensor.test_1", "on")) == {
        "value": "on",
        "valueas": {"boolean": True},
    }

    assert document_creator._state_to_value_v2(
        State("sensor.test_1", MOCK_NOON_APRIL_12TH_2023)
    ) == {
        "value": MOCK_NOON_APRIL_12TH_2023,
        "valueas": {
            "date": "2023-04-12",
            "datetime": "2023-04-12T12:00:00+00:00",
            "time": "12:00:00",
        },
    }

    assert document_creator._state_to_value_v2(State("sensor.test_1", "tomato")) == {
        "value": "tomato",
        "valueas": {"string": "tomato"},
    }

    assert document_creator._state_to_value_v2(State("sensor.test_1", "true")) == {
        "value": "true",
        "valueas": {"boolean": True},
    }

    assert document_creator._state_to_value_v2(State("sensor.test_1", "false")) == {
        "value": "false",
        "valueas": {"boolean": False},
    }


@pytest.mark.asyncio
async def test_v1_doc_creation_geolocation(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v1 document creation with geolocation."""

    hass.config.latitude = MOCK_LOCATION_SERVER["lat"]
    hass.config.longitude = MOCK_LOCATION_SERVER["lon"]

    await document_creator.async_init()

    # Mock a state object with attributes
    document = await create_and_return_document(
        hass,
        value="2",
        attributes={},
        document_creator=document_creator,
        version=1,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "agent.name": "My Home Assistant",
        "agent.type": "hass",
        "agent.version": "UNKNOWN",
        "ecs.version": "1.0.0",
        "hass.attributes": {},
        "hass.domain": "sensor",
        "hass.entity": {
            "attributes": {},
            "domain": "sensor",
            "id": "sensor.test_1",
            "value": 2.0,
        },
        "hass.entity_id": "sensor.test_1",
        "hass.entity_id_lower": "sensor.test_1",
        "hass.object_id": "test_1",
        "hass.object_id_lower": "test_1",
        "hass.value": 2.0,
        "host.architecture": "UNKNOWN",
        "host.hostname": "UNKNOWN",
        "host.os.name": "UNKNOWN",
        "tags": None,
        "host.geo.location": {
            "lat": MOCK_LOCATION_SERVER["lat"],
            "lon": MOCK_LOCATION_SERVER["lon"],
        },
    }

    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_v1_doc_creation_geolocation_from_attributes(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v1 document creation with geolocation."""

    hass.config.latitude = MOCK_LOCATION_SERVER["lat"]
    hass.config.longitude = MOCK_LOCATION_SERVER["lon"]

    await document_creator.async_init()

    # Mock a state object with attributes
    document = await create_and_return_document(
        hass,
        value="2",
        attributes={
            "latitude": MOCK_LOCATION_DEVICE["lat"],
            "longitude": MOCK_LOCATION_DEVICE["lon"],
        },
        document_creator=document_creator,
        version=1,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "agent.name": "My Home Assistant",
        "agent.type": "hass",
        "agent.version": "UNKNOWN",
        "ecs.version": "1.0.0",
        "hass.attributes": {
            "latitude": MOCK_LOCATION_DEVICE["lat"],
            "longitude": MOCK_LOCATION_DEVICE["lon"],
        },
        "hass.domain": "sensor",
        "hass.entity": {
            "attributes": {
                "latitude": MOCK_LOCATION_DEVICE["lat"],
                "longitude": MOCK_LOCATION_DEVICE["lon"],
            },
            "domain": "sensor",
            "id": "sensor.test_1",
            "value": 2.0,
        },
        "hass.entity_id": "sensor.test_1",
        "hass.entity_id_lower": "sensor.test_1",
        "hass.object_id": "test_1",
        "hass.object_id_lower": "test_1",
        "hass.value": 2.0,
        "host.architecture": "UNKNOWN",
        "host.hostname": "UNKNOWN",
        "host.os.name": "UNKNOWN",
        "tags": None,
        "host.geo.location": {
            "lat": MOCK_LOCATION_SERVER["lat"],
            "lon": MOCK_LOCATION_SERVER["lon"],
        },
        "hass.geo.location": {
            "lat": MOCK_LOCATION_DEVICE["lat"],
            "lon": MOCK_LOCATION_DEVICE["lon"],
        },
    }

    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_v1_doc_creation_attributes(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v1 document creation with attributes."""

    # Mock a state object with attributes
    document = await create_and_return_document(
        hass,
        value="2",
        attributes={"unit_of_measurement": "kg"},
        document_creator=document_creator,
        version=1,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.attributes": {"unit_of_measurement": "kg"},
        "hass.domain": "sensor",
        "hass.entity": {
            "attributes": {"unit_of_measurement": "kg"},
            "domain": "sensor",
            "id": "sensor.test_1",
            "value": 2.0,
        },
        "hass.entity_id": "sensor.test_1",
        "hass.entity_id_lower": "sensor.test_1",
        "hass.object_id": "test_1",
        "hass.object_id_lower": "test_1",
        "hass.value": 2.0,
    }

    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_v1_doc_creation_on_off_float(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v1 document creation with attributes."""
    document = await create_and_return_document(
        hass,
        domain="sensor",
        entity_id="test_1",
        value="off",
        attributes={},
        document_creator=document_creator,
        version=1,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.attributes": {},
        "hass.domain": "sensor",
        "hass.entity": {
            "attributes": {},
            "domain": "sensor",
            "id": "sensor.test_1",
            "value": 0,
        },
        "hass.entity_id": "sensor.test_1",
        "hass.entity_id_lower": "sensor.test_1",
        "hass.object_id": "test_1",
        "hass.object_id_lower": "test_1",
        "hass.value": 0,
    }

    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_v1_doc_creation_infinity(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v1 document creation with infinity number."""
    # Test infinityfloat coercion to Float
    document = await create_and_return_document(
        hass,
        domain="sensor",
        entity_id="test_1",
        value=float("inf"),
        attributes={},
        document_creator=document_creator,
        version=1,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.attributes": {},
        "hass.domain": "sensor",
        "hass.entity": {
            "attributes": {},
            "domain": "sensor",
            "id": "sensor.test_1",
            "value": "inf",
        },
        "hass.entity_id": "sensor.test_1",
        "hass.entity_id_lower": "sensor.test_1",
        "hass.object_id": "test_1",
        "hass.object_id_lower": "test_1",
        "hass.value": "inf",
    }

    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_v1_doc_creation_string_to_float(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v1 document creation with floats."""
    # Test float coercion to Float
    document = await create_and_return_document(
        hass,
        domain="sensor",
        entity_id="test_1",
        value="2.0",
        attributes={},
        document_creator=document_creator,
        version=1,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.attributes": {},
        "hass.domain": "sensor",
        "hass.entity": {
            "attributes": {},
            "domain": "sensor",
            "id": "sensor.test_1",
            "value": 2.0,
        },
        "hass.entity_id": "sensor.test_1",
        "hass.entity_id_lower": "sensor.test_1",
        "hass.object_id": "test_1",
        "hass.object_id_lower": "test_1",
        "hass.value": 2.0,
    }

    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_v1_doc_creation_leave_datetime_alone(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v1 document creation with dates."""

    document = await create_and_return_document(
        hass,
        value=MOCK_NOON_APRIL_12TH_2023,
        attributes={},
        document_creator=document_creator,
        version=1,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.attributes": {},
        "hass.domain": "sensor",
        "hass.entity": {
            "attributes": {},
            "domain": "sensor",
            "id": "sensor.test_1",
            "value": MOCK_NOON_APRIL_12TH_2023,
        },
        "hass.entity_id": "sensor.test_1",
        "hass.entity_id_lower": "sensor.test_1",
        "hass.object_id": "test_1",
        "hass.object_id_lower": "test_1",
        "hass.value": MOCK_NOON_APRIL_12TH_2023,
    }
    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_v2_doc_creation_geolocation(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v2 document creation with geolocation."""

    hass.config.latitude = MOCK_LOCATION_SERVER["lat"]
    hass.config.longitude = MOCK_LOCATION_SERVER["lon"]

    await document_creator.async_init()

    # Mock a state object with attributes
    document = await create_and_return_document(
        hass,
        value="2",
        attributes={},
        document_creator=document_creator,
        version=2,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "agent.name": "My Home Assistant",
        "agent.type": "hass",
        "ecs.version": "1.0.0",
        "hass.entity": {
            "attributes": {},
            "domain": "sensor",
            "id": "sensor.test_1",
            "value": "2",
            "valueas": {"float": 2.0},
            "geo.location": {
                "lat": MOCK_LOCATION_SERVER["lat"],
                "lon": MOCK_LOCATION_SERVER["lon"],
            },
        },
        "hass.object_id": "test_1",
        "host.geo.location": {
            "lat": MOCK_LOCATION_SERVER["lat"],
            "lon": MOCK_LOCATION_SERVER["lon"],
        },
        "tags": None,
    }

    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_v2_doc_creation_geolocation_from_attributes(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v2 document creation with geolocation."""

    hass.config.latitude = MOCK_LOCATION_SERVER["lat"]
    hass.config.longitude = MOCK_LOCATION_SERVER["lon"]

    await document_creator.async_init()

    # Mock a state object with attributes
    document = await create_and_return_document(
        hass,
        value="2",
        attributes={
            "latitude": MOCK_LOCATION_DEVICE["lat"],
            "longitude": MOCK_LOCATION_DEVICE["lon"],
        },
        document_creator=document_creator,
        version=2,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "agent.name": "My Home Assistant",
        "agent.type": "hass",
        "ecs.version": "1.0.0",
        "hass.entity": {
            "attributes": {
                "latitude": MOCK_LOCATION_DEVICE["lat"],
                "longitude": MOCK_LOCATION_DEVICE["lon"],
            },
            "geo.location": {
                "lat": MOCK_LOCATION_DEVICE["lat"],
                "lon": MOCK_LOCATION_DEVICE["lon"],
            },
            "domain": "sensor",
            "id": "sensor.test_1",
            "value": "2",
            "valueas": {"float": 2.0},
        },
        "hass.object_id": "test_1",
        "host.geo.location": {
            "lat": MOCK_LOCATION_SERVER["lat"],
            "lon": MOCK_LOCATION_SERVER["lon"],
        },
        "tags": None,
    }

    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_v2_doc_creation_attributes(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v2 document creation with attributes."""
    # Test v2 Document Creation with String Value and attribute
    document = await create_and_return_document(
        hass,
        value="tomato",
        attributes={"unit_of_measurement": "kg"},
        document_creator=document_creator,
        version=2,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.entity": {
            "attributes": {"unit_of_measurement": "kg"},
            "domain": "sensor",
            "geo.location": {
                "lat": MOCK_LOCATION_SERVER["lat"],
                "lon": MOCK_LOCATION_SERVER["lon"],
            },
            "id": "sensor.test_1",
            "value": "tomato",
            "valueas": {"string": "tomato"},
        },
        "hass.object_id": "test_1",
    }

    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_v2_doc_creation_float_as_string(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v2 document creation with stringified float value."""
    document = await create_and_return_document(
        hass,
        domain="sensor",
        entity_id="test_1",
        value="2.0",
        attributes={},
        document_creator=document_creator,
        version=2,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.entity": {
            "attributes": {},
            "domain": "sensor",
            "geo.location": {
                "lat": MOCK_LOCATION_SERVER["lat"],
                "lon": MOCK_LOCATION_SERVER["lon"],
            },
            "id": "sensor.test_1",
            "value": "2.0",
            "valueas": {"float": 2.0},
        },
        "hass.object_id": "test_1",
    }

    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_v2_doc_creation_float_infinity(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v2 document creation with infinity float."""
    # Test v2 Document Creation with invalid number Value
    document = await create_and_return_document(
        hass,
        domain="sensor",
        entity_id="test_1",
        value=float("inf"),
        attributes={},
        document_creator=document_creator,
        version=2,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.entity": {
            "attributes": {},
            "domain": "sensor",
            "geo.location": {
                "lat": MOCK_LOCATION_SERVER["lat"],
                "lon": MOCK_LOCATION_SERVER["lon"],
            },
            "id": "sensor.test_1",
            "value": "inf",
            "valueas": {"string": "inf"},
        },
        "hass.object_id": "test_1",
    }

    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_v2_doc_creation_float(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v2 document creation with Float."""
    document = await create_and_return_document(
        hass,
        domain="sensor",
        entity_id="test_1",
        value=2.0,
        attributes={},
        document_creator=document_creator,
        version=2,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.entity": {
            "attributes": {},
            "domain": "sensor",
            "geo.location": {
                "lat": MOCK_LOCATION_SERVER["lat"],
                "lon": MOCK_LOCATION_SERVER["lon"],
            },
            "id": "sensor.test_1",
            "value": "2.0",
            "valueas": {"float": 2.0},
        },
        "hass.object_id": "test_1",
    }

    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_v2_doc_creation_datetime(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v2 document creation with Datetime value."""

    testDateTimeString = MOCK_NOON_APRIL_12TH_2023
    testDateTime = dt_util.parse_datetime(testDateTimeString)

    document = await create_and_return_document(
        hass,
        value=testDateTimeString,
        attributes={},
        document_creator=document_creator,
        version=2,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.entity": {
            "attributes": {},
            "domain": "sensor",
            "geo.location": {
                "lat": MOCK_LOCATION_SERVER["lat"],
                "lon": MOCK_LOCATION_SERVER["lon"],
            },
            "id": "sensor.test_1",
            "value": testDateTimeString,
            "valueas": {
                "datetime": testDateTime.isoformat(),
                "date": testDateTime.date().isoformat(),
                "time": testDateTime.time().isoformat(),
            },
        },
        "hass.object_id": "test_1",
    }

    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_v2_doc_creation_boolean_truefalse(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v2 document creation with true/false coerced Boolean value."""
    document = await create_and_return_document(
        hass,
        domain="sensor",
        entity_id="test_1",
        value="true",
        attributes={},
        document_creator=document_creator,
        version=2,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.entity": {
            "attributes": {},
            "domain": "sensor",
            "geo.location": {
                "lat": MOCK_LOCATION_SERVER["lat"],
                "lon": MOCK_LOCATION_SERVER["lon"],
            },
            "id": "sensor.test_1",
            "value": "true",
            "valueas": {"boolean": True},
        },
        "hass.object_id": "test_1",
    }

    assert diff(document, expected) == {}


@pytest.mark.asyncio
async def test_v2_doc_creation_boolean_onoff(
    hass: HomeAssistant, document_creator: DocumentCreator
):
    """Test v2 document creation with on/off coerced to Boolean value."""
    document = await create_and_return_document(
        hass,
        domain="sensor",
        entity_id="test_1",
        value="off",
        attributes={},
        document_creator=document_creator,
        version=2,
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.entity": {
            "attributes": {},
            "domain": "sensor",
            "geo.location": {
                "lat": MOCK_LOCATION_SERVER["lat"],
                "lon": MOCK_LOCATION_SERVER["lon"],
            },
            "id": "sensor.test_1",
            "value": "off",
            "valueas": {"boolean": False},
        },
        "hass.object_id": "test_1",
    }

    assert diff(document, expected) == {}

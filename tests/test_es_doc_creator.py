"""Tests for the DocumentCreator class."""

from datetime import datetime
from unittest import mock

import pytest
from homeassistant.components import (
    counter,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import area_registry, device_registry, entity_registry
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from jsondiff import diff
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.extensions.json import JSONSnapshotExtension

from custom_components.elasticsearch.config_flow import (
    build_new_data,
)
from custom_components.elasticsearch.const import (
    CONF_INDEX_MODE,
    DOMAIN,
    INDEX_MODE_LEGACY,
)
from custom_components.elasticsearch.es_doc_creator import DocumentCreator
from custom_components.elasticsearch.system_info import SystemInfoResult
from tests.conftest import MockEntityState, mock_config_entry
from tests.const import (
    MOCK_LOCATION_DEVICE,
    MOCK_LOCATION_SERVER,
    MOCK_NOON_APRIL_12TH_2023,
)


@pytest.fixture(autouse=True)
def snapshot(snapshot):
    """Provide a pre-configured snapshot object."""

    return snapshot.with_defaults(extension_class=JSONSnapshotExtension)


@pytest.fixture(autouse=True)
def mock_system_info():
    """Fixture to skip returning system info."""

    async def get_system_info():
        return SystemInfoResult(
            version="2099.1.2",
            arch="Test Arch",
            hostname="Test Host",
            os_name="Test OS",
            os_version="v9.8.7",
        )

    with mock.patch(
        "custom_components.elasticsearch.system_info.SystemInfo.async_get_system_info",
        side_effect=get_system_info,
    ):
        yield None


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
        data=build_new_data({"url": es_url, CONF_INDEX_MODE: INDEX_MODE_LEGACY}),
        title="ES Config",
    )

    creator = DocumentCreator(hass, mock_entry)

    # TODO: Consider initializing the document creator before returning it, requires rewriting tests and initializing the whole integration
    # await creator.async_init()

    yield creator


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input,result,success",
    [
        (1, 1, True),
        (0, 0, True),
        ("on", 1, True),
        ("off", 0, True),
        ("1", 1, True),
        ("0", 0, True),
        ("1.0", 1.0, True),
        ("0.0", 0.0, True),
        ("2.0", 2.0, True),
        ("2", 2, True),
        ("tomato", None, False),
        (MOCK_NOON_APRIL_12TH_2023, None, False),
    ],
)
async def test_state_as_number(
    input: str | float,
    result: float | None,
    success: bool,
):
    """Test trying state to float conversion."""

    # Test Try First
    assert (
        DocumentCreator.try_state_as_number(State("domain.entity_id", input)) == success
    )

    # Test conversion which should throw an exception when success is False
    if not success:
        with pytest.raises(ValueError):
            DocumentCreator.state_as_number(State("domain.entity_id", input))
    else:
        assert (
            DocumentCreator.state_as_number(State("domain.entity_id", input)) == result
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input,result,success",
    [
        ("true", True, True),
        ("false", False, True),
        ("on", True, True),
        ("off", False, True),
        ("tomato", False, False),
        ("1", False, False),
        ("0", False, False),
        ("1.0", False, False),
        ("MOCK_NOON_APRIL_12TH_2023", False, False),
    ],
)
async def test_state_as_boolean(
    input: str | float,
    result: float | None,
    success: bool,
):
    """Test trying state to boolean conversion."""

    # Test Try First
    assert (
        DocumentCreator.try_state_as_boolean(State("domain.entity_id", input))
        == success
    )

    # Test conversion which should throw an exception when success is False
    if not success:
        with pytest.raises(ValueError):
            DocumentCreator.state_as_boolean(State("domain.entity_id", input))
    else:
        assert (
            DocumentCreator.state_as_boolean(State("domain.entity_id", input)) == result
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input,result,success",
    [
        (
            MOCK_NOON_APRIL_12TH_2023,
            dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
            True,
        ),
        ("tomato", None, False),
        ("1", None, False),
        ("0", None, False),
        ("1.0", None, False),
        ("on", None, False),
        ("off", None, False),
    ],
)
async def test_state_as_datetime(
    input: str | float,
    result,
    success: bool,
):
    """Test trying state to datetime conversion."""

    # Test Try First
    assert (
        DocumentCreator.try_state_as_datetime(State("domain.entity_id", input))
        == success
    )

    # Test conversion which should throw an exception when success is False
    if not success:
        with pytest.raises(ValueError):
            DocumentCreator.state_as_datetime(State("domain.entity_id", input))
    else:
        assert (
            DocumentCreator.state_as_datetime(State("domain.entity_id", input))
            == result
        )


async def test_state_to_entity_details(hass: HomeAssistant, snapshot: snapshot):
    """Test entity details creation."""
    es_url = "http://localhost:9200"

    mock_entry = MockConfigEntry(
        unique_id="test_entity_details",
        domain=DOMAIN,
        version=3,
        data=build_new_data({"url": es_url, CONF_INDEX_MODE: INDEX_MODE_LEGACY}),
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

    # Delete the id field from the document dict
    del document["device"]["id"]

    assert document == snapshot


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

    state = MockEntityState(
        hass, entity_id="test.test_1", state="2", attributes=testAttributes
    )

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
@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize(
    "state, attributes",
    [
        (2, {}),
        (2.0, {}),
        (float("inf"), {}),
        (
            "2",
            {
                "latitude": MOCK_LOCATION_DEVICE["lat"],
                "longitude": MOCK_LOCATION_DEVICE["lon"],
            },
        ),
        ("2.0", {}),
        ("off", {}),
        ("on", {}),
        (dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023), {}),
        (MOCK_NOON_APRIL_12TH_2023, {}),
        ("tomato", {}),
        ("true", {}),
        (True, {}),
        (False, {}),
    ],
)
async def test_state_to_document(
    hass: HomeAssistant,
    document_creator: DocumentCreator,
    snapshot,
    state,
    attributes,
    version,
):
    """Test Doc Creation."""

    entity_state = MockEntityState(
        hass,
        entity_id="sensor.test_1",
        state=state,
        attributes=attributes,
        last_changed=dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        last_updated=dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
    )

    document = document_creator.state_to_document(
        entity_state,
        dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "testing",
        version,
    )

    assert {
        "state": state,
        "entity state": entity_state.as_dict(),
        "document": document,
        "version": version,
    } == snapshot


@pytest.mark.asyncio
async def test_state_to_document_no_tz(
    hass: HomeAssistant, document_creator: DocumentCreator, snapshot
):
    """Test Doc Creation."""

    entity_state = MockEntityState(
        hass,
        entity_id="sensor.test_1",
        state="1",
        attributes={},
        last_changed=dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        last_updated=dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
    )

    document = document_creator.state_to_document(
        entity_state,
        dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023).replace(tzinfo=None),
        "testing",
        1,
    )

    assert document == snapshot

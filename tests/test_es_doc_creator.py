"""Tests for the DocumentPublisher class."""

from datetime import datetime
from unittest import mock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.dt import UTC
from jsondiff import diff
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.elasticsearch.config_flow import build_full_config
from custom_components.elasticsearch.const import (
    CONF_INDEX_MODE,
    DOMAIN,
    INDEX_MODE_LEGACY,
)
from custom_components.elasticsearch.es_doc_creator import DocumentCreator
from tests.const import MOCK_NOON_APRIL_12TH_2023


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


@pytest.mark.asyncio
async def test_v1_doc_creation(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test v1 document creation."""
    es_url = "http://localhost:9200"

    mock_entry = MockConfigEntry(
        unique_id="test_publish_state_change",
        domain=DOMAIN,
        version=3,
        data=build_full_config({"url": es_url, CONF_INDEX_MODE: INDEX_MODE_LEGACY}),
        title="ES Config",
    )

    # Initialize a document creator
    creator = DocumentCreator(hass, mock_entry)

    # Mock a state object
    hass.states.async_set("sensor.test_1", "2", {"unit_of_measurement": "kg"}, True)
    await hass.async_block_till_done()
    _state = hass.states.get("sensor.test_1")

    # Test v1 Document Creation

    document = creator.state_to_document(
        _state, dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023), version=1
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

    # Test on/off coercion to Float

    hass.states.async_set("sensor.test_1", "off", {"unit_of_measurement": "kg"}, True)
    await hass.async_block_till_done()
    _state = hass.states.get("sensor.test_1")

    document = creator.state_to_document(
        _state, dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023), version=1
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.attributes": {"unit_of_measurement": "kg"},
        "hass.domain": "sensor",
        "hass.entity": {
            "attributes": {"unit_of_measurement": "kg"},
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

    # Test date handling to Float

    hass.states.async_set(
        "sensor.test_1", MOCK_NOON_APRIL_12TH_2023, {"unit_of_measurement": "kg"}, True
    )
    await hass.async_block_till_done()
    _state = hass.states.get("sensor.test_1")

    document = creator.state_to_document(
        _state, dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023), version=1
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.attributes": {"unit_of_measurement": "kg"},
        "hass.domain": "sensor",
        "hass.entity": {
            "attributes": {"unit_of_measurement": "kg"},
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
async def test_v2_doc_creation(
    hass: HomeAssistant, es_aioclient_mock: AiohttpClientMocker
):
    """Test v2 document creation."""
    es_url = "http://localhost:9200"

    mock_entry = MockConfigEntry(
        unique_id="test_publish_state_change",
        domain=DOMAIN,
        version=3,
        data=build_full_config({"url": es_url, CONF_INDEX_MODE: INDEX_MODE_LEGACY}),
        title="ES Config",
    )

    # Initialize a document creator
    creator = DocumentCreator(hass, mock_entry)

    # Test v2 Document Creation with String Value
    hass.states.async_set(
        "sensor.test_1", "tomato", {"unit_of_measurement": "kg"}, True
    )
    await hass.async_block_till_done()
    _state = hass.states.get("sensor.test_1")

    document = creator.state_to_document(
        _state, dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023), version=2
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.entity": {
            "attributes": {"unit_of_measurement": "kg"},
            "domain": "sensor",
            "id": "sensor.test_1",
            "value": "tomato",
            "valueas": {"string": "tomato"},
        },
        "hass.object_id": "test_1",
    }

    assert diff(document, expected) == {}

    # Test v2 Document Creation with stringed Float Value
    hass.states.async_set("sensor.test_1", "2.0", {"unit_of_measurement": "kg"}, True)
    await hass.async_block_till_done()
    _state = hass.states.get("sensor.test_1")

    document = creator.state_to_document(
        _state, dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023), version=2
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.entity": {
            "attributes": {"unit_of_measurement": "kg"},
            "domain": "sensor",
            "id": "sensor.test_1",
            "value": "2.0",
            "valueas": {"float": 2.0},
        },
        "hass.object_id": "test_1",
    }

    assert diff(document, expected) == {}

    # Test v2 Document Creation with Float Value
    hass.states.async_set("sensor.test_1", 2.0, {"unit_of_measurement": "kg"}, True)
    await hass.async_block_till_done()
    _state = hass.states.get("sensor.test_1")

    document = creator.state_to_document(
        _state, dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023), version=2
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.entity": {
            "attributes": {"unit_of_measurement": "kg"},
            "domain": "sensor",
            "id": "sensor.test_1",
            "value": "2.0",
            "valueas": {"float": 2.0},
        },
        "hass.object_id": "test_1",
    }

    assert diff(document, expected) == {}

    # Test v2 Document Creation with Datetime Value
    testDateTimeString = MOCK_NOON_APRIL_12TH_2023
    testDateTime = dt_util.parse_datetime(testDateTimeString)

    hass.states.async_set(
        "sensor.test_1",
        testDateTimeString,
        {"unit_of_measurement": "kg"},
        True,
    )
    await hass.async_block_till_done()
    _state = hass.states.get("sensor.test_1")
    document = creator.state_to_document(
        _state, dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023), version=2
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.entity": {
            "attributes": {"unit_of_measurement": "kg"},
            "domain": "sensor",
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

    # Test v2 Document Creation with Boolean Value
    testDateTimeString = MOCK_NOON_APRIL_12TH_2023
    testDateTime = dt_util.parse_datetime(testDateTimeString)

    hass.states.async_set(
        "sensor.test_1",
        "off",
        {"unit_of_measurement": "kg"},
        True,
    )
    await hass.async_block_till_done()
    _state = hass.states.get("sensor.test_1")
    document = creator.state_to_document(
        _state, dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023), version=2
    )

    expected = {
        "@timestamp": dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
        "hass.entity": {
            "attributes": {"unit_of_measurement": "kg"},
            "domain": "sensor",
            "id": "sensor.test_1",
            "value": "off",
            "valueas": {"boolean": False},
        },
        "hass.object_id": "test_1",
    }

    assert diff(document, expected) == {}

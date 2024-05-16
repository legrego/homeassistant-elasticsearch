"""Test Entity Details."""

import pytest
from homeassistant.components.counter import DOMAIN as COUNTER_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry,
    device_registry,
    entity_registry,
    floor_registry,
    label_registry,
)
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.elasticsearch.entity_details import (
    EntityDetails,
    FullEntityDetails,
)


@pytest.mark.asyncio
async def test_missing_entity(hass: HomeAssistant):
    """Verify missing entity returns None."""
    instance = EntityDetails(hass)

    assert instance.async_get("unknown_entity_id") is None


@pytest.mark.asyncio
async def test_entity_without_device(hass: HomeAssistant):
    """Entity without device returns details."""
    config = {COUNTER_DOMAIN: {"test_1": {}}}
    assert await async_setup_component(hass, COUNTER_DOMAIN, config)
    await hass.async_block_till_done()
    entity_id = "counter.test_1"

    state = hass.states.get(entity_id)
    assert int(state.state) == 0

    instance = EntityDetails(hass)

    deets = instance.async_get(entity_id)
    assert isinstance(deets, FullEntityDetails) is True

    assert deets.entity.entity_id == entity_id
    assert deets.entity.domain == COUNTER_DOMAIN
    assert deets.entity_area is None
    assert deets.device is None
    assert deets.device_area is None


@pytest.mark.asyncio
async def test_entity_with_area(hass: HomeAssistant):
    """Entity without device returns details."""
    area = area_registry.async_get(hass).async_create("mock")

    config = {COUNTER_DOMAIN: {"test_1": {}}}
    assert await async_setup_component(hass, COUNTER_DOMAIN, config)
    entity_id = "counter.test_1"
    entity_registry.async_get(hass).async_update_entity(entity_id, area_id=area.id)

    state = hass.states.get(entity_id)
    assert int(state.state) == 0

    instance = EntityDetails(hass)

    deets = instance.async_get(entity_id)
    assert isinstance(deets, FullEntityDetails) is True

    assert deets.entity.entity_id == entity_id
    assert deets.entity.domain == COUNTER_DOMAIN
    assert isinstance(deets.entity_area, area_registry.AreaEntry) is True
    assert deets.entity_area.id == area.id
    assert deets.entity_area.name == area.name

    assert deets.device is None
    assert deets.device_area is None


@pytest.mark.asyncio
async def test_entity_with_device(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    """Entity with device returns details."""
    entity_area = area_registry.async_get(hass).async_create("entity area")
    device_area = area_registry.async_get(hass).async_create("device area")

    dr = device_registry.async_get(hass)
    entry = dr.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        connections={(device_registry.CONNECTION_NETWORK_MAC, "12:34:56:AB:CD:EF")},
        identifiers={("bridgeid", "0123")},
        sw_version="sw-version",
        name="name",
        manufacturer="manufacturer",
        model="model",
        suggested_area="device area",
    )

    config = {COUNTER_DOMAIN: {"test_1": {}}}
    assert await async_setup_component(hass, COUNTER_DOMAIN, config)
    entity_id = "counter.test_1"
    entity_registry.async_get(hass).async_update_entity(
        entity_id, area_id=entity_area.id, device_id=entry.id
    )

    state = hass.states.get(entity_id)
    assert int(state.state) == 0

    instance = EntityDetails(hass)

    deets = instance.async_get(entity_id)
    assert isinstance(deets, FullEntityDetails) is True

    assert deets.entity.entity_id == entity_id
    assert deets.entity.domain == COUNTER_DOMAIN
    assert isinstance(deets.entity_area, area_registry.AreaEntry) is True
    assert deets.entity_area.id == entity_area.id
    assert deets.entity_area.name == entity_area.name

    assert isinstance(deets.device, device_registry.DeviceEntry) is True
    assert isinstance(deets.device_area, area_registry.AreaEntry) is True
    assert deets.device.id == entry.id
    assert deets.device.name == entry.name
    assert deets.device_area.id == device_area.id
    assert deets.device_area.name == device_area.name


@pytest.mark.asyncio
async def test_entity_with_floor_and_labels(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    """Entity with device returns details."""
    device_floor = floor_registry.async_get(hass).async_create("device floor")
    entity_floor = floor_registry.async_get(hass).async_create("entity_floor")

    entity_area = area_registry.async_get(hass).async_create(
        "entity area", floor_id=entity_floor.floor_id
    )
    device_area = area_registry.async_get(hass).async_create(
        "device area", floor_id=device_floor.floor_id
    )

    label_registry.async_get(hass).async_create("device label")
    label_registry.async_get(hass).async_create("entity label")

    dr = device_registry.async_get(hass)
    entry = dr.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        connections={(device_registry.CONNECTION_NETWORK_MAC, "12:34:56:AB:CD:EF")},
        identifiers={("bridgeid", "0123")},
        sw_version="sw-version",
        name="name",
        manufacturer="manufacturer",
        model="model",
        suggested_area="device area",
    )

    dr.async_update_device(device_id=entry.id, labels={"device label"})

    config = {COUNTER_DOMAIN: {"test_1": {}}}
    assert await async_setup_component(hass, COUNTER_DOMAIN, config)
    entity_id = "counter.test_1"
    entity_registry.async_get(hass).async_update_entity(
        entity_id, area_id=entity_area.id, device_id=entry.id, labels={"entity label"}
    )

    state = hass.states.get(entity_id)
    assert int(state.state) == 0

    instance = EntityDetails(hass)

    deets = instance.async_get(entity_id)
    assert isinstance(deets, FullEntityDetails) is True

    # Deets = FullEntityDetails(entity=RegistryEntry(entity_id='counter.test_1', unique_id='test_1', platform='counter', previous_unique_id=None, aliases=set(), area_id='entity_area', categories={}, capabilities=None, config_entry_id=None, device_class=None, device_id='12149f90d33242dd66a8997d9a67cfed', disabled_by=None, entity_category=None, hidden_by=None, icon=None, id='58ef0ee276405cab93f8fd0fa345fbf2', has_entity_name=False, labels={'entity label'}, name=None, options={}, original_device_class=None, original_icon=None, original_name=None, supported_features=0, translation_key=None, unit_of_measurement=None)
    # Write assertions for the FullEntityDetails object but exclude ephemeral values like id, unique_id, etc.

    assert deets.entity.entity_id == entity_id
    assert deets.entity.domain == COUNTER_DOMAIN
    assert isinstance(deets.entity_area, area_registry.AreaEntry) is True
    assert deets.entity_area.id == entity_area.id
    assert deets.entity_area.name == entity_area.name
    assert deets.entity_floor == entity_floor

    assert isinstance(deets.device, device_registry.DeviceEntry) is True
    assert isinstance(deets.device_area, area_registry.AreaEntry) is True
    assert deets.device.id == entry.id
    assert deets.device.name == entry.name
    assert deets.device_area.id == device_area.id
    assert deets.device_area.name == device_area.name

    assert deets.device_labels == ["device label"]
    assert deets.entity_labels == ["entity label"]
    assert deets.device_floor == device_floor

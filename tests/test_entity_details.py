"""Test Entity Details."""

import pytest
from homeassistant.components.counter import DOMAIN as COUNTER_DOMAIN
from homeassistant.helpers import area_registry, device_registry, entity_registry
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.elasticsearch.entity_details import (
    EntityDetails,
    FullEntityDetails,
)


@pytest.mark.asyncio
async def test_missing_entity(hass: HomeAssistantType):
    """Verify missing entity returns None."""
    instance = EntityDetails(hass)

    assert instance.async_get("unknown_entity_id") is None

@pytest.mark.asyncio
async def test_entity_without_device(hass: HomeAssistantType):
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
async def test_entity_with_area(hass: HomeAssistantType):
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
async def test_entity_with_device(hass: HomeAssistantType, mock_config_entry: MockConfigEntry):
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
    entity_registry.async_get(hass).async_update_entity(entity_id, area_id=entity_area.id, device_id=entry.id)

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

"""Sensor entities backed by independently configured ES|QL queries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity, UpdateFailed
from homeassistant.util import dt as dt_util

from .coordinator import QuerySensorCoordinator
from .query_sensor import SUBENTRY_TYPE

if TYPE_CHECKING:  # pragma: no cover
    from homeassistant.config_entries import ConfigSubentry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import ElasticIntegrationConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElasticIntegrationConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add saved queries even when one query is temporarily unavailable."""
    registry = dr.async_get(hass)
    info = entry.runtime_data.device_info
    subentries = [
        subentry for subentry in entry.subentries.values() if subentry.subentry_type == SUBENTRY_TYPE
    ]
    if not subentries:
        if device := registry.async_get_device(identifiers=info["identifiers"]):
            if device.config_entry_id == entry.entry_id:
                registry.async_remove_device(device.id)
        return
    # A service shared by subentries belongs to the parent connection, not to
    # any one saved query. Passing device_info per entity would move its ownership.
    device = registry.async_get_or_create(config_entry_id=entry.entry_id, config_subentry_id=None, **info)
    for subentry in subentries:
        coordinator = QuerySensorCoordinator(hass, entry, subentry)
        entry.runtime_data.coordinators[subentry.subentry_id] = coordinator
        # async_refresh deliberately avoids turning an individual query failure into
        # ConfigEntryNotReady, which would prevent unrelated sensors from loading.
        await coordinator.async_refresh()
        async_add_entities(
            [QuerySensor(coordinator, subentry, device)], config_subentry_id=subentry.subentry_id
        )


class QuerySensor(CoordinatorEntity[QuerySensorCoordinator], SensorEntity):
    """Expose a scalar, with an independent deadline for source freshness."""

    _attr_has_entity_name = True
    _attr_translation_key = "query"

    def __init__(
        self, coordinator: QuerySensorCoordinator, subentry: ConfigSubentry, device: dr.DeviceEntry
    ) -> None:
        """Identity belongs to the saved query, never to its name or text."""
        super().__init__(coordinator)
        self._attr_unique_id = subentry.subentry_id
        self._attr_name = subentry.title
        self.device_entry = device
        self._attr_native_unit_of_measurement = subentry.data.get("unit_of_measurement")
        self._attr_device_class = subentry.data.get("device_class")
        self._attr_state_class = subentry.data.get("state_class")
        self._cancel_expiry: Callable[[], None] | None = None

    @property
    def available(self) -> bool:
        """Expire the source reading even if later fetches return identical values."""
        reading = self.coordinator.data
        return (
            super().available
            and bool(reading)
            and (reading.expires_at is None or reading.expires_at > dt_util.utcnow())
        )

    @property
    def native_value(self) -> str | int | float | date | datetime | None:
        """Return only the selected value."""
        return self.coordinator.data.value if self.coordinator.data else None

    async def async_added_to_hass(self) -> None:
        """Start watching coordinator updates and the current freshness deadline."""
        await super().async_added_to_hass()
        self._schedule_expiry()

    async def async_will_remove_from_hass(self) -> None:
        """Remove the deadline and coordinator listener."""
        self._clear_expiry()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._schedule_expiry()
        super()._handle_coordinator_update()

    @callback
    def _clear_expiry(self) -> None:
        if self._cancel_expiry is not None:
            self._cancel_expiry()
            self._cancel_expiry = None

    @callback
    def _schedule_expiry(self) -> None:
        self._clear_expiry()
        reading = self.coordinator.data
        if self.available and reading.expires_at is not None:
            self._cancel_expiry = async_track_point_in_utc_time(self.hass, self._expire, reading.expires_at)

    @callback
    def _expire(self, now: datetime) -> None:
        self._cancel_expiry = None
        self.coordinator.async_set_update_error(
            UpdateFailed(translation_domain="elasticsearch", translation_key="sensor_stale")
        )

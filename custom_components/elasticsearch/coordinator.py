"""Independent, bounded polling for saved ES|QL queries."""

from __future__ import annotations

from datetime import timedelta
from time import monotonic
from typing import TYPE_CHECKING, Any

from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .errors import AuthenticationRequired, InsufficientPrivileges
from .logger import LOGGER
from .query_sensor import CONF_INTERVAL, SensorReading, error_code, read_sensor_result

if TYPE_CHECKING:  # pragma: no cover
    from homeassistant.config_entries import ConfigSubentry
    from homeassistant.core import HomeAssistant

    from . import ElasticIntegrationConfigEntry

# These problems persist until the saved mapping, permissions, or cluster changes.
REPAIR_ERRORS = {
    "multiple_rows",
    "missing_column",
    "invalid_value",
    "invalid_metadata",
    "invalid_freshness",
    "invalid_timestamp",
    "query_warnings",
    "query_rejected",
    "query_not_supported",
    "insufficient_privileges",
}


class QuerySensorCoordinator(DataUpdateCoordinator[SensorReading]):
    """Poll one sensor without letting its failures block another sensor or publishing."""

    def __init__(
        self, hass: HomeAssistant, entry: ElasticIntegrationConfigEntry, subentry: ConfigSubentry
    ) -> None:
        """Use opaque IDs in logs and diagnostics; user names can contain sensitive data."""
        super().__init__(
            hass,
            LOGGER,
            name=f"Elasticsearch query {subentry.subentry_id}",
            config_entry=entry,
            update_interval=timedelta(seconds=subentry.data.get(CONF_INTERVAL, 60)),
        )
        self.entry = entry
        self.subentry = subentry
        self.last_error: str | None = None
        self.last_duration: float | None = None
        self.last_success: str | None = None
        self.took_ms: int | None = None
        self.issue_id = f"query_sensor_{entry.entry_id}_{subentry.subentry_id}"

    async def _async_update_data(self) -> SensorReading:
        """Fetch and validate a reading, retaining only sanitized failure categories."""
        started = monotonic()
        try:
            result = await self.entry.runtime_data.query_runner.async_query(
                self.subentry.data["query"], self.subentry.data.get("params", [])
            )
            self.took_ms = result.took_ms
            reading = read_sensor_result(result, self.subentry.data)
        except Exception as err:  # noqa: BLE001
            self.last_error = code = error_code(err)
            if isinstance(err, AuthenticationRequired) and not isinstance(err, InsufficientPrivileges):
                self.entry.async_start_reauth(self.hass)
            if code in REPAIR_ERRORS:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    self.issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=f"sensor_{code}",
                    translation_placeholders={"sensor": self.subentry.title},
                )
            raise UpdateFailed(translation_domain=DOMAIN, translation_key=f"sensor_{code}") from None
        finally:
            self.last_duration = round(monotonic() - started, 3)
        self.last_error = None
        self.last_success = dt_util.utcnow().isoformat()
        ir.async_delete_issue(self.hass, DOMAIN, self.issue_id)
        return reading

    def diagnostics(self) -> dict[str, Any]:
        """Report operational status without query text, values, or column names."""
        stale = bool(self.data and self.data.expires_at and self.data.expires_at <= dt_util.utcnow())
        return {
            "available": self.last_update_success and not stale,
            "error": "stale" if stale else self.last_error,
            "last_success": self.last_success,
            "duration_seconds": self.last_duration,
            "took_ms": self.took_ms,
            "interval_seconds": self.subentry.data.get(CONF_INTERVAL, 60),
        }

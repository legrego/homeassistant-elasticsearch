"""Validate saved query mappings without exposing query data in errors."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.components.sensor.const import (
    DEVICE_CLASS_STATE_CLASSES,
    DEVICE_CLASS_UNITS,
    NON_NUMERIC_DEVICE_CLASSES,
)
from homeassistant.util import dt as dt_util

from .errors import (
    AuthenticationRequired,
    BadRequest,
    CannotConnect,
    InsufficientPrivileges,
    QueryNotSupported,
    RequestTimeout,
)
from .esql import QueryResult

CONF_VALUE_COLUMN = "value_column"
CONF_TIMESTAMP_COLUMN = "timestamp_column"
CONF_MAX_AGE = "max_age"
CONF_INTERVAL = "scan_interval"
SUBENTRY_TYPE = "query_sensor"
NUMERIC_TYPES = {
    "byte",
    "short",
    "integer",
    "long",
    "unsigned_long",
    "double",
    "float",
    "half_float",
    "scaled_float",
    "counter_long",
    "counter_double",
    "counter_integer",
}
TEXT_TYPES = {"keyword", "text", "ip", "version", "date", "date_nanos"}
DATETIME_DEVICE_CLASSES = {SensorDeviceClass.TIMESTAMP, SensorDeviceClass.UPTIME}
SUPPORTED_DEVICE_CLASSES = sorted(item.value for item in SensorDeviceClass if item != SensorDeviceClass.ENUM)


class SensorQueryError(Exception):
    """An error identified by a translation key, never by user data."""

    def __init__(self, code: str) -> None:
        """Keep only the public, non-sensitive error category."""
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SensorReading:
    """A scalar reading and its optional expiry; never arbitrary result attributes."""

    value: str | int | float | date | datetime | None
    expires_at: datetime | None = None


def error_code(error: Exception) -> str:
    """Classify failures without propagating server messages or result values."""
    if isinstance(error, SensorQueryError):
        return error.code
    if isinstance(error, InsufficientPrivileges):
        return "insufficient_privileges"
    if isinstance(error, AuthenticationRequired):
        return "authentication_failed"
    if isinstance(error, QueryNotSupported):
        return "query_not_supported"
    if isinstance(error, BadRequest):
        return "query_rejected"
    if isinstance(error, RequestTimeout):
        return "query_timeout"
    if isinstance(error, CannotConnect):
        return "cannot_connect"
    return "query_failed"


def validate_result(result: QueryResult) -> None:
    """Check the contract shared by previews and sensor updates."""
    if len(result.rows) > 1:
        raise SensorQueryError("multiple_rows")
    # The shared layer already rejects a result that actually reaches a default LIMIT.
    # Any other warning could indicate ignored values or failed calculations.
    if any(
        not warning.startswith("No limit defined, adding default limit of [") for warning in result.warnings
    ):
        raise SensorQueryError("query_warnings")


def validate_metadata(config: Mapping[str, Any]) -> None:
    """Reject metadata combinations Home Assistant cannot represent correctly."""
    device_class = config.get("device_class")
    unit = config.get("unit_of_measurement")
    state_class = config.get("state_class")
    if device_class and device_class not in SUPPORTED_DEVICE_CLASSES:
        raise SensorQueryError("invalid_metadata")
    if state_class and state_class not in SensorStateClass:
        raise SensorQueryError("invalid_metadata")
    if device_class:
        units = DEVICE_CLASS_UNITS.get(device_class)
        if (units is not None and unit not in units) or (device_class in NON_NUMERIC_DEVICE_CLASSES and unit):
            raise SensorQueryError("invalid_metadata")
        if state_class and state_class not in DEVICE_CLASS_STATE_CLASSES.get(device_class, set()):
            raise SensorQueryError("invalid_metadata")
    if bool(config.get(CONF_TIMESTAMP_COLUMN)) != bool(config.get(CONF_MAX_AGE)):
        raise SensorQueryError("invalid_freshness")


def _timestamp(value: Any) -> datetime:
    """Accept only explicit timezone-aware timestamps, including date_nanos strings."""
    parsed = dt_util.parse_datetime(value) if isinstance(value, str) else None
    if parsed is None or parsed.tzinfo is None:
        raise SensorQueryError("invalid_timestamp")
    return dt_util.as_utc(parsed)


def read_sensor_result(result: QueryResult, config: Mapping[str, Any]) -> SensorReading:
    """Select a single scalar, checking even an empty result's column metadata."""
    validate_result(result)
    validate_metadata(config)
    columns = {column.name: column.type for column in result.columns}
    column = config[CONF_VALUE_COLUMN]
    if column not in columns:
        raise SensorQueryError("missing_column")
    column_type = columns[column]
    if column_type not in NUMERIC_TYPES | TEXT_TYPES | {"null"}:
        raise SensorQueryError("invalid_value")
    timestamp_column = config.get(CONF_TIMESTAMP_COLUMN)
    if timestamp_column and columns.get(timestamp_column) not in {"date", "date_nanos"}:
        raise SensorQueryError("invalid_timestamp")
    device_class = config.get("device_class")
    numeric = bool(
        config.get("unit_of_measurement")
        or config.get("state_class")
        or (device_class and device_class not in NON_NUMERIC_DEVICE_CLASSES)
    )
    if numeric and column_type not in NUMERIC_TYPES | {"null"}:
        raise SensorQueryError("invalid_value")
    if device_class in NON_NUMERIC_DEVICE_CLASSES and column_type not in {
        "date",
        "date_nanos",
        "null",
    }:
        raise SensorQueryError("invalid_value")
    if not result.rows:
        return SensorReading(None)
    row = result.rows[0]
    value = row.get(column)
    # A null observation is unknown, with no reading that needs an expiry timer.
    if value is None:
        return SensorReading(None)
    expires_at = None
    if timestamp_column:
        observed_at = _timestamp(row.get(timestamp_column))
        expires_at = observed_at + timedelta(seconds=config[CONF_MAX_AGE])
        if observed_at > dt_util.utcnow():
            raise SensorQueryError("invalid_timestamp")
        if expires_at <= dt_util.utcnow():
            raise SensorQueryError("stale")
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise SensorQueryError("invalid_value")
    if column_type in NUMERIC_TYPES:
        if not isinstance(value, int | float) or not math.isfinite(value):
            raise SensorQueryError("invalid_value")
    elif not isinstance(value, str) or len(value) > 255:
        raise SensorQueryError("invalid_value")
    if device_class in DATETIME_DEVICE_CLASSES:
        value = _timestamp(value)
    elif device_class == SensorDeviceClass.DATE:
        value = _timestamp(value).date()
    return SensorReading(value, expires_at)

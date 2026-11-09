"""Contracts for sensor values, metadata, warnings, and observation age."""

from datetime import date, datetime, timedelta

import pytest
from custom_components.elasticsearch.esql import QueryColumn, QueryResult
from custom_components.elasticsearch.query_sensor import SensorQueryError, read_sensor_result
from homeassistant.util import dt as dt_util


def result(value=0, column_type="double", *, rows=None, warnings=None):
    """Build a normalized result with an extra observation column."""
    return QueryResult(
        [QueryColumn("value", column_type), QueryColumn("observed", "date_nanos")],
        [{"value": value, "observed": dt_util.utcnow().isoformat()}] if rows is None else rows,
        warnings or [],
        5,
    )


@pytest.mark.parametrize(
    ("value", "column_type", "expected"),
    [
        (0, "double", 0),
        (1.5, "double", 1.5),
        (None, "double", None),
        (None, "null", None),
        ("ready", "keyword", "ready"),
        (255 * "x", "keyword", 255 * "x"),
    ],
)
def test_scalar(value, column_type, expected):
    """Null remains unknown, zero remains zero, and supported scalars pass through."""
    assert read_sensor_result(result(value, column_type), {"value_column": "value"}).value == expected


@pytest.mark.parametrize(
    ("response", "config", "code"),
    [
        (result(rows=[{"value": 1}, {"value": 2}]), {}, "multiple_rows"),
        (result(warnings=["invalid value SECRET"]), {}, "query_warnings"),
        (result(), {"value_column": "gone"}, "missing_column"),
        (result(True, "boolean"), {}, "invalid_value"),
        (result([1], "double"), {}, "invalid_value"),
        (result({"a": 1}, "keyword"), {}, "invalid_value"),
        (result(True), {}, "invalid_value"),
        (result(float("inf")), {}, "invalid_value"),
        (result(float("nan")), {}, "invalid_value"),
        (result("3"), {}, "invalid_value"),
        (result(3, "keyword"), {}, "invalid_value"),
        (result("x" * 256, "keyword"), {}, "invalid_value"),
        (result("ready", "keyword"), {"state_class": "measurement"}, "invalid_value"),
        (result(), {"device_class": "temperature", "unit_of_measurement": "bananas"}, "invalid_metadata"),
        (
            result(),
            {"device_class": "temperature", "unit_of_measurement": "°C", "state_class": "total_increasing"},
            "invalid_metadata",
        ),
        (result(), {"device_class": "timestamp", "unit_of_measurement": "s"}, "invalid_metadata"),
        (result(), {"device_class": "not-a-class"}, "invalid_metadata"),
        (result(), {"state_class": "not-a-class"}, "invalid_metadata"),
        (result(), {"timestamp_column": "observed"}, "invalid_freshness"),
        (result(), {"max_age": 30}, "invalid_freshness"),
        (result(), {"timestamp_column": "missing", "max_age": 30}, "invalid_timestamp"),
        (result(), {"device_class": "timestamp"}, "invalid_value"),
        (
            result(rows=[{"value": 2, "observed": "garbage"}]),
            {"timestamp_column": "observed", "max_age": 30},
            "invalid_timestamp",
        ),
        (
            result(rows=[{"value": 2, "observed": "2026-01-01T00:00:00"}]),
            {"timestamp_column": "observed", "max_age": 30},
            "invalid_timestamp",
        ),
        (
            result(rows=[{"value": 2, "observed": None}]),
            {"timestamp_column": "observed", "max_age": 30},
            "invalid_timestamp",
        ),
    ],
)
def test_invalid_results(response, config, code):
    """Invalid mappings never silently coerce, choose a row, or expose query values."""
    with pytest.raises(SensorQueryError, match=f"^{code}$"):
        read_sensor_result(response, {"value_column": "value", **config})


def test_empty_and_default_limit_warning():
    """A genuine empty response is valid, and a non-truncating default-limit warning is harmless."""
    assert read_sensor_result(result(rows=[]), {"value_column": "value"}).value is None
    assert (
        read_sensor_result(
            result(warnings=["No limit defined, adding default limit of [1000]"]), {"value_column": "value"}
        ).value
        == 0
    )


@pytest.mark.parametrize("device_class", ["timestamp", "date", "uptime"])
def test_date_values(device_class):
    """Explicit date classes return the Python types Home Assistant expects."""
    value = "2026-01-01T12:30:00.123456789Z"
    reading = read_sensor_result(
        result(value, "date_nanos"), {"value_column": "value", "device_class": device_class}
    )
    assert isinstance(reading.value, date if device_class == "date" else datetime)


FRESHNESS = {"value_column": "value", "timestamp_column": "observed", "max_age": 60}


def observed(offset):
    """Build a result observed offset seconds from now."""
    return result(rows=[{"value": 2, "observed": (dt_util.utcnow() + timedelta(seconds=offset)).isoformat()}])


@pytest.mark.parametrize(("offset", "code"), [(-61, "stale"), (120, "invalid_timestamp")])
def test_observation_age(offset, code):
    """Old and future observations cannot masquerade as current data."""
    with pytest.raises(SensorQueryError, match=code):
        read_sensor_result(observed(offset), FRESHNESS)


def test_small_clock_skew_accepted():
    """A source clock slightly ahead of Home Assistant still yields a reading."""
    assert read_sensor_result(observed(10), FRESHNESS).value == 2


def test_freshness_check_can_be_skipped():
    """Saving a mapping does not reject a reading that is merely stale right now."""
    reading = read_sensor_result(observed(-3600), FRESHNESS, check_freshness=False)
    assert reading.value == 2
    with pytest.raises(SensorQueryError, match="invalid_timestamp"):
        read_sensor_result(observed(120), FRESHNESS, check_freshness=False)


def test_numeric_metadata():
    """A compatible physical measurement keeps its explicit semantics."""
    assert (
        read_sensor_result(
            result(),
            {
                "value_column": "value",
                "device_class": "temperature",
                "unit_of_measurement": "°C",
                "state_class": "measurement",
            },
        ).value
        == 0
    )

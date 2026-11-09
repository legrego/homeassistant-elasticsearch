"""Saved-query UI flows, including recoverable errors and empty observations."""

from unittest.mock import patch

import probatio
import pytest
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    BadRequest,
    CannotConnect,
    InsufficientPrivileges,
    PartialQueryResult,
    QueryNotSupported,
    RequestTimeout,
)
from custom_components.elasticsearch.esql import QueryColumn, QueryResult
from custom_components.elasticsearch.sensor_config_flow import _parameters, _preview
from homeassistant.data_entry_flow import FlowResultType

from tests.test_sensor import add_sensor, response, sensor_entity

QUERY_INPUT = {"name": "My reading", "query": "ROW value = ?", "params": "[0]"}
MAPPING = {"value_column": "value", "scan_interval": 60}


@pytest.fixture
async def loaded(hass, config_entry, es_mock_builder, integration_setup):
    """Load the actual integration before opening its saved-query UI."""
    es_mock_builder.as_elasticsearch_9_1().with_correct_permissions().without_index_template()
    assert await integration_setup()
    return config_entry


async def start(hass, entry):
    """Open the query-sensor add flow."""
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, "query_sensor"), context={"source": "user"}
    )


async def test_add_preview_save_remove(hass, loaded):
    """A completed flow stores bound params and immediately adds a polling entity."""
    result = await start(hass, loaded)
    assert result["step_id"] == "query"
    with patch.object(loaded.runtime_data.query_runner, "async_query", return_value=response()) as query:
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], QUERY_INPUT)
        assert result["step_id"] == "mapping"
        assert "| value | double | 0 |" in result["description_placeholders"]["preview"]
        query.assert_awaited_once_with("ROW value = ?", [0])
    with patch("custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=response()):
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], MAPPING)
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        [subentry] = loaded.subentries.values()
        assert subentry.data["params"] == [0]
        assert hass.states.get(sensor_entity(hass, subentry)).state == "0"
        hass.config_entries.async_remove_subentry(loaded, subentry.subentry_id)
        await hass.async_block_till_done()
        assert sensor_entity(hass, subentry) is None


async def test_empty_confirmation(hass, loaded):
    """Empty data has an explicit confirmation and can create an unknown sensor."""
    result = await start(hass, loaded)
    with patch(
        "custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=response(rows=[])
    ):
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], QUERY_INPUT)
        assert result["step_id"] == "empty"
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
        assert result["step_id"] == "mapping"
        assert result["description_placeholders"]["preview"] == ""
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], MAPPING)
        await hass.async_block_till_done()
    [subentry] = loaded.subentries.values()
    assert hass.states.get(sensor_entity(hass, subentry)).state == "unknown"


@pytest.mark.parametrize(
    ("exception", "code"),
    [
        (CannotConnect("SECRET"), "cannot_connect"),
        (RequestTimeout("SECRET"), "query_timeout"),
        (InsufficientPrivileges("SECRET"), "insufficient_privileges"),
        (AuthenticationRequired("SECRET"), "authentication_failed"),
        (BadRequest("SECRET"), "query_rejected"),
        (QueryNotSupported("SECRET"), "query_not_supported"),
        (PartialQueryResult("SECRET"), "query_failed"),
        (RuntimeError("SECRET"), "query_failed"),
    ],
)
async def test_query_error_recovery(hass, loaded, exception, code, caplog):
    """Every connection or execution error stays on an editable query form."""
    result = await start(hass, loaded)
    with (
        patch.object(loaded.runtime_data.query_runner, "async_query", side_effect=exception),
        patch(
            "custom_components.elasticsearch.config_flow.Elasticsearch8Gateway.async_init_then_stop",
            side_effect=AuthenticationRequired,
        ),
    ):
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], QUERY_INPUT)
        await hass.async_block_till_done()
    assert result["errors"] == {"base": code}
    assert result["step_id"] == "query"
    assert "SECRET" not in caplog.text
    with patch.object(loaded.runtime_data.query_runner, "async_query", return_value=response()):
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], QUERY_INPUT)
    assert result["step_id"] == "mapping"


@pytest.mark.parametrize("params", ["{}", "[[]]", "[{}]", "not json", "[NaN]", "[Infinity]"])
async def test_invalid_parameters_recover(hass, loaded, params):
    """Only arrays of JSON scalars can be bound, and correcting them resumes preview."""
    result = await start(hass, loaded)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**QUERY_INPUT, "params": params}
    )
    assert result["errors"] == {"base": "invalid_params"}
    with patch.object(loaded.runtime_data.query_runner, "async_query", return_value=response()):
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], QUERY_INPUT)
    assert result["step_id"] == "mapping"


@pytest.mark.parametrize("field", ["query", "name"])
async def test_empty_text_recover(hass, loaded, field):
    """Whitespace is not a query or display name."""
    result = await start(hass, loaded)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**QUERY_INPUT, field: "  "}
    )
    assert result["errors"] == {"base": "empty_query"}
    with patch.object(loaded.runtime_data.query_runner, "async_query", return_value=response()):
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], QUERY_INPUT)
    assert result["step_id"] == "mapping"


@pytest.mark.parametrize(
    ("invalid", "code"),
    [
        (response(rows=[{"value": 1}, {"value": 2}]), "multiple_rows"),
        (QueryResult([QueryColumn("value", "double")], [{"value": 0}], ["SECRET"], 1), "query_warnings"),
    ],
)
async def test_result_errors_recover(hass, loaded, invalid, code):
    """A multiple-row or warning-bearing query must be corrected before mapping."""
    result = await start(hass, loaded)
    with patch.object(loaded.runtime_data.query_runner, "async_query", side_effect=[invalid, response()]):
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], QUERY_INPUT)
        assert result["errors"] == {"base": code}
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], QUERY_INPUT)
    assert result["step_id"] == "mapping"


@pytest.mark.parametrize(
    ("mapping", "code"),
    [
        ({"device_class": "temperature", "unit_of_measurement": "bananas"}, "invalid_metadata"),
        ({"timestamp_column": "observed"}, "invalid_freshness"),
    ],
)
async def test_mapping_error_recovery(hass, loaded, mapping, code):
    """Metadata mistakes can be corrected without repeating a successful query."""
    result = await start(hass, loaded)
    with patch("custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=response()):
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], QUERY_INPUT)
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {**MAPPING, **mapping}
        )
        assert result["errors"] == {"base": code}
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], MAPPING)
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("field", "value"),
    [("scan_interval", 9), ("scan_interval", 86401), ("max_age", 0), ("max_age", 31536001)],
)
async def test_interval_bounds(hass, loaded, field, value):
    """The UI schema enforces bounded polling and source-age settings."""
    result = await start(hass, loaded)
    with patch.object(loaded.runtime_data.query_runner, "async_query", return_value=response()):
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], QUERY_INPUT)
    with pytest.raises(probatio.Invalid):
        result["data_schema"]({**MAPPING, field: value})


async def test_reconfigure_and_clear_optional_metadata(hass, loaded):
    """Reconfiguration updates the existing entity and can clear every optional field."""
    with patch("custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=response()):
        subentry = add_sensor(
            hass, loaded, device_class="temperature", unit_of_measurement="°C", state_class="measurement"
        )
        await hass.async_block_till_done()
        entity_id = sensor_entity(hass, subentry)
        result = await hass.config_entries.subentries.async_init(
            (loaded.entry_id, "query_sensor"),
            context={"source": "reconfigure", "subentry_id": subentry.subentry_id},
        )
        assert result["step_id"] == "query"
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {**QUERY_INPUT, "name": "Renamed"}
        )
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], MAPPING)
        assert result["reason"] == "reconfigure_successful"
        await hass.async_block_till_done()
    assert len(loaded.subentries) == 1
    assert subentry.title == "Renamed"
    assert "device_class" not in subentry.data
    assert "unit_of_measurement" not in subentry.data
    assert sensor_entity(hass, subentry) == entity_id


async def test_unloaded(hass, config_entry):
    """An unloaded connection cannot be queried by a subentry flow."""
    result = await start(hass, config_entry)
    assert result["reason"] == "connection_unloaded"


def test_preview_escapes_and_bounds_values():
    """Result contents are text and cannot inject markdown links, images, or HTML."""
    text = _preview(
        QueryResult([QueryColumn("[x]|<b>", "keyword")], [{"[x]|<b>": "`![*x*](url)\n" + "x" * 400}], [], 0)
    )
    assert "<b>" not in text and "[x]" not in text and "![" not in text
    assert "…" in text
    assert len(text) < 400
    assert _parameters('[null, true, false, 2, 1.5, "text"]') == [None, True, False, 2, 1.5, "text"]

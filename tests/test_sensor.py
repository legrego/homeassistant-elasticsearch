"""Exercise real HA entity lifecycle and isolated query failure recovery."""

import asyncio
from types import MappingProxyType
from unittest.mock import patch

import pytest
from custom_components.elasticsearch import async_remove_config_entry_device
from custom_components.elasticsearch.const import DOMAIN, StateChangeType
from custom_components.elasticsearch.diagnostics import async_get_config_entry_diagnostics
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    BadRequest,
    CannotConnect,
    InsufficientPrivileges,
    PartialQueryResult,
    QueryNotSupported,
    RequestTimeout,
)
from custom_components.elasticsearch.es_integration import ElasticIntegration
from custom_components.elasticsearch.es_publish_pipeline import Pipeline
from custom_components.elasticsearch.esql import QueryColumn, QueryResult
from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed


@pytest.fixture
def cluster(es_mock_builder):
    """Provide a query-capable cluster with its existing publishing permissions."""
    return es_mock_builder.as_elasticsearch_9_1().with_correct_permissions().without_index_template()


def add_sensor(hass, entry, *, title="Temperature", **data):
    """Attach a sensor subentry through HA's registry API."""
    subentry = ConfigSubentry(
        subentry_type="query_sensor",
        title=title,
        unique_id=None,
        data=MappingProxyType(
            {"query": "ROW value = 0", "params": [], "value_column": "value", "scan_interval": 60, **data}
        ),
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    return subentry


def response(value=0, *, rows=None):
    """Build a simple scalar query result."""
    return QueryResult(
        [QueryColumn("value", "double"), QueryColumn("observed", "date_nanos")],
        [{"value": value, "observed": dt_util.utcnow().isoformat()}] if rows is None else rows,
        [],
        12,
    )


def sensor_entity(hass, subentry):
    """Resolve the entity by its stable saved-query ID."""
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, subentry.subentry_id)


@pytest.mark.parametrize("value", [0, None, 21.5])
async def test_states_and_device(hass, config_entry, cluster, integration_setup, value):
    """Saved sensors get stable IDs and one service device; null and zero differ."""
    subentry = add_sensor(hass, config_entry)
    with patch("custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=response(value)):
        assert await integration_setup()
    entity_id = sensor_entity(hass, subentry)
    assert hass.states.get(entity_id).state == ("unknown" if value is None else str(value))
    entity = er.async_get(hass).async_get(entity_id)
    assert entity.config_subentry_id == subentry.subentry_id
    device = dr.async_get(hass).async_get(entity.device_id)
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert (DOMAIN, config_entry.unique_id) in device.identifiers
    assert not await async_remove_config_entry_device(hass, config_entry, device)
    assert not hass.states.get(entity_id).attributes.get("rows")


async def test_initial_refreshes_run_concurrently(hass, config_entry, cluster, integration_setup):
    """Setup waits for the slowest query, not for every query in turn."""
    first = add_sensor(hass, config_entry, title="First")
    second = add_sensor(hass, config_entry, title="Second")
    started = 0
    both_started = asyncio.Event()

    async def query(*_args):
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        # A sequential setup would never start the second query, and this would time out.
        await asyncio.wait_for(both_started.wait(), timeout=5)
        return response()

    with patch("custom_components.elasticsearch.esql.QueryRunner.async_query", side_effect=query):
        assert await integration_setup()
    assert hass.states.get(sensor_entity(hass, first)).state == "0"
    assert hass.states.get(sensor_entity(hass, second)).state == "0"


async def test_last_query_removal_removes_device(hass, config_entry, cluster, integration_setup):
    """The service device goes away with the entry's last saved query."""
    subentry = add_sensor(hass, config_entry)
    with patch("custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=response()):
        assert await integration_setup()
        devices = dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
        assert len(devices) == 1
        hass.config_entries.async_remove_subentry(config_entry, subentry.subentry_id)
        await hass.async_block_till_done()
    assert not dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)


@pytest.mark.parametrize(
    "failure",
    [
        CannotConnect("SECRET"),
        RequestTimeout("SECRET"),
        InsufficientPrivileges("SECRET"),
        AuthenticationRequired("SECRET"),
        BadRequest("SECRET"),
        PartialQueryResult("SECRET"),
        QueryNotSupported("SECRET"),
        ValueError("SECRET"),
    ],
)
async def test_failure_isolation_recovery(hass, config_entry, cluster, integration_setup, failure, caplog):
    """One sensor's failure leaves the other available and recovers without log spam."""
    first = add_sensor(hass, config_entry, title="First")
    second = add_sensor(hass, config_entry, title="Second")
    with (
        patch(
            "custom_components.elasticsearch.esql.QueryRunner.async_query", side_effect=[failure, response()]
        ),
        patch(
            "custom_components.elasticsearch.config_flow.Elasticsearch8Gateway.async_init_then_stop",
            side_effect=AuthenticationRequired,
        ),
    ):
        assert await integration_setup()
    assert hass.states.get(sensor_entity(hass, first)).state == "unavailable"
    assert hass.states.get(sensor_entity(hass, second)).state == "0"
    coordinator = config_entry.runtime_data.coordinators[first.subentry_id]
    initial_logs = caplog.text.count("Error fetching Elasticsearch query")
    with patch.object(config_entry.runtime_data.query_runner, "async_query", side_effect=failure):
        await coordinator.async_refresh()
    assert caplog.text.count("Error fetching Elasticsearch query") == initial_logs
    with patch.object(config_entry.runtime_data.query_runner, "async_query", return_value=response(12)):
        await coordinator.async_refresh()
    assert hass.states.get(sensor_entity(hass, first)).state == "12"
    assert ir.async_get(hass).async_get_issue(DOMAIN, coordinator.issue_id) is None
    assert "SECRET" not in caplog.text
    assert "recovered" in caplog.text
    flows = hass.config_entries.flow.async_progress()
    assert bool(flows) == (
        isinstance(failure, AuthenticationRequired) and not isinstance(failure, InsufficientPrivileges)
    )


async def test_mapping_failure_repair_and_remove(hass, config_entry, cluster, integration_setup):
    """Persistent mapping problems create repairs that are cleared on subentry removal."""
    subentry = add_sensor(hass, config_entry, value_column="missing")
    with patch("custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=response()):
        assert await integration_setup()
        coordinator = config_entry.runtime_data.coordinators[subentry.subentry_id]
        assert ir.async_get(hass).async_get_issue(DOMAIN, coordinator.issue_id)
        hass.config_entries.async_remove_subentry(config_entry, subentry.subentry_id)
        await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, coordinator.issue_id) is None
    assert sensor_entity(hass, subentry) is None
    assert not config_entry.runtime_data.coordinators
    assert not dr.async_get(hass).devices


async def test_freshness_expires_between_polls(hass, config_entry, cluster, integration_setup, freezer):
    """A successful fetch of old data does not extend its observation deadline."""
    subentry = add_sensor(hass, config_entry, timestamp_column="observed", max_age=10, scan_interval=60)
    observation = response(2)
    with patch(
        "custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=observation
    ) as query:
        assert await integration_setup()
        entity_id = sensor_entity(hass, subentry)
        assert hass.states.get(entity_id).state == "2"
        freezer.tick(11)
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert query.call_count == 1
        assert hass.states.get(entity_id).state == "unavailable"
        coordinator = config_entry.runtime_data.coordinators[subentry.subentry_id]
        assert coordinator.diagnostics()["error"] == "stale"
        await coordinator.async_refresh()
        assert hass.states.get(entity_id).state == "unavailable"
        query.return_value = response(2)
        await coordinator.async_refresh()
        assert hass.states.get(entity_id).state == "2"
        assert await hass.config_entries.async_unload(config_entry.entry_id)
        freezer.tick(120)
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert query.call_count == 3
        assert not coordinator._listeners


async def test_reconfigure_preserves_entity_identity(hass, config_entry, cluster, integration_setup):
    """Name, column, query and metadata changes preserve the registry entity and history."""
    subentry = add_sensor(hass, config_entry)
    with patch("custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=response()):
        assert await integration_setup()
        entity_id = sensor_entity(hass, subentry)
        registry_id = er.async_get(hass).async_get(entity_id).id
        hass.config_entries.async_update_subentry(
            config_entry,
            subentry,
            title="Renamed",
            data={
                **subentry.data,
                "query": "ROW value = 1",
                "unit_of_measurement": "°C",
                "device_class": "temperature",
            },
        )
        await hass.async_block_till_done()
        assert sensor_entity(hass, subentry) == entity_id
        assert er.async_get(hass).async_get(entity_id).id == registry_id
        assert hass.states.get(entity_id).attributes["device_class"] == "temperature"
        assert hass.states.get(entity_id).attributes["friendly_name"] == "Elasticsearch Renamed"


async def test_diagnostics_redact_sensor_data(hass, config_entry, cluster, integration_setup):
    """Operational diagnostics expose timing without names, query text, params, or results."""
    add_sensor(hass, config_entry, title="SECRET", query="SECRET", params=["SECRET"])
    with patch(
        "custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=response(123456789)
    ):
        assert await integration_setup()
    diagnostic = await async_get_config_entry_diagnostics(hass, config_entry)
    assert "SECRET" not in str(diagnostic)
    assert "123456789" not in str(diagnostic)
    [status] = diagnostic["runtime"]["query_sensors"].values()
    assert status["available"] and status["took_ms"] == 12
    assert status["duration_seconds"] >= 0


@pytest.mark.parametrize("enabled", [False, True])
async def test_publishing_exclusion(hass, config_entry, cluster, integration_setup, enabled):
    """Derived sensors require explicit opt-in before ordinary publishing filters run."""
    subentry = add_sensor(hass, config_entry)
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            **config_entry.options,
            "publish_query_sensors": enabled,
            "change_detection_type": ["state"],
        },
    )
    with patch("custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=response()):
        assert await integration_setup()
    settings = ElasticIntegration.build_pipeline_manager_parameters(
        hass, config_entry.runtime_data._gateway, config_entry
    )["settings"]
    filterer = Pipeline.Filterer(hass, settings)
    state = hass.states.get(sensor_entity(hass, subentry))
    assert filterer.passes_filter(state, StateChangeType.STATE) is enabled


async def test_query_only_setup(hass, config_entry, es_mock_builder, integration_setup):
    """No write-side components or endpoints are initialized for a read-only connection."""
    cluster = es_mock_builder.as_elasticsearch_8_19().with_correct_permissions().respond_to_esql()
    hass.config_entries.async_update_entry(config_entry, data={**config_entry.data, "publish_enabled": False})
    with (
        patch("custom_components.elasticsearch.es_integration.Pipeline.Manager") as pipeline,
        patch("custom_components.elasticsearch.es_integration.DatastreamManager") as datastream,
    ):
        assert await integration_setup()
        pipeline.assert_not_called()
        datastream.assert_not_called()
    result = await hass.services.async_call(
        DOMAIN,
        "query",
        {"config_entry_id": config_entry.entry_id, "query": "ROW value = 0"},
        blocking=True,
        return_response=True,
    )
    assert result["rows"]
    assert config_entry.runtime_data.diagnostics()["queue_size"] == 0
    assert all(
        "_index_template" not in str(url) and "_data_stream" not in str(url)
        for _, url, _ in cluster.get_calls()
    )
    assert config_entry.runtime_data._gateway.settings.minimum_privileges == {"cluster": ["monitor"]}


async def test_polling_and_empty(hass, config_entry, cluster, integration_setup, freezer):
    """A regular poll can transition from unknown to a valid zero reading."""
    subentry = add_sensor(hass, config_entry)
    with patch(
        "custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=response(rows=[])
    ) as query:
        assert await integration_setup()
        assert hass.states.get(sensor_entity(hass, subentry)).state == "unknown"
        query.return_value = response(0)
        freezer.tick(65)
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert query.call_count == 2
        assert hass.states.get(sensor_entity(hass, subentry)).state == "0"


async def test_unloaded_query_removal_clears_repair(hass, config_entry, cluster, integration_setup):
    """Unloading clears query Repairs, so removing an unloaded subentry leaves none behind."""
    subentry = add_sensor(hass, config_entry, value_column="missing")
    with patch("custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=response()):
        assert await integration_setup()
    coordinator = config_entry.runtime_data.coordinators[subentry.subentry_id]
    assert ir.async_get(hass).async_get_issue(DOMAIN, coordinator.issue_id)
    await hass.config_entries.async_unload(config_entry.entry_id)
    hass.config_entries.async_remove_subentry(config_entry, subentry.subentry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, coordinator.issue_id) is None


async def test_failed_platform_unload_keeps_connection(hass, config_entry, cluster, integration_setup):
    """A failed entity unload must not close the connection underneath live entities."""
    assert await integration_setup()
    integration = config_entry.runtime_data
    with (
        patch.object(hass.config_entries, "async_unload_platforms", return_value=False),
        patch.object(integration, "async_shutdown") as shutdown,
    ):
        assert not await hass.config_entries.async_unload(config_entry.entry_id)
        shutdown.assert_not_called()


async def test_disabled_sensor_stops_polling(hass, config_entry, cluster, integration_setup, freezer):
    """Disabling a saved entity cancels its polling listener and expiry timer."""
    subentry = add_sensor(hass, config_entry, timestamp_column="observed", max_age=120)
    with patch(
        "custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=response()
    ) as query:
        assert await integration_setup()
        entity_id = sensor_entity(hass, subentry)
        er.async_get(hass).async_update_entity(entity_id, disabled_by=er.RegistryEntryDisabler.USER)
        await hass.async_block_till_done()
        freezer.tick(125)
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert query.call_count == 1
        assert not config_entry.runtime_data.coordinators[subentry.subentry_id]._listeners


@pytest.mark.parametrize(
    "invalid",
    [
        response(rows=[{"value": 1}, {"value": 2}]),
        response([1, 2]),
        QueryResult([QueryColumn("renamed", "double")], [{"renamed": 2}], [], 1),
        QueryResult([QueryColumn("value", "keyword")], [{"value": "not numeric"}], [], 1),
        QueryResult([QueryColumn("value", "double")], [{"value": 2}], ["SECRET ignored value"], 1),
    ],
)
async def test_runtime_mapping_changes(hass, config_entry, cluster, integration_setup, invalid, caplog):
    """Schema and data changes become unavailable and recover without losing entity identity."""
    subentry = add_sensor(hass, config_entry, state_class="measurement")
    with patch("custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=response()):
        assert await integration_setup()
    entity_id = sensor_entity(hass, subentry)
    coordinator = config_entry.runtime_data.coordinators[subentry.subentry_id]
    with patch.object(config_entry.runtime_data.query_runner, "async_query", return_value=invalid):
        await coordinator.async_refresh()
    assert hass.states.get(entity_id).state == "unavailable"
    assert ir.async_get(hass).async_get_issue(DOMAIN, coordinator.issue_id)
    with patch.object(config_entry.runtime_data.query_runner, "async_query", return_value=response(0)):
        await coordinator.async_refresh()
    assert hass.states.get(entity_id).state == "0"
    assert "SECRET" not in caplog.text
    assert sensor_entity(hass, subentry) == entity_id


@pytest.mark.parametrize(
    ("value", "column_type", "metadata", "expected"),
    [
        (
            12.5,
            "double",
            {"device_class": "monetary", "unit_of_measurement": "USD", "state_class": "total"},
            "12.5",
        ),
        ("2026-01-01T12:00:00Z", "date_nanos", {"device_class": "uptime"}, "2026-01-01T12:00:00+00:00"),
        (0, "double", {"device_class": "uptime"}, "unavailable"),
        (
            "2026-01-01T12:00:00Z",
            "date_nanos",
            {"device_class": "uptime", "unit_of_measurement": "s"},
            "unavailable",
        ),
    ],
)
async def test_special_device_class_states(
    hass, config_entry, cluster, integration_setup, value, column_type, metadata, expected
):
    """Validate monetary units and uptime timestamps against HA's actual state writer."""
    subentry = add_sensor(hass, config_entry, **metadata)
    result = QueryResult([QueryColumn("value", column_type)], [{"value": value}], [], 1)
    with patch("custom_components.elasticsearch.esql.QueryRunner.async_query", return_value=result):
        assert await integration_setup()
    assert hass.states.get(sensor_entity(hass, subentry)).state == expected

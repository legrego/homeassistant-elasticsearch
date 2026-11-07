"""Tests for the elasticsearch.query action."""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from unittest import mock

import probatio
import pytest
from aiohttp import client_exceptions
from custom_components.elasticsearch.const import DOMAIN
from custom_components.elasticsearch.esql import MAX_CONCURRENT_QUERIES, MAX_RESULT_BYTES, MAX_ROWS
from custom_components.elasticsearch.services import ATTR_PARAMS, ATTR_QUERY, MAX_REASON_LENGTH, SERVICE_QUERY
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

from tests import const as testconst

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.core import HomeAssistant

    from tests.test_util.es_mocker import es_mocker

QUERY = "FROM metrics-homeassistant.* | WHERE hass.entity.id == ? | SORT @timestamp DESC | LIMIT 1"


@pytest.fixture
def cluster(es_mock_builder: es_mocker) -> es_mocker:
    """Mock a 9.1 cluster that the integration can set up against."""
    return es_mock_builder.as_elasticsearch_9_1().with_correct_permissions().without_index_template()


@pytest.fixture
async def loaded_entry(
    hass: HomeAssistant,
    cluster: es_mocker,
    integration_setup: Callable[[], Awaitable[bool]],
    config_entry: MockConfigEntry,
) -> MockConfigEntry:
    """Return a loaded config entry."""
    assert await integration_setup()
    assert config_entry.state is ConfigEntryState.LOADED
    return config_entry


async def call_query(hass: HomeAssistant, entry_id: str, **data: Any) -> Any:
    """Call the query action and return its response."""
    return await hass.services.async_call(
        DOMAIN,
        SERVICE_QUERY,
        {ATTR_CONFIG_ENTRY_ID: entry_id, ATTR_QUERY: QUERY, **data},
        blocking=True,
        return_response=True,
    )


def esql_calls(cluster: es_mocker) -> list[tuple[Any, Any, Any]]:
    """Return the requests made to the ES|QL endpoint, with their bodies decoded."""
    return [
        (method, url, json.loads(body)) for method, url, body in cluster.get_calls() if url.path == "/_query"
    ]


class Test_Registration:
    """Test that the action is registered."""

    async def test_registered_without_entries(self, hass: HomeAssistant) -> None:
        """Test the action is registered by async_setup, before any entry is loaded."""
        assert await async_setup_component(hass, DOMAIN, {})
        assert hass.services.has_service(DOMAIN, SERVICE_QUERY)

    async def test_response_required(self, hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
        """Test the action only responds, and can't be called without asking for a response."""
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_QUERY,
                {ATTR_CONFIG_ENTRY_ID: loaded_entry.entry_id, ATTR_QUERY: QUERY},
                blocking=True,
            )


class Test_Success:
    """Test queries that succeed."""

    async def test_query(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker
    ) -> None:
        """Test a query's result is returned as named rows, and its parameters are bound."""
        cluster.respond_to_esql()

        response = await call_query(hass, loaded_entry.entry_id, **{ATTR_PARAMS: ["sensor.temp"]})

        assert response == {
            "columns": [
                {"name": "@timestamp", "type": "date_nanos"},
                {"name": "hass.entity.valueas.float", "type": "double"},
            ],
            "rows": [{"@timestamp": "2026-11-07T22:06:42.875933123Z", "hass.entity.valueas.float": 21.5}],
            "warnings": [],
            "took_ms": 12,
        }

        [(method, url, body)] = esql_calls(cluster)
        assert method == "POST"
        assert url.query["allow_partial_results"] == "false"
        assert body == {"query": QUERY, "params": ["sensor.temp"]}

    async def test_params_default_to_empty(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker
    ) -> None:
        """Test a query without parameters sends an empty list."""
        cluster.respond_to_esql()

        await call_query(hass, loaded_entry.entry_id)

        [(_, _, body)] = esql_calls(cluster)
        assert body == {"query": QUERY, "params": []}

    async def test_query_text_is_stripped(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker
    ) -> None:
        """Test surrounding whitespace, such as from a YAML block, is removed from the query."""
        cluster.respond_to_esql()

        await call_query(hass, loaded_entry.entry_id, **{ATTR_QUERY: f"\n  {QUERY}\n"})

        [(_, _, body)] = esql_calls(cluster)
        assert body["query"] == QUERY

    async def test_empty_result(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker
    ) -> None:
        """Test a query that matches nothing is a valid response, not an error."""
        cluster.respond_to_esql(json={"columns": [{"name": "a", "type": "long"}], "values": []})

        response = await call_query(hass, loaded_entry.entry_id)

        assert response["rows"] == []
        assert response["columns"] == [{"name": "a", "type": "long"}]

    async def test_warnings(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker
    ) -> None:
        """Test warnings are returned with the result."""
        cluster.respond_to_esql(
            json={"columns": [{"name": "b", "type": "double"}], "values": [[None]]},
            warnings=["Line 1:26: evaluation of [TO_DOUBLE(a)] failed, treating result as null."],
        )

        response = await call_query(hass, loaded_entry.entry_id)

        assert response["warnings"] == [
            "Line 1:26: evaluation of [TO_DOUBLE(a)] failed, treating result as null."
        ]

    async def test_serverless(
        self,
        hass: HomeAssistant,
        es_mock_builder: es_mocker,
        integration_setup: Callable[[], Awaitable[bool]],
        config_entry: MockConfigEntry,
    ) -> None:
        """Test serverless projects can be queried, whatever version they report."""
        es_mock_builder.as_elasticsearch_serverless().with_correct_permissions().without_index_template()
        assert await integration_setup()
        es_mock_builder.respond_to_esql()

        response = await call_query(hass, config_entry.entry_id)

        assert response["rows"]


class Test_Validation:
    """Test invalid input is rejected before anything is sent."""

    @pytest.mark.parametrize(
        "service_data",
        [
            {ATTR_QUERY: ""},
            {ATTR_QUERY: "   \n"},
            {ATTR_PARAMS: "sensor.temp"},
            {ATTR_PARAMS: [{"name": "value"}]},
            {ATTR_PARAMS: [["a", "b"]]},
        ],
        ids=["empty query", "blank query", "params not a list", "named param", "list param"],
    )
    async def test_invalid_input(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker, service_data: dict
    ) -> None:
        """Test invalid queries and parameters are rejected."""
        with pytest.raises(probatio.Invalid):
            await call_query(hass, loaded_entry.entry_id, **service_data)

        assert esql_calls(cluster) == []

    async def test_scalar_params(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker
    ) -> None:
        """Test every kind of scalar can be bound."""
        cluster.respond_to_esql()

        await call_query(hass, loaded_entry.entry_id, **{ATTR_PARAMS: ["a", 1, 1.5, True, None]})

        [(_, _, body)] = esql_calls(cluster)
        assert body["params"] == ["a", 1, 1.5, True, None]

    async def test_unknown_entry(self, hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
        """Test an entry that doesn't exist is rejected."""
        with pytest.raises(ServiceValidationError) as err:
            await call_query(hass, "not_an_entry")

        assert err.value.translation_key == "service_config_entry_not_found"

    async def test_other_domain(self, hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
        """Test an entry of another integration is rejected."""
        other = MockConfigEntry(domain="other_domain")
        other.add_to_hass(hass)

        with pytest.raises(ServiceValidationError) as err:
            await call_query(hass, other.entry_id)

        assert err.value.translation_key == "service_config_entry_wrong_domain"

    async def test_entry_not_loaded(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker
    ) -> None:
        """Test an entry that isn't loaded is rejected."""
        await hass.config_entries.async_unload(loaded_entry.entry_id)

        with pytest.raises(ServiceValidationError) as err:
            await call_query(hass, loaded_entry.entry_id)

        assert err.value.translation_key == "service_config_entry_not_loaded"
        assert esql_calls(cluster) == []


class Test_Unsupported_Version:
    """Test clusters that can be published to, but not queried."""

    @pytest.mark.parametrize(
        ("version_mock", "cluster_version"),
        [("as_elasticsearch_8_17", "8.17.0"), ("as_elasticsearch_9_0", "9.0.0")],
        ids=["8.17", "9.0"],
    )
    async def test_unsupported_version(
        self,
        hass: HomeAssistant,
        es_mock_builder: es_mocker,
        integration_setup: Callable[[], Awaitable[bool]],
        config_entry: MockConfigEntry,
        version_mock: str,
        cluster_version: str,
    ) -> None:
        """Test the entry loads, but querying is refused without contacting the cluster."""
        getattr(es_mock_builder, version_mock)().with_correct_permissions().without_index_template()
        assert await integration_setup()
        assert config_entry.state is ConfigEntryState.LOADED

        with pytest.raises(ServiceValidationError) as err:
            await call_query(hass, config_entry.entry_id)

        assert err.value.translation_key == "query_not_supported"
        assert err.value.translation_placeholders is not None
        assert err.value.translation_placeholders["version"] == cluster_version
        assert esql_calls(es_mock_builder) == []


class Test_Errors:
    """Test failures are raised as translated errors."""

    async def test_rejected_query(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker
    ) -> None:
        """Test a query Elasticsearch rejects includes its reason."""
        cluster.respond_to_esql(
            status=HTTPStatus.BAD_REQUEST,
            json={
                "error": {
                    "type": "verification_exception",
                    "reason": "Found 1 problem\nline 1:1: Unknown index [nope-*]",
                },
                "status": 400,
            },
        )

        with pytest.raises(ServiceValidationError) as err:
            await call_query(hass, loaded_entry.entry_id)

        assert err.value.translation_key == "query_rejected"
        assert err.value.translation_placeholders == {
            "error_type": "verification_exception",
            "reason": "Found 1 problem\nline 1:1: Unknown index [nope-*]",
        }

    async def test_rejected_query_long_reason(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker
    ) -> None:
        """Test a long reason is cut short."""
        cluster.respond_to_esql(
            status=HTTPStatus.BAD_REQUEST,
            json={"error": {"type": "parsing_exception", "reason": "x" * 2000}, "status": 400},
        )

        with pytest.raises(ServiceValidationError) as err:
            await call_query(hass, loaded_entry.entry_id)

        assert err.value.translation_placeholders is not None
        assert err.value.translation_placeholders["reason"] == "x" * MAX_REASON_LENGTH + "…"

    async def test_rejected_query_without_details(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker
    ) -> None:
        """Test a rejection without an error body still explains itself."""
        cluster.respond_to_esql(status=HTTPStatus.BAD_REQUEST, json={})

        with pytest.raises(ServiceValidationError) as err:
            await call_query(hass, loaded_entry.entry_id)

        assert err.value.translation_placeholders == {"error_type": "unknown", "reason": "no reason given"}

    async def test_insufficient_privileges(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker
    ) -> None:
        """Test credentials that can't read the indices don't start reauthentication."""
        cluster.respond_to_esql(status=HTTPStatus.FORBIDDEN, json={"error": {"type": "security_exception"}})

        with pytest.raises(HomeAssistantError) as err:
            await call_query(hass, loaded_entry.entry_id)

        assert err.value.translation_key == "query_insufficient_privileges"
        await hass.async_block_till_done()
        assert not list(loaded_entry.async_get_active_flows(hass, {SOURCE_REAUTH}))

    async def test_authentication_failed(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker
    ) -> None:
        """Test rejected credentials start reauthentication."""
        cluster.respond_to_esql(
            status=HTTPStatus.UNAUTHORIZED, json={"error": {"type": "security_exception"}}
        )

        with (
            mock.patch.object(loaded_entry, "async_start_reauth") as start_reauth,
            pytest.raises(HomeAssistantError) as err,
        ):
            await call_query(hass, loaded_entry.entry_id)

        assert err.value.translation_key == "authentication_failed"
        start_reauth.assert_called_once_with(hass)

    async def test_timeout(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker
    ) -> None:
        """Test a query that times out."""
        cluster.respond_to_esql(exc=client_exceptions.ServerTimeoutError())

        with pytest.raises(HomeAssistantError) as err:
            await call_query(hass, loaded_entry.entry_id)

        assert err.value.translation_key == "query_timeout"
        assert err.value.translation_placeholders == {"timeout": str(testconst.CONFIG_ENTRY_DATA_TIMEOUT)}

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"status": HTTPStatus.INTERNAL_SERVER_ERROR, "json": {}},
            {"status": HTTPStatus.TOO_MANY_REQUESTS, "json": {}},
            {"exc": client_exceptions.ClientConnectionError()},
        ],
        ids=["server error", "too many requests", "connection error"],
    )
    async def test_failed(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker, kwargs: dict
    ) -> None:
        """Test a query that fails for reasons other than the query."""
        cluster.respond_to_esql(**kwargs)

        with pytest.raises(HomeAssistantError) as err:
            await call_query(hass, loaded_entry.entry_id)

        assert err.value.translation_key == "query_failed"
        assert QUERY not in str(err.value.translation_placeholders)

    @pytest.mark.parametrize(
        ("body", "expected_error", "translation_key", "placeholders"),
        [
            (
                {**testconst.ESQL_QUERY_RESPONSE_BODY, "is_partial": True},
                HomeAssistantError,
                "query_partial_result",
                None,
            ),
            ({"columns": "nope", "values": []}, HomeAssistantError, "query_invalid_response", None),
            (
                {"columns": [{"name": "a", "type": "long"}] * 2, "values": [[1, 2]]},
                ServiceValidationError,
                "query_ambiguous_columns",
                {"columns": "a"},
            ),
            (
                {"columns": [{"name": "a", "type": "long"}], "values": [[1]] * (MAX_ROWS + 1)},
                ServiceValidationError,
                "query_too_many_rows",
                {"rows": str(MAX_ROWS + 1), "limit": str(MAX_ROWS)},
            ),
            (
                {"columns": [{"name": "a", "type": "keyword"}], "values": [["x" * MAX_RESULT_BYTES]]},
                ServiceValidationError,
                "query_result_too_large",
                {"size": "1025 KiB", "limit": "1024 KiB"},
            ),
        ],
        ids=["partial", "invalid", "ambiguous columns", "too many rows", "too large"],
    )
    async def test_unacceptable_result(
        self,
        hass: HomeAssistant,
        loaded_entry: MockConfigEntry,
        cluster: es_mocker,
        body: dict,
        expected_error: type[HomeAssistantError],
        translation_key: str,
        placeholders: dict | None,
    ) -> None:
        """Test results that can't be accepted are errors, never returned incomplete."""
        cluster.respond_to_esql(json=body)

        with pytest.raises(expected_error) as err:
            await call_query(hass, loaded_entry.entry_id)

        assert err.value.translation_key == translation_key
        assert err.value.translation_placeholders == placeholders

    async def test_truncated(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker
    ) -> None:
        """Test a result Elasticsearch cut short at its default limit is an error."""
        cluster.respond_to_esql(
            json={"columns": [{"name": "a", "type": "long"}], "values": [[1]] * 1000},
            warnings=["No limit defined, adding default limit of [1000]"],
        )

        with pytest.raises(ServiceValidationError) as err:
            await call_query(hass, loaded_entry.entry_id)

        assert err.value.translation_key == "query_truncated"
        assert err.value.translation_placeholders == {"limit": "1000", "max_rows": str(MAX_ROWS)}

    async def test_unexpected_error(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test an unexpected error is logged, without the query, and raised as a translated error."""
        with (
            mock.patch.object(
                loaded_entry.runtime_data.query_runner, "async_query", side_effect=RuntimeError("boom")
            ),
            pytest.raises(HomeAssistantError) as err,
        ):
            await call_query(hass, loaded_entry.entry_id)

        assert err.value.translation_key == "unexpected_error"
        assert "Unexpected error running a query" in caplog.text
        assert QUERY not in caplog.text

    async def test_unparseable_response(
        self,
        hass: HomeAssistant,
        loaded_entry: MockConfigEntry,
        cluster: es_mocker,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test a response that can't be parsed doesn't expose its contents in the error or logs."""
        caplog.set_level(logging.DEBUG, logger="custom_components.elasticsearch")
        cluster.respond_to_esql(text='{"columns": [], "values": [["PRIVATE_RESULT"]')

        with pytest.raises(HomeAssistantError) as err:
            await call_query(hass, loaded_entry.entry_id)

        assert err.value.translation_key == "query_invalid_response"
        assert "PRIVATE_RESULT" not in "".join(traceback.format_exception(err.value))
        assert "PRIVATE_RESULT" not in caplog.text


class Test_Unload:
    """Test queries don't outlive their entry."""

    async def test_unload_cancels_queries(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry, cluster: es_mocker
    ) -> None:
        """Test unloading cancels running queries, and queued ones never send a request."""
        release = asyncio.Event()

        async def blocked(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
            await release.wait()
            return AiohttpClientMockResponse(  # pragma: no cover
                method,
                url,
                json=testconst.ESQL_QUERY_RESPONSE_BODY,
                headers={"x-elastic-product": "Elasticsearch"},
            )

        cluster.mocker.post(f"{cluster.base_url}/_query", side_effect=blocked)
        integration = loaded_entry.runtime_data
        nodes = integration._gateway.client.transport.node_pool.all()

        # Fill every slot, and queue one more query behind them
        calls = [
            asyncio.create_task(call_query(hass, loaded_entry.entry_id))
            for _ in range(MAX_CONCURRENT_QUERIES + 1)
        ]
        for _ in range(50):
            if len(esql_calls(cluster)) == MAX_CONCURRENT_QUERIES:
                break
            await asyncio.sleep(0)
        assert len(esql_calls(cluster)) == MAX_CONCURRENT_QUERIES

        assert await hass.config_entries.async_unload(loaded_entry.entry_id)
        release.set()
        results = await asyncio.gather(*calls, return_exceptions=True)

        assert all(isinstance(result, HomeAssistantError) for result in results)
        assert {result.translation_key for result in results if isinstance(result, HomeAssistantError)} == {
            "query_cancelled"
        }

        # Nothing more was sent, and no closed session was reopened
        for _ in range(10):
            await asyncio.sleep(0)
        assert len(esql_calls(cluster)) == MAX_CONCURRENT_QUERIES
        assert all(node.session is None for node in nodes)

"""Tests for running ES|QL queries."""

from __future__ import annotations

import asyncio
import json
import traceback
import warnings
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from custom_components.elasticsearch.errors import (
    AmbiguousQueryColumns,
    CannotConnect,
    InvalidQueryResponse,
    PartialQueryResult,
    QueryCancelled,
    QueryNotSupported,
    QueryResultTooLarge,
    TooManyQueryRows,
    TruncatedQueryResult,
)
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway, EsqlResponse
from custom_components.elasticsearch.es_gateway_8 import (
    ESQL_WARNING_HEADER,
    CompatibilityTransport,
    Elasticsearch8Gateway,
    Gateway8Settings,
    JoinedWarningsNode,
    JoinedWarningsResponse,
    parse_warning_header,
)
from custom_components.elasticsearch.esql import (
    MAX_CONCURRENT_QUERIES,
    MAX_RESULT_BYTES,
    MAX_ROWS,
    QueryColumn,
    QueryRunner,
    check_query_support,
    normalize_response,
    supports_query,
)
from elastic_transport import AsyncTransport, HttpHeaders, NodeConfig, TransportApiResponse

from tests import const as testconst

if TYPE_CHECKING:
    from tests.test_util.es_mocker import es_mocker

COLUMNS = [{"name": "entity", "type": "keyword"}, {"name": "value", "type": "double"}]


def response(values: list[Any], warnings: list[str] | None = None, **body: Any) -> EsqlResponse:
    """Build a raw query response."""
    return EsqlResponse(body={"columns": COLUMNS, "values": values, **body}, warnings=warnings or [])


def mock_gateway(version: str | None = "9.1.0", build_flavor: str = "default") -> MagicMock:
    """Return a gateway connected to a cluster of the given version."""
    gateway = MagicMock(spec=ElasticsearchGateway)
    gateway.cluster_version = version
    gateway.build_flavor = build_flavor
    gateway.esql_query = AsyncMock(return_value=response([["sensor.temp", 21.5]]))
    return gateway


async def settle() -> None:
    """Let tasks that are ready run, including the ones they start."""
    for _ in range(5):
        await asyncio.sleep(0)


class Test_Version_Support:
    """Test which versions can be queried."""

    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            ("8.14.0", False),
            ("8.18.8", False),
            ("8.19.0", True),
            ("8.20.1", True),
            ("9.0.8", False),
            ("9.1.0", True),
            ("9.3.2", True),
            ("10.0.0", True),
            ("7.17.0", False),
            (None, False),
            ("9", False),
            ("nine.one", False),
        ],
    )
    def test_supports_query(self, version: str | None, expected: bool) -> None:
        """Test the minimum version on each major version."""
        assert supports_query(version) is expected

    def test_serverless(self) -> None:
        """Test serverless projects are always supported, whatever version they report."""
        check_query_support(mock_gateway(version="8.11.0", build_flavor="serverless"))

    def test_unsupported(self) -> None:
        """Test an unsupported version is reported with the cluster's version."""
        with pytest.raises(QueryNotSupported) as err:
            check_query_support(mock_gateway(version="9.0.0"))

        assert err.value.version == "9.0.0"


class Test_Normalize_Response:
    """Test turning query responses into results."""

    def test_named_rows(self) -> None:
        """Test columns and values become named rows, keeping column metadata, warnings, and timing."""
        result = normalize_response(
            response([["sensor.temp", 21.5], ["sensor.hum", 40.0]], warnings=["a warning"], took=7)
        )

        assert result.columns == [QueryColumn("entity", "keyword"), QueryColumn("value", "double")]
        assert result.rows == [
            {"entity": "sensor.temp", "value": 21.5},
            {"entity": "sensor.hum", "value": 40.0},
        ]
        assert result.as_dict() == {
            "columns": COLUMNS,
            "rows": result.rows,
            "warnings": ["a warning"],
            "took_ms": 7,
        }

    def test_nulls_and_multivalues(self) -> None:
        """Test nulls and multivalued cells are kept as they are."""
        result = normalize_response(response([[None, [1.0, 2.0]]]))

        assert result.rows == [{"entity": None, "value": [1.0, 2.0]}]

    def test_empty(self) -> None:
        """Test a result without rows is valid."""
        result = normalize_response(response([]))

        assert result.rows == []
        assert len(result.columns) == 2

    @pytest.mark.parametrize("took", [None, "7", True], ids=["missing", "string", "boolean"])
    def test_took_not_an_integer(self, took: Any) -> None:
        """Test a missing or unexpected `took` isn't reported."""
        body = {} if took is None else {"took": took}
        assert normalize_response(response([], **body)).took_ms is None

    def test_partial(self) -> None:
        """Test partial results are never accepted."""
        with pytest.raises(PartialQueryResult):
            normalize_response(response([["a", 1.0]], is_partial=True))

    def test_not_partial(self) -> None:
        """Test a response that says it isn't partial is accepted."""
        assert normalize_response(response([["a", 1.0]], is_partial=False)).rows

    def test_ambiguous_columns(self) -> None:
        """Test a name used by more than one column is rejected, rather than overwritten."""
        body = {
            "columns": [*COLUMNS, {"name": "value", "type": "long"}, {"name": "entity", "type": "keyword"}],
            "values": [["a", 1.0, 2, "b"]],
        }

        with pytest.raises(AmbiguousQueryColumns) as err:
            normalize_response(EsqlResponse(body=body, warnings=[]))

        assert err.value.columns == ["entity", "value"]

    def test_row_limit(self) -> None:
        """Test the most rows that are accepted."""
        assert len(normalize_response(response([["a", 1.0]] * MAX_ROWS)).rows) == MAX_ROWS

    def test_too_many_rows(self) -> None:
        """Test more rows than the limit is an error, not a truncated result."""
        with pytest.raises(TooManyQueryRows) as err:
            normalize_response(response([["a", 1.0]] * (MAX_ROWS + 1)))

        assert (err.value.rows, err.value.limit) == (MAX_ROWS + 1, MAX_ROWS)

    @pytest.mark.parametrize("limit", [1000, 50])
    def test_default_limit_reached(self, limit: int) -> None:
        """Test a result that reached the default limit Elasticsearch applied is an error."""
        warning = f"No limit defined, adding default limit of [{limit}]"

        with pytest.raises(TruncatedQueryResult) as err:
            normalize_response(response([["a", 1.0]] * limit, warnings=[warning]))

        assert err.value.limit == limit

    def test_default_limit_not_reached(self) -> None:
        """Test a result below the default limit is complete, and keeps the warning."""
        warning = "No limit defined, adding default limit of [1000]"

        result = normalize_response(response([["a", 1.0]] * 999, warnings=["other", warning]))

        assert len(result.rows) == 999
        assert result.warnings == ["other", warning]

    def test_too_large(self) -> None:
        """Test a result larger than the limit is an error, even within the row limit."""
        with pytest.raises(QueryResultTooLarge) as err:
            normalize_response(response([["x" * MAX_RESULT_BYTES, 1.0]]))

        assert err.value.size > MAX_RESULT_BYTES
        assert err.value.limit == MAX_RESULT_BYTES

    @pytest.mark.parametrize(
        "body",
        [
            {"values": []},
            {"columns": {}, "values": []},
            {"columns": [{"name": "a"}], "values": []},
            {"columns": [{"name": 1, "type": "long"}], "values": []},
            {"columns": ["a"], "values": []},
            {"columns": COLUMNS},
            {"columns": COLUMNS, "values": {}},
            {"columns": COLUMNS, "values": [["a"]]},
            {"columns": COLUMNS, "values": ["a"]},
        ],
        ids=[
            "no columns",
            "columns not a list",
            "column without type",
            "column name not a string",
            "column not an object",
            "no values",
            "values not a list",
            "row too short",
            "row not a list",
        ],
    )
    def test_invalid_response(self, body: dict) -> None:
        """Test responses that don't have the expected shape."""
        with pytest.raises(InvalidQueryResponse):
            normalize_response(EsqlResponse(body=body, warnings=[]))


class Test_Query_Runner:
    """Test the query runner."""

    async def test_query(self) -> None:
        """Test a query is sent with its parameters, and its result normalized."""
        gateway = mock_gateway()

        result = await QueryRunner(gateway).async_query("FROM x | WHERE a == ?", ["b"])

        gateway.esql_query.assert_awaited_once_with("FROM x | WHERE a == ?", ["b"])
        assert result.rows == [{"entity": "sensor.temp", "value": 21.5}]

    async def test_no_params(self) -> None:
        """Test a query without parameters sends an empty list."""
        gateway = mock_gateway()

        await QueryRunner(gateway).async_query("ROW a = 1")

        gateway.esql_query.assert_awaited_once_with("ROW a = 1", [])

    async def test_unsupported_version(self) -> None:
        """Test nothing is sent to a cluster that can't be queried."""
        gateway = mock_gateway(version="8.17.0")

        with pytest.raises(QueryNotSupported):
            await QueryRunner(gateway).async_query("ROW a = 1")

        gateway.esql_query.assert_not_awaited()

    async def test_concurrency_is_bounded(self) -> None:
        """Test no more than MAX_CONCURRENT_QUERIES queries run at once."""
        gateway = mock_gateway()
        release = asyncio.Event()
        running = 0
        most_running = 0

        async def esql_query(query: str, params: list[Any]) -> EsqlResponse:
            nonlocal running, most_running
            running += 1
            most_running = max(most_running, running)
            await release.wait()
            running -= 1
            return response([])

        gateway.esql_query = esql_query
        runner = QueryRunner(gateway)

        tasks = [
            asyncio.create_task(runner.async_query("ROW a = 1")) for _ in range(MAX_CONCURRENT_QUERIES + 3)
        ]
        await settle()
        assert running == MAX_CONCURRENT_QUERIES

        release.set()
        await asyncio.gather(*tasks)
        assert most_running == MAX_CONCURRENT_QUERIES

    async def test_shutdown(self) -> None:
        """Test shutting down cancels running queries, and queued ones never reach the gateway."""
        gateway = mock_gateway()
        started: list[asyncio.Event] = []
        cancelled = 0

        async def esql_query(query: str, params: list[Any]) -> EsqlResponse:
            nonlocal cancelled
            started.append(asyncio.Event())
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled += 1
                raise
            return response([])  # pragma: no cover

        gateway.esql_query = esql_query
        runner = QueryRunner(gateway)

        tasks = [
            asyncio.create_task(runner.async_query("ROW a = 1")) for _ in range(MAX_CONCURRENT_QUERIES + 2)
        ]
        await settle()
        assert len(started) == MAX_CONCURRENT_QUERIES

        await runner.async_shutdown()
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assert all(isinstance(result, QueryCancelled) for result in results)
        assert cancelled == MAX_CONCURRENT_QUERIES
        assert len(started) == MAX_CONCURRENT_QUERIES

    async def test_query_after_shutdown(self) -> None:
        """Test a query after shutting down never reaches the gateway."""
        gateway = mock_gateway()
        runner = QueryRunner(gateway)
        await runner.async_shutdown()

        with pytest.raises(QueryCancelled):
            await runner.async_query("ROW a = 1")

        gateway.esql_query.assert_not_awaited()

    async def test_caller_cancelled(self) -> None:
        """Test cancelling the caller cancels its request, and isn't turned into QueryCancelled."""
        gateway = mock_gateway()
        request_cancelled = asyncio.Event()

        async def esql_query(query: str, params: list[Any]) -> EsqlResponse:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                request_cancelled.set()
                raise
            return response([])  # pragma: no cover

        gateway.esql_query = esql_query
        runner = QueryRunner(gateway)

        task = asyncio.create_task(runner.async_query("ROW a = 1"))
        await settle()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert request_cancelled.is_set()

    async def test_caller_cancelled_during_shutdown(self) -> None:
        """Test a caller that's cancelled itself still gets its cancellation, even while shutting down."""
        gateway = mock_gateway()

        async def esql_query(query: str, params: list[Any]) -> EsqlResponse:
            await asyncio.Event().wait()
            return response([])  # pragma: no cover

        gateway.esql_query = esql_query
        runner = QueryRunner(gateway)

        task = asyncio.create_task(runner.async_query("ROW a = 1"))
        await settle()
        task.cancel()
        await runner.async_shutdown()

        with pytest.raises(asyncio.CancelledError):
            await task


class Test_Gateway_Query:
    """Test the gateway's ES|QL request, through the Elasticsearch client."""

    @pytest.fixture
    async def gateway(self, es_mock_builder: es_mocker):
        """Return a gateway connected to a 9.1 cluster."""
        es_mock_builder.as_elasticsearch_9_1()
        gateway = Elasticsearch8Gateway(
            gateway_settings=Gateway8Settings(
                url=testconst.CONFIG_ENTRY_DATA_URL, minimum_privileges=MappingProxyType({})
            )
        )
        gateway._client = gateway.settings.to_client()
        try:
            yield gateway
        finally:
            await gateway.stop()

    async def test_request(self, gateway: Elasticsearch8Gateway, es_mock_builder: es_mocker) -> None:
        """Test the query and parameters are sent, with partial results turned off."""
        es_mock_builder.respond_to_esql()

        result = await gateway.esql_query("FROM x | WHERE a == ?", ["b"])

        [(method, url, body)] = [call for call in es_mock_builder.get_calls() if call[1].path == "/_query"]
        assert method == "POST"
        assert url.query["allow_partial_results"] == "false"
        assert json.loads(body) == {"query": "FROM x | WHERE a == ?", "params": ["b"]}
        assert result == EsqlResponse(body=testconst.ESQL_QUERY_RESPONSE_BODY, warnings=[])

    async def test_warnings(self, gateway: Elasticsearch8Gateway, es_mock_builder: es_mocker) -> None:
        """Test warnings are returned, and never raised as Python warnings that would be logged."""
        es_mock_builder.respond_to_esql(warnings=["No limit defined", "Line 1:2: evaluation failed"])

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = await gateway.esql_query("ROW a = 1", [])

        assert result.warnings == ["No limit defined", "Line 1:2: evaluation failed"]
        assert caught == []

    async def test_encoded_warnings(self, gateway: Elasticsearch8Gateway, es_mock_builder: es_mocker) -> None:
        """Test warnings with quotes, backslashes, percent signs, and commas are decoded intact."""
        messages = [
            'Line 1:22: evaluation of [TO_DOUBLE("abc")] failed, treating result as null.',
            'Cannot parse number [a"b\\c 100%, really]',
        ]
        es_mock_builder.respond_to_esql(warnings=messages)

        result = await gateway.esql_query("ROW a = 1", [])

        assert result.warnings == messages

    async def test_not_an_object(self, gateway: Elasticsearch8Gateway, es_mock_builder: es_mocker) -> None:
        """Test a response body that isn't an object."""
        es_mock_builder.respond_to_esql(json=["not", "an", "object"])

        with pytest.raises(InvalidQueryResponse):
            await gateway.esql_query("ROW a = 1", [])

    async def test_unparseable(self, gateway: Elasticsearch8Gateway, es_mock_builder: es_mocker) -> None:
        """Test a response that can't be parsed is an invalid response, without its contents."""
        es_mock_builder.respond_to_esql(text='{"columns": [], "values": [["PRIVATE_RESULT"]')

        with pytest.raises(InvalidQueryResponse) as err:
            await gateway.esql_query("ROW a = 1", [])

        assert "PRIVATE_RESULT" not in "".join(traceback.format_exception(err.value))

    async def test_connection_error(self, gateway: Elasticsearch8Gateway, es_mock_builder: es_mocker) -> None:
        """Test other connection errors are raised as they are."""
        es_mock_builder.respond_to_esql(status=500, json={})

        with pytest.raises(CannotConnect):
            await gateway.esql_query("ROW a = 1", [])


class Test_Transport_Warnings:
    """Test that the transport moves ES|QL warnings where the client won't raise them."""

    @staticmethod
    def transport_response(headers: dict[str, str]) -> TransportApiResponse:
        """Return a transport response with the given headers."""
        meta = MagicMock()
        meta.headers = HttpHeaders(headers)
        return TransportApiResponse(meta, {})

    @pytest.mark.parametrize("target", ["/_query", "/_query?allow_partial_results=false"])
    async def test_query_warnings_moved(self, target: str) -> None:
        """Test an ES|QL response's warnings are moved to their own header."""
        transport = Gateway8Settings(url=testconst.CONFIG_ENTRY_DATA_URL).to_client().transport
        assert isinstance(transport, CompatibilityTransport)
        sent = self.transport_response({"Warning": '299 Elasticsearch "a"'})

        with patch.object(AsyncTransport, "perform_request", AsyncMock(return_value=sent)):
            received = await transport.perform_request("POST", target)

        assert "warning" not in received.meta.headers
        assert received.meta.headers[ESQL_WARNING_HEADER] == '299 Elasticsearch "a"'

    @pytest.mark.parametrize("target", ["/", "/_bulk", "/_query/async"])
    async def test_other_warnings_kept(self, target: str) -> None:
        """Test warnings on other requests are left for the client."""
        transport = Gateway8Settings(url=testconst.CONFIG_ENTRY_DATA_URL).to_client().transport
        sent = self.transport_response({"Warning": '299 Elasticsearch "a"'})

        with patch.object(AsyncTransport, "perform_request", AsyncMock(return_value=sent)):
            received = await transport.perform_request("POST", target)

        assert received.meta.headers["warning"] == '299 Elasticsearch "a"'
        assert ESQL_WARNING_HEADER not in received.meta.headers


class Test_Parse_Warning_Header:
    """Test decoding warnings as Elasticsearch encodes them."""

    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ("", []),
            ("   ", []),
            ('299 Elasticsearch-9.1.0-abc "a"', ["a"]),
            ('299 Elasticsearch-9.1.0-abc "a", 299 Elasticsearch-9.1.0-abc "b, c"', ["a", "b, c"]),
            ('299 Elasticsearch-9.1.0-abc "TO_DOUBLE(\\"abc\\")"', ['TO_DOUBLE("abc")']),
            ('299 Elasticsearch-9.1.0-abc "a\\\\b"', ["a\\b"]),
            ('299 Elasticsearch-9.1.0-abc "a\\\\"', ["a\\"]),
            ('299 Elasticsearch-9.1.0-abc "100%25"', ["100%"]),
            ('299 Elasticsearch-9.1.0-abc "caf\udce9"', ["café"]),
            ('299 Elasticsearch-9.1.0-abc "a" "Sat, 07 Nov 2026 22:00:00 GMT"', ["a"]),
            ("not formatted by Elasticsearch", ["not formatted by Elasticsearch"]),
        ],
        ids=[
            "empty",
            "blank",
            "one",
            "several",
            "escaped quotes",
            "escaped backslash",
            "escaped backslash at end",
            "percent",
            "iso-8859-1 byte",
            "with date",
            "unformatted",
        ],
    )
    def test_parse(self, header: str, expected: list[str]) -> None:
        """Test each warning's text is decoded."""
        assert parse_warning_header(header) == expected


class Test_Joined_Warnings_Node:
    """Test that repeated warning headers survive elastic-transport, against a real HTTP server."""

    @pytest.fixture
    async def server(self, socket_enabled):
        """Run a local server that responds with the given warning headers."""

        async def handler(request: web.Request) -> web.Response:
            headers = [("Warning", value) for value in request.query.getall("warning", [])]
            return web.Response(text="{}", headers=headers, content_type="application/json")

        app = web.Application()
        app.router.add_get("/", handler)
        server = TestServer(app, host="127.0.0.1")
        await server.start_server()
        try:
            yield server
        finally:
            await server.close()

    async def test_client_uses_node(self) -> None:
        """Test the client is built with the node."""
        client = Gateway8Settings(url=testconst.CONFIG_ENTRY_DATA_URL).to_client()
        try:
            assert all(isinstance(node, JoinedWarningsNode) for node in client.transport.node_pool.all())
        finally:
            await client.close()

    @pytest.mark.parametrize(
        ("sent", "expected"),
        [
            ([], None),
            (['299 Elasticsearch "a"'], '299 Elasticsearch "a"'),
            (
                ['299 Elasticsearch "a"', '299 Elasticsearch "b"'],
                '299 Elasticsearch "a", 299 Elasticsearch "b"',
            ),
            (
                ['299 Elasticsearch "x, \\"y\\""', '299 Elasticsearch "z"'],
                '299 Elasticsearch "x, \\"y\\"", 299 Elasticsearch "z"',
            ),
        ],
        ids=["none", "one", "several", "escaped"],
    )
    async def test_warnings_joined(self, server: TestServer, sent: list[str], expected: str | None) -> None:
        """Test every warning header reaches the response metadata."""
        assert server.port is not None
        node = JoinedWarningsNode(NodeConfig("http", "127.0.0.1", server.port))
        try:
            result = await node.perform_request(
                "GET", f"/?{urlencode([('warning', value) for value in sent])}"
            )
            assert node.session is not None
            assert node.session._response_class is JoinedWarningsResponse
        finally:
            await node.close()

        assert result.meta.headers.get("warning") == expected
        assert parse_warning_header(expected or "") == [
            value.split(" ", 2)[2][1:-1].replace('\\"', '"') for value in sent
        ]

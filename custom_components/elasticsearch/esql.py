"""Run ES|QL queries, and turn their responses into results Home Assistant can use.

The `elasticsearch.query` action uses this module, and so will anything else that queries the
cluster. It owns the rules every query follows: which versions can be queried, that partial
results are never accepted, and how large a result can be.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.json import json_bytes

from custom_components.elasticsearch.errors import (
    AmbiguousQueryColumns,
    InvalidQueryResponse,
    PartialQueryResult,
    QueryNotSupported,
    QueryResultTooLarge,
    TooManyQueryRows,
    TruncatedQueryResult,
)

if TYPE_CHECKING:  # pragma: no cover
    from custom_components.elasticsearch.es_gateway import ElasticsearchGateway, EsqlResponse

# Querying needs a newer cluster than publishing. Before 8.18, ES|QL can't filter on or compare
# the `date_nanos` timestamps the integration publishes. Before 8.19 (and in 9.0), it doesn't
# accept `allow_partial_results`, so partial results can't be turned off.
QUERY_MINIMUM_VERSIONS: dict[int, tuple[int, int]] = {8: (8, 19), 9: (9, 1)}
QUERY_MINIMUM_VERSION_TEXT: str = "8.19 or later, or 9.1 or later on 9.x"

# The most rows a query may return. More than this is an error, never a truncated result.
MAX_ROWS: int = 1000

# The most JSON a query's result may take up, in bytes.
MAX_RESULT_BYTES: int = 1024 * 1024

# How many queries one config entry runs at once. Others wait for their turn.
MAX_CONCURRENT_QUERIES: int = 4

# Elasticsearch adds this warning when a query has no LIMIT and it applies its default
_DEFAULT_LIMIT_WARNING = re.compile(r"^No limit defined, adding default limit of \[(\d+)\]$")


@dataclass(frozen=True)
class QueryColumn:
    """A column in a query's result."""

    name: str
    type: str


@dataclass(frozen=True)
class QueryResult:
    """The result of an ES|QL query, as named rows."""

    columns: list[QueryColumn]
    rows: list[dict[str, Any]]
    warnings: list[str]
    took_ms: int | None

    def as_dict(self) -> dict[str, Any]:
        """Return the result in the documented form, which is also what the action responds with."""
        return {
            "columns": [{"name": column.name, "type": column.type} for column in self.columns],
            "rows": self.rows,
            "warnings": self.warnings,
            "took_ms": self.took_ms,
        }


class QueryRunner:
    """Runs ES|QL queries for one config entry."""

    def __init__(self, gateway: ElasticsearchGateway) -> None:
        """Initialize the runner."""
        self._gateway = gateway
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_QUERIES)

    async def async_query(self, query: str, params: list[Any] | None = None) -> QueryResult:
        """Run a query and return its result.

        Raises QueryError when the cluster can't be queried or the result can't be accepted, and
        the gateway's connection errors when the request fails.
        """

        check_query_support(self._gateway)

        async with self._semaphore:
            response = await self._gateway.esql_query(query, list(params or []))

        return normalize_response(response)


def check_query_support(gateway: ElasticsearchGateway) -> None:
    """Raise QueryNotSupported unless the connected cluster's version supports querying."""

    if gateway.build_flavor == "serverless":
        return

    version = gateway.cluster_version
    if not supports_query(version):
        msg = f"Querying requires Elasticsearch {QUERY_MINIMUM_VERSION_TEXT}."
        raise QueryNotSupported(msg, version=version)


def supports_query(version: str | None) -> bool:
    """Return whether a stateful cluster of this version supports querying."""

    if version is None:
        return False

    parts = version.split(".")
    if len(parts) < 2 or not all(part.isdecimal() for part in parts[:2]):
        return False

    major, minor = int(parts[0]), int(parts[1])
    minimum = QUERY_MINIMUM_VERSIONS.get(major)

    if minimum is None:
        return major > max(QUERY_MINIMUM_VERSIONS)

    return (major, minor) >= minimum


def normalize_response(response: EsqlResponse) -> QueryResult:
    """Turn ES|QL's columns and values into named rows, and check the result can be accepted."""

    body = response.body

    # Partial results are turned off, but a cluster setting or a future version could still
    # return them. They're never accepted as complete.
    if body.get("is_partial") is True:
        msg = "Elasticsearch returned partial results for the query."
        raise PartialQueryResult(msg)

    columns = _read_columns(body.get("columns"))
    values = body.get("values")

    if not isinstance(values, list):
        msg = "The query response has no list of values."
        raise InvalidQueryResponse(msg)

    if len(values) > MAX_ROWS:
        msg = f"The query returned {len(values)} rows, more than the limit of {MAX_ROWS}."
        raise TooManyQueryRows(msg, rows=len(values), limit=MAX_ROWS)

    default_limit = _default_limit_applied(response.warnings)
    if default_limit is not None and len(values) >= default_limit:
        msg = f"Elasticsearch applied its default limit of {default_limit} rows, so the result may be incomplete."
        raise TruncatedQueryResult(msg, limit=default_limit)

    duplicates = sorted(
        name for name, count in Counter(column.name for column in columns).items() if count > 1
    )
    if duplicates:
        msg = "The query returned more than one column with the same name."
        raise AmbiguousQueryColumns(msg, columns=duplicates)

    names = [column.name for column in columns]
    rows: list[dict[str, Any]] = []
    for row in values:
        if not isinstance(row, list) or len(row) != len(names):
            msg = "A row in the query response doesn't match its columns."
            raise InvalidQueryResponse(msg)
        rows.append(dict(zip(names, row, strict=True)))

    took = body.get("took")
    took_ms = took if isinstance(took, int) and not isinstance(took, bool) else None

    result = QueryResult(columns=columns, rows=rows, warnings=list(response.warnings), took_ms=took_ms)

    size = len(json_bytes(result.as_dict()))
    if size > MAX_RESULT_BYTES:
        msg = f"The query's result is {size} bytes, more than the limit of {MAX_RESULT_BYTES}."
        raise QueryResultTooLarge(msg, size=size, limit=MAX_RESULT_BYTES)

    return result


def _read_columns(columns: Any) -> list[QueryColumn]:
    """Read the column metadata from a query response."""

    if not isinstance(columns, list):
        msg = "The query response has no list of columns."
        raise InvalidQueryResponse(msg)

    result: list[QueryColumn] = []
    for column in columns:
        if (
            not isinstance(column, dict)
            or not isinstance(column.get("name"), str)
            or not isinstance(column.get("type"), str)
        ):
            msg = "A column in the query response has no name or type."
            raise InvalidQueryResponse(msg)
        result.append(QueryColumn(name=column["name"], type=column["type"]))

    return result


def _default_limit_applied(messages: list[str]) -> int | None:
    """Return the default row limit Elasticsearch says it applied, if it applied one."""

    for message in messages:
        match = _DEFAULT_LIMIT_WARNING.match(message)
        if match:
            return int(match.group(1))

    return None

"""Tests for the encoder module."""

import builtins
import json
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from custom_components.elasticsearch.encoder import Serializer, convert_set_to_list
from elastic_transport import SerializationError


@pytest.fixture
def forbid_optional_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail on optional library imports, even when another test already loaded them."""
    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.split(".", maxsplit=1)[0] in {"numpy", "pandas"}:
            pytest.fail(f"Serialization must not import {name} on the event loop")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2026, 11, 6, 12, 30, tzinfo=UTC), "2026-11-06T12:30:00+00:00"),
        (date(2026, 11, 6), "2026-11-06"),
        (time(12, 30), "12:30:00"),
        (Path("/config/example"), "/config/example"),
        ({3, 1, 2}, [1, 2, 3]),
        (Decimal("12.5"), 12.5),
        (UUID("12345678-1234-5678-1234-567812345678"), "12345678-1234-5678-1234-567812345678"),
    ],
    ids=["datetime", "date", "time", "path", "set", "decimal", "uuid"],
)
async def test_serializer_nested_attribute_without_optional_imports(
    value: Any, expected: Any, forbid_optional_imports: None
) -> None:
    """List attributes serialize on the event loop without importing numpy or pandas."""
    attributes = convert_set_to_list([value])

    result = Serializer().dumps({"attribute": attributes})

    assert json.loads(result) == {"attribute": [expected]}


async def test_serializer_sorts_sets(forbid_optional_imports: None) -> None:
    """The serializer also handles sets that have not passed through the formatter."""
    assert json.loads(Serializer().dumps({"attribute": {3, 1, 2}})) == {"attribute": [1, 2, 3]}


async def test_serializer_rejects_unknown_values_without_optional_imports(
    forbid_optional_imports: None,
) -> None:
    """Unsupported values fail without loading optional libraries on the event loop."""
    with pytest.raises(SerializationError):
        Serializer().dumps({"attribute": [object()]})


def test_convert_set_to_list_dict_with_datetime_values() -> None:
    """Dict attributes with datetime values are stringified for Elasticsearch."""
    start = datetime(2026, 6, 25, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 25, 0, 30, tzinfo=UTC)
    data = {"start": start, "end": end, "consumption": 0.687}

    result = convert_set_to_list(data)

    assert isinstance(result, str)
    parsed = json.loads(result)
    assert parsed["start"] == start.isoformat()
    assert parsed["end"] == end.isoformat()
    assert parsed["consumption"] == 0.687


def test_convert_set_to_list_list_of_dicts_with_datetime_values() -> None:
    """List attributes (e.g. Octopus Energy charges) serialize nested datetimes."""
    start = datetime(2026, 6, 25, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 25, 0, 30, tzinfo=UTC)
    charges = [{"start": start, "end": end, "consumption": 0.5}]

    result = convert_set_to_list(charges)

    assert isinstance(result, list)
    assert len(result) == 1
    parsed = json.loads(result[0])
    assert parsed["start"] == start.isoformat()
    assert parsed["end"] == end.isoformat()


def test_convert_set_to_list_set_sorted() -> None:
    """Sets are converted to sorted lists."""
    assert convert_set_to_list({3, 1, 2}) == [1, 2, 3]

"""Tests for the encoder module."""

import json
from datetime import UTC, datetime

from custom_components.elasticsearch.encoder import convert_set_to_list


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

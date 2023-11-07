"""Utilities for working with the AIOClient Mock."""

from dataclasses import dataclass
import json
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from yarl import URL
from typing import cast

@dataclass
class MockCall:
    """Mock API Call."""

    method: str
    url: URL
    data: str
    headers: dict

def extract_es_bulk_requests(aioclient_mock: AiohttpClientMocker) -> list[MockCall]:
    """Extract ES Bulk request from the collection of mock calls."""
    assert isinstance(aioclient_mock.mock_calls, list)

    bulk_requests: list[MockCall] = []

    for call in aioclient_mock.mock_calls:
        (method, url, data, headers) = cast(tuple[str, URL, dict, dict], call)
        if method == "POST" and url.path.endswith("/_bulk"):
            output = []
            for payload in data.decode().rstrip().split("\n"):
                output.append(json.loads(payload))

            bulk_requests.append(MockCall(method, url, output, headers))

    return bulk_requests

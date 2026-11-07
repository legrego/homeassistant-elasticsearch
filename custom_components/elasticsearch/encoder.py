"""Custom JSON encoder for Elasticsearch."""

import json
from typing import Any

from elastic_transport import JsonSerializer
from homeassistant.helpers.json import json_encoder_default


def convert_set_to_list(data: Any) -> Any:
    """Convert set to list and stringify dict attributes."""

    if isinstance(data, set):
        output = [convert_set_to_list(item) for item in data]
        output.sort()
        return output

    if isinstance(data, dict):
        return json.dumps(
            {key: convert_set_to_list(value) for key, value in data.items()},
            default=json_encoder_default,
        )

    if isinstance(data, list):
        return [convert_set_to_list(item) for item in data]

    if isinstance(data, tuple):
        return tuple(convert_set_to_list(item) for item in data)

    return data


class Serializer(JsonSerializer):
    """Serialize Home Assistant values without importing optional libraries."""

    def default(self, data: Any) -> Any:
        """Handle Home Assistant types before the transport's JSON-only fallback."""

        if isinstance(data, set):
            return convert_set_to_list(data)

        try:
            return json_encoder_default(data)
        except TypeError:
            # The Elasticsearch client's fallback lazily imports numpy and pandas,
            # which can read timezone files on the event loop. The transport's
            # serializer handles UUIDs and decimals without those imports.
            return super().default(data)

"""Custom JSON encoder for Elasticsearch."""

import json
from typing import Any

from elasticsearch8.serializer import JSONSerializer
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
            ensure_ascii=False,
            separators=(",", ":"),
        )

    if isinstance(data, list):
        return [convert_set_to_list(item) for item in data]

    if isinstance(data, tuple):
        return tuple(convert_set_to_list(item) for item in data)

    return data


class Serializer(JSONSerializer):
    """JSONSerializer which serializes sets to lists."""

    def json_dumps(self, data: Any) -> bytes:
        """Serialize data to JSON."""

        return json.dumps(
            data, default=self.default, ensure_ascii=False, separators=(",", ":"), cls=Encoder
        ).encode("utf-8", "surrogatepass")

    def default(self, data: Any) -> Any:
        """Entry point."""

        return super().default(convert_set_to_list(data))


class Encoder(json.JSONEncoder):
    """JSONSerializer which serializes sets to lists."""

    def default(self, o: Any) -> Any:
        """Entry point."""

        try:
            return json_encoder_default(o)
        except TypeError:
            return super().default(convert_set_to_list(o))

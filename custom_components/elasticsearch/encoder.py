"""Custom JSON encoder for Elasticsearch."""

import json
from typing import Any

from elasticsearch8.serializer import JSONSerializer


def convert_set_to_list(data: Any) -> Any:
    """Convert set to list."""

    if isinstance(data, set):
        output = [convert_set_to_list(item) for item in data]
        output.sort()
        return output

    if isinstance(data, dict):
        return {key: convert_set_to_list(value) for key, value in data.items()}

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

        return JSONSerializer.default(self, convert_set_to_list(data))


class Encoder(json.JSONEncoder):
    """JSONSerializer which serializes sets to lists."""

    def default(self, o: Any) -> Any:
        """Entry point."""

        return json.JSONEncoder.default(self, convert_set_to_list(o))

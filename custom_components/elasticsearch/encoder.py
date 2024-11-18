"""Custom JSON encoder for Elasticsearch."""

from typing import Any

from elasticsearch8.serializer import JSONSerializer


class Encoder(JSONSerializer):
    """JSONSerializer which serializes sets to lists."""

    def needs_serialization(self, data: Any) -> bool:
        """Check if data needs to be serialized."""
        return isinstance(data, (set, dict, list, tuple))

    def default(self, data: Any) -> Any:
        """Entry point."""

        if not self.needs_serialization(data):
            return data

        if isinstance(data, set):
            output = [self.default(item) for item in data]
            output.sort()
            return output

        if isinstance(data, dict):
            return {key: self.default(value) for key, value in data.items()}

        if isinstance(data, list):
            return [self.default(item) for item in data]

        if isinstance(data, tuple):
            return tuple(self.default(item) for item in data)

        return JSONSerializer.default(self, data)

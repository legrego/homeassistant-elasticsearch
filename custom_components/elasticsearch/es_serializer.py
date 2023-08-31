"""Gets the custom JSON serializer."""


def get_serializer():
    """Gets the custom JSON serializer."""
    from elasticsearch7.serializer import JSONSerializer

    class SetEncoder(JSONSerializer):
        """JSONSerializer which serializes sets to lists."""

        def default(self, data):
            """Entry point."""
            if isinstance(data, set):
                return list(data)
            return JSONSerializer.default(self, data)

    return SetEncoder()

"""Gets the custom JSON serializer."""


def get_serializer():
    """Get the custom JSON serializer."""
    from elasticsearch7.serializer import JSONSerializer

    class SetEncoder(JSONSerializer):
        """JSONSerializer which serializes sets to lists."""

        def default(self, data):
            """Entry point."""
            if isinstance(data, set):
                output = list(data)
                output.sort()
                return output
            return JSONSerializer.default(self, data)

    return SetEncoder()

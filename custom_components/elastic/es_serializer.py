"""Gets the custom JSON serializer"""


def get_serializer():
    """Gets the custom JSON serializer"""
    from elasticsearch.serializer import JSONSerializer

    class SetEncoder(JSONSerializer):
        """JSONSerializer which serializes sets to lists"""

        def default(self, data):
            """entry point"""
            if isinstance(data, set):
                return list(data)
            return JSONSerializer.default(self, data)

    return SetEncoder()

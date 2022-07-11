"""Maintains information about the version of Elasticsearch"""


class ElasticsearchVersion:
    """Maintains information about the version of Elasticsearch"""

    def __init__(self, client):
        self._client = client
        self._version_number_str = None
        self.major = None
        self.minor = None

    async def async_init(self):
        """I/O bound init"""
        version = (await self._client.info())["version"]
        version_number_parts = version["number"].split(".")
        self._version_number_str = version["number"]
        self.major = int(version_number_parts[0])
        self.minor = int(version_number_parts[1])

    def is_supported_version(self):
        """Determines if this version of ES is supported by this component"""
        return self.major == 8 or (self.major == 7 and self.minor >= 11)

    def to_string(self):
        """Returns a string representation of the current ES version"""
        return self._version_number_str

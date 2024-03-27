"""Maintain information about the version of Elasticsearch."""


class ElasticsearchVersion:
    """Maintain information about the version of Elasticsearch."""

    def __init__(self, client):
        """ES Version Initialization."""
        self._client = client
        self._version_number_str = None
        self.major = None
        self.minor = None
        self.build_flavor = None

    async def async_init(self):
        """I/O bound init."""
        version = (await self._client.info())["version"]
        version_number_parts = version["number"].split(".")
        self._version_number_str = version["number"]
        self.major = int(version_number_parts[0])
        self.minor = int(version_number_parts[1])
        self.build_flavor = version.get("build_flavor", "unknown")

    def is_supported_version(self):
        """Determine if this version of ES is supported by this component."""
        return self.major == 8 or (self.major == 7 and self.minor >= 11)

    def meets_minimum_version(self, major, minor):
        """Determine if this version of ES meets the minimum version requirements."""
        return self.major > major or (self.major == major and self.minor >= minor)

    def is_serverless(self):
        """Determine if this is a serverless ES instance."""
        return self.build_flavor == "serverless"

    def to_string(self):
        """Return a string representation of the current ES version."""
        return self._version_number_str

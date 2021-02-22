"""Maintains information about the verion of Elasticsearch"""

from .logger import LOGGER


class ElasticsearchVersion:
    """Maintains information about the verion of Elasticsearch"""

    def __init__(self, client):
        self._client = client
        self._version_number_str = None
        self.major = None
        self.minor = None
        self.build_flavor = None

    async def async_init(self):
        """I/O bound init"""
        version = (await self._client.info())["version"]
        version_number_parts = version["number"].split(".")
        self._version_number_str = version["number"]
        self.major = int(version_number_parts[0])
        self.minor = int(version_number_parts[1])
        self.build_flavor = version["build_flavor"]

        if self.is_oss_distribution():
            LOGGER.warning(
                "\
                Support for the Elasticseach's OSS distribution is deprecated, \
                and will not work in a future release. \
                Download the default distribution from https://elastic.co/downloads \
            "
            )

    def is_supported_version(self):
        """Determines if this version of ES is supported by this component"""
        return self.major == 7

    def is_oss_distribution(self):
        """Determines if this is the OSS distribution"""
        return self.build_flavor == "oss"

    def is_default_distribution(self):
        """Determines if this is the default distribution"""
        return self.build_flavor == "default"

    def to_string(self):
        """Returns a string representation of the current ES version"""
        return self._version_number_str

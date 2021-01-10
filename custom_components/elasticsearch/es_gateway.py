"""Encapsulates Elasticsearch operations"""
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)

from .const import CONF_SSL_CA_PATH
from .es_serializer import get_serializer
from .es_version import ElasticsearchVersion
from .logger import LOGGER


class ElasticsearchGateway:
    """Encapsulates Elasticsearch operations"""

    def __init__(self, hass, config):
        """Initialize the gateway"""
        self._hass = hass
        self._url = config.get(CONF_URL)
        self._timeout = config.get(CONF_TIMEOUT)
        self._username = config.get(CONF_USERNAME)
        self._password = config.get(CONF_PASSWORD)
        self._verify_certs = config.get(CONF_VERIFY_SSL)
        self._ca_certs = config.get(CONF_SSL_CA_PATH)

        LOGGER.debug("Creating Elasticsearch client for %s", self._url)
        self.client = self._create_es_client()
        self.sync_client = self._create_es_client(sync=True)
        self.es_version = ElasticsearchVersion(self.client)

    async def async_init(self):
        """I/O bound init"""

        await self.es_version.async_init()

        if not self.es_version.is_supported_version():
            LOGGER.warning(
                "UNSUPPORTED VERSION OF ELASTICSEARCH DETECTED: %s. \
                This may function in unexpected ways, or fail entirely!",
                self.es_version.to_string(),
            )

    def get_client(self):
        """Returns the underlying ES Client"""
        return self.client

    def get_sync_client(self):
        """Returns the underlying ES Client"""
        return self.sync_client

    def _create_es_client(self, sync=False):
        """Constructs an instance of the Elasticsearch client"""
        from elasticsearch import AsyncElasticsearch, Elasticsearch

        use_basic_auth = self._username is not None and self._password is not None

        serializer = get_serializer()

        if use_basic_auth:
            auth = (self._username, self._password)
            return (
                Elasticsearch(
                    [self._url],
                    http_auth=auth,
                    serializer=serializer,
                    verify_certs=self._verify_certs,
                    ca_certs=self._ca_certs,
                    timeout=self._timeout,
                )
                if sync
                else AsyncElasticsearch(
                    [self._url],
                    http_auth=auth,
                    serializer=serializer,
                    verify_certs=self._verify_certs,
                    ca_certs=self._ca_certs,
                    timeout=self._timeout,
                )
            )

        return (
            Elasticsearch(
                [self._url],
                serializer=serializer,
                verify_certs=self._verify_certs,
                ca_certs=self._ca_certs,
                timeout=self._timeout,
            )
            if sync
            else AsyncElasticsearch(
                [self._url],
                serializer=serializer,
                verify_certs=self._verify_certs,
                ca_certs=self._ca_certs,
                timeout=self._timeout,
            )
        )

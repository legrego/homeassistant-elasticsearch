"""Encapsulates Elasticsearch operations"""
import base64
import binascii
from homeassistant.const import (
    CONF_URL, CONF_USERNAME, CONF_PASSWORD, CONF_VERIFY_SSL
)
from .const import (CONF_CLOUD_ID, CONF_SSL_CA_PATH)
from .es_version import ElasticsearchVersion
from .es_serializer import get_serializer
from .logger import LOGGER

class ElasticsearchGateway:
    """Encapsulates Elasticsearch operations"""

    def __init__(self, hass, config):
        """Initialize the gateway"""
        self._hass = hass
        self._url = config.get(CONF_URL)
        self._username = config.get(CONF_USERNAME)
        self._password = config.get(CONF_PASSWORD)
        self._cloud_id = config.get(CONF_CLOUD_ID)
        self._verify_certs = config.get(CONF_VERIFY_SSL)
        self._ca_certs = config.get(CONF_SSL_CA_PATH)

        if self._cloud_id:
            self._url = decode_cloud_id(self._cloud_id)

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
                self.es_version.to_string()
            )

    def get_client(self):
        """Returns the underlying ES Client"""
        return self.client

    def get_sync_client(self):
        """Returns the underlying ES Client"""
        return self.sync_client

    def _create_es_client(self, sync=False):
        """Constructs an instance of the Elasticsearch client"""
        from elasticsearch_async import AsyncElasticsearch
        from elasticsearch import Elasticsearch

        use_basic_auth = self._username is not None and self._password is not None

        serializer = get_serializer()

        if use_basic_auth:
            auth = (self._username, self._password)
            return Elasticsearch(
                [self._url],
                http_auth=auth,
                serializer=serializer,
                verify_certs=self._verify_certs,
                ca_certs=self._ca_certs
            ) if sync else AsyncElasticsearch(
                [self._url],
                http_auth=auth,
                serializer=serializer,
                verify_certs=self._verify_certs,
                ca_certs=self._ca_certs
            )

        return Elasticsearch(
            [self._url],
            serializer=serializer,
            verify_certs=self._verify_certs,
            ca_certs=self._ca_certs
        ) if sync else AsyncElasticsearch(
            [self._url],
            serializer=serializer,
            verify_certs=self._verify_certs,
            ca_certs=self._ca_certs
        )


def decode_cloud_id(cloud_id):
    """Decodes the cloud id"""

    # Logic adapted from https://github.com/elastic/beats/blob/6.5/libbeat/cloudid/cloudid.go

    this_cloud_id = cloud_id

    # 1. Ignore anything before `:`
    idx = this_cloud_id.rfind(':')
    if idx >= 0:
        this_cloud_id = this_cloud_id[idx+1:]

    # 2. base64 decode
    try:
        this_cloud_id = base64.b64decode(this_cloud_id).decode('utf-8')
    except binascii.Error:
        raise Exception(
            "Invalid cloud_id. Error base64 decoding {}".format(cloud_id))

    # 3. separate based on `$`
    words = this_cloud_id.split("$")
    if len(words) < 3:
        raise Exception(
            "Invalid cloud_id: expected at least 3 parts in {}".format(cloud_id))

    # 4. extract port from the ES host, or use 443 as the default
    host, port = extract_port_from_name(words[0], 443)
    es_id, es_port = extract_port_from_name(words[1], port)

    # 5. form the URLs
    es_url = "https://{}.{}:{}".format(es_id, host, es_port)

    return es_url


def extract_port_from_name(name, default_port):
    """
    extractPortFromName takes a string in the form `id:port` and returns the ID and the port
    If there's no `:`, the default port is returned
    """
    idx = name.rfind(":")
    if idx >= 0:
        return name[:idx], name[idx+1:]

    return name, default_port

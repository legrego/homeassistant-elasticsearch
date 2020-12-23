"""Encapsulates Elasticsearch operations"""
from homeassistant.const import (
    CONF_URL,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_VERIFY_SSL,
    CONF_TIMEOUT,
)
from .const import CONF_SSL_CA_PATH
from .es_version import ElasticsearchVersion
from .es_serializer import get_serializer
from .logger import LOGGER
from .errors import (
    CannotConnect,
    AuthenticationRequired,
    InsufficientPrivileges,
    ElasticException,
    UntrustedCertificate,
)
from http.client import RemoteDisconnected
import ssl
import urllib3


class ElasticsearchGateway:
    """Encapsulates Elasticsearch operations"""

    def __init__(self, config, connection_class=None):
        """Initialize the gateway"""
        self._url = config.get(CONF_URL)
        self._timeout = config.get(CONF_TIMEOUT)
        self._username = config.get(CONF_USERNAME)
        self._password = config.get(CONF_PASSWORD)
        self._verify_certs = config.get(CONF_VERIFY_SSL, True)
        self._ca_certs = config.get(CONF_SSL_CA_PATH)
        self._connection_class = connection_class

        self.client = None
        self.sync_client = None
        self.es_version = None

    def check_connection(self):
        """Performs connection checks for setup"""
        from elasticsearch import (
            ConnectionError,
            SSLError,
            AuthenticationException,
            AuthorizationException,
            ElasticsearchException,
        )

        try:
            self.sync_client = self._create_es_client(sync=True)
            self.sync_client.info()
        except SSLError as err:
            raise UntrustedCertificate(err)
        except ConnectionError as err:
            raise CannotConnect(err)
        except AuthenticationException as err:
            raise AuthenticationRequired(err)
        except AuthorizationException as err:
            raise InsufficientPrivileges(err)
        except ElasticsearchException as err:
            raise ElasticException(err)
        finally:
            self.sync_client.close()
            self.sync_client = None

    async def async_init(self):
        """I/O bound init"""

        LOGGER.debug("Creating Elasticsearch client for %s", self._url)
        self.client = self._create_es_client()
        self.sync_client = self._create_es_client(sync=True)
        self.es_version = ElasticsearchVersion(self.client)

        await self.es_version.async_init()

        if not self.es_version.is_supported_version():
            LOGGER.warning(
                "UNSUPPORTED VERSION OF ELASTICSEARCH DETECTED: %s. \
                This may function in unexpected ways, or fail entirely!",
                self.es_version.to_string(),
            )
        LOGGER.debug("Gateway initialized")

    async def async_stop_gateway(self):
        await self.client.close()
        self.sync_client.close()

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
                    connection_class=self._connection_class,
                )
                if sync
                else AsyncElasticsearch(
                    [self._url],
                    http_auth=auth,
                    serializer=serializer,
                    verify_certs=self._verify_certs,
                    ca_certs=self._ca_certs,
                    timeout=self._timeout,
                    connection_class=self._connection_class,
                )
            )

        return (
            Elasticsearch(
                [self._url],
                serializer=serializer,
                verify_certs=self._verify_certs,
                ca_certs=self._ca_certs,
                timeout=self._timeout,
                connection_class=self._connection_class,
            )
            if sync
            else AsyncElasticsearch(
                [self._url],
                serializer=serializer,
                verify_certs=self._verify_certs,
                ca_certs=self._ca_certs,
                timeout=self._timeout,
                connection_class=self._connection_class,
            )
        )

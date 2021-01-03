"""Encapsulates Elasticsearch operations"""
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.helpers.typing import HomeAssistantType

from .const import CONF_SSL_CA_PATH
from .errors import (
    AuthenticationRequired,
    CannotConnect,
    ElasticException,
    InsufficientPrivileges,
    UntrustedCertificate,
)
from .es_serializer import get_serializer
from .es_version import ElasticsearchVersion
from .logger import LOGGER


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
        self.es_version = None

    async def check_connection(self, hass: HomeAssistantType):
        """Performs connection checks for setup"""
        from elasticsearch import (
            AuthenticationException,
            AuthorizationException,
            ConnectionError,
            ElasticsearchException,
            SSLError,
        )

        # TODO use async client via hass.add_executor_job

        client = None
        try:
            client = self._create_es_client()
            await client.info()
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
            if client:
                client.close()
                client = None

    async def async_init(self):
        """I/O bound init"""

        LOGGER.debug("Creating Elasticsearch client for %s", self._url)
        self.client = self._create_es_client()
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

    def get_client(self):
        """Returns the underlying ES Client"""
        return self.client

    def _create_es_client(self):
        """Constructs an instance of the Elasticsearch client"""
        from elasticsearch import AsyncElasticsearch

        use_basic_auth = self._username is not None and self._password is not None

        serializer = get_serializer()

        if use_basic_auth:
            auth = (self._username, self._password)
            return AsyncElasticsearch(
                [self._url],
                http_auth=auth,
                serializer=serializer,
                verify_certs=self._verify_certs,
                ca_certs=self._ca_certs,
                timeout=self._timeout,
            )

        return AsyncElasticsearch(
            [self._url],
            serializer=serializer,
            verify_certs=self._verify_certs,
            ca_certs=self._ca_certs,
            timeout=self._timeout,
        )

"""Encapsulates Elasticsearch operations."""
import aiohttp
from elasticsearch7 import AIOHttpConnection
from homeassistant.const import (
    CONF_API_KEY,
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)

from .const import CONF_SSL_CA_PATH
from .errors import (
    AuthenticationRequired,
    CannotConnect,
    ElasticException,
    InsufficientPrivileges,
    UnsupportedVersion,
    UntrustedCertificate,
)
from .es_serializer import get_serializer
from .es_version import ElasticsearchVersion
from .logger import LOGGER


class ElasticsearchGateway:
    """Encapsulates Elasticsearch operations."""

    def __init__(self, config):
        """Initialize the gateway."""
        self._url = config.get(CONF_URL)
        self._timeout = config.get(CONF_TIMEOUT)
        self._username = config.get(CONF_USERNAME)
        self._password = config.get(CONF_PASSWORD)
        self._api_key = config.get(CONF_API_KEY)
        self._verify_certs = config.get(CONF_VERIFY_SSL, True)
        self._ca_certs = config.get(CONF_SSL_CA_PATH)

        self.client = None
        self.es_version = None

    async def check_connection(self):
        """Perform connection checks for setup."""
        from elasticsearch7 import (
            AuthenticationException,
            AuthorizationException,
            ConnectionError as ESConnectionError,
            ElasticsearchException,
            SSLError,
        )

        client = None
        is_supported_version = True
        try:
            client = self._create_es_client()

            es_version = ElasticsearchVersion(client)
            await es_version.async_init()

            is_supported_version = es_version.is_supported_version()
        except SSLError as err:
            raise UntrustedCertificate(err) from err
        except ESConnectionError as err:
            if isinstance(
                err.info, aiohttp.client_exceptions.ClientConnectorCertificateError
            ):
                raise UntrustedCertificate(err) from err
            raise CannotConnect(err) from err
        except AuthenticationException as err:
            raise AuthenticationRequired(err) from err
        except AuthorizationException as err:
            raise InsufficientPrivileges(err) from err
        except ElasticsearchException as err:
            raise ElasticException(err) from err
        except Exception as err:
            raise ElasticException(err) from err
        finally:
            if client:
                await client.close()
                client = None

        if not is_supported_version:
            raise UnsupportedVersion()

    async def async_init(self):
        """I/O bound init."""

        LOGGER.debug("Creating Elasticsearch client for %s", self._url)
        self.client = self._create_es_client()
        self.es_version = ElasticsearchVersion(self.client)

        await self.es_version.async_init()

        if not self.es_version.is_supported_version():
            LOGGER.fatal(
                "UNSUPPORTED VERSION OF ELASTICSEARCH DETECTED: %s.",
                self.es_version.to_string(),
            )
            raise UnsupportedVersion()
        LOGGER.debug("Gateway initialized")

    async def async_stop_gateway(self):
        """Stop the ES Gateway."""
        await self.client.close()

    def get_client(self):
        """Return the underlying ES Client."""
        return self.client

    def _create_es_client(self):
        """Construct an instance of the Elasticsearch client."""
        from elasticsearch7._async.client import AsyncElasticsearch

        use_basic_auth = self._username is not None and self._password is not None
        use_api_key = self._api_key is not None

        serializer = get_serializer()

        if use_basic_auth:
            auth = (self._username, self._password)
            return AsyncElasticsearch(
                [self._url],
                http_auth=auth,
                serializer=serializer,
                verify_certs=self._verify_certs,
                ssl_show_warn=self._verify_certs,
                ca_certs=self._ca_certs,
                timeout=self._timeout,
            )

        if use_api_key:
            return AsyncElasticsearch(
                [self._url],
                headers={"Authorization": f"ApiKey {self._api_key}"},
                serializer=serializer,
                verify_certs=self._verify_certs,
                ssl_show_warn=self._verify_certs,
                ca_certs=self._ca_certs,
                timeout=self._timeout,
            )

        return AsyncElasticsearch(
            [self._url],
            serializer=serializer,
            verify_certs=self._verify_certs,
            ssl_show_warn=self._verify_certs,
            ca_certs=self._ca_certs,
            timeout=self._timeout,
        )


class ESConnection(AIOHttpConnection):
    """Connection class for ES connections."""

    def __init__ (self, **kwargs):
        """Init ESConnection."""
        super().__init__(**kwargs)

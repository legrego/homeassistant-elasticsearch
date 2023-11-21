"""Encapsulates Elasticsearch operations."""
import asyncio
import time

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
    UnsupportedVersion,
    convert_es_error,
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

        self._connection_monitor_ref = None
        self._active_connection_error = False
        self._connection_monitor_active = False

    async def async_init(self):
        """I/O bound init."""

        LOGGER.debug("Creating Elasticsearch client for %s", self._url)
        try:
            self.client = self._create_es_client()

            self.es_version = ElasticsearchVersion(self.client)
            await self.es_version.async_init()
        except Exception as err:
            raise convert_es_error("Gateway initialization failed", err) from err

        if not self.es_version.is_supported_version():
            LOGGER.fatal(
                "UNSUPPORTED VERSION OF ELASTICSEARCH DETECTED: %s.",
                self.es_version.to_string(),
            )
            raise UnsupportedVersion()

        self._start_connection_monitor_task()

        LOGGER.debug("Gateway initialized")

    async def async_stop_gateway(self):
        """Stop the ES Gateway."""
        LOGGER.debug("Stopping ES Gateway")

        self._connection_monitor_active = False
        self._active_connection_error = False
        if self._connection_monitor_ref is not None:
            self._connection_monitor_ref.cancel()
            self._connection_monitor_ref = None

        if self.client:
            await self.client.close()
            self.client = None

        LOGGER.debug("ES Gateway stopped")

    def get_client(self):
        """Return the underlying ES Client."""
        return self.client

    @property
    def active_connection_error(self):
        """Returns if there is a known connection error."""
        return self._active_connection_error

    def notify_of_connection_error(self):
        """Notify the gateway of a connection error."""
        self._active_connection_error = True

    def _start_connection_monitor_task(self):
        """Initialize connection monitor task."""
        LOGGER.debug("Starting connection monitor")
        self._connection_monitor_ref = asyncio.ensure_future(self._connection_monitor_task())
        self._connection_monitor_active = True

    async def _connection_monitor_task(self):
        from elasticsearch7 import TransportError
        next_test = time.monotonic() + 30
        while self._connection_monitor_active:
            try:
                can_test = next_test <= time.monotonic()
                if can_test:
                    LOGGER.debug("Starting connection test.")
                    next_test = time.monotonic() + 30
                    had_error = self._active_connection_error

                    await self.client.info()

                    self._active_connection_error = False
                    LOGGER.debug("Finished connection test.")

                    if had_error:
                        LOGGER.info("Connection to [%s] has been reestablished. Operations will resume.")
            except TransportError as transport_err:
                LOGGER.debug("Finished connection test with TransportError")
                ignorable_error = isinstance(transport_err.status_code, int) and transport_err.status_code <= 403
                # Do not spam the logs with connection errors if we already know there is a problem.
                if not ignorable_error and not self.active_connection_error:
                    LOGGER.exception("Connection error. Operations will be paused until connection is reestablished. %s", transport_err)
                    self._active_connection_error = True
            except Exception as err:
                LOGGER.exception("Error during connection monitoring task %s", err)
            finally:
                if self._connection_monitor_active:
                    await asyncio.sleep(1)

    async def async_test_connection(self):
        """Perform basic connection test."""
        try:
            await self.es_version.async_refresh()
            return True
        except Exception:
            return False

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

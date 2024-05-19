"""Encapsulates Elasticsearch operations."""

import asyncio
import time

from elasticsearch7 import TransportError as TransportError7
from elasticsearch8 import TransportError as TransportError8
from elasticsearch8._async.client import AsyncElasticsearch as AsyncElasticsearch7
from elasticsearch8._async.client import AsyncElasticsearch as AsyncElasticsearch8
from homeassistant.core import HomeAssistant

from .const import CONF_SSL_CA_PATH
from .errors import (
    InsufficientPrivileges,
    UnsupportedVersion,
    convert_es_error,
)
from .es_serializer import get_serializer
from .es_version import ElasticsearchVersion
from .logger import LOGGER


class ElasticsearchGateway(ABC):
    """Encapsulates Elasticsearch operations."""

    def __init__(
        self,
        config_entry: ConfigEntry = None,
        hass: HomeAssistant = None,
    ):
        """Initialize the gateway."""
        self._hass = hass
        self._config_entry = config_entry

        self._url = self._config_entry.data.get(CONF_URL)
        self._timeout = self._config_entry.data.get(CONF_TIMEOUT)
        self._username = self._config_entry.data.get(CONF_USERNAME)
        self._password = self._config_entry.data.get(CONF_PASSWORD)
        self._api_key = self._config_entry.data.get(CONF_API_KEY)
        self._verify_certs = self._config_entry.data.get(CONF_VERIFY_SSL, True)
        self._ca_certs = self._config_entry.data.get(CONF_SSL_CA_PATH)

        self.client = None
        self.es_version = None

        self._connection_monitor_ref = None
        self._active_connection_error = False
        self._connection_monitor_active = False

    async def async_init(self):
        """I/O bound init."""

        LOGGER.debug("Creating Elasticsearch client for %s", self._url)
        try:
            self.client = self._create_es_client(
                self._url,
                self._username,
                self._password,
                self._api_key,
                self._verify_certs,
                self._ca_certs,
                self._timeout,
            )

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

        if self._hass and self._config_entry:
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
        self._config_entry.async_create_background_task(
            self._hass, self._connection_monitor_task(), "connection_monitor"
        )
        # self._connection_monitor_ref = asyncio.ensure_future(self._connection_monitor_task())
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
                        LOGGER.info(
                            "Connection to [%s] has been reestablished. Operations will resume."
                        )
            except TransportError as transport_err:
                LOGGER.debug("Finished connection test with TransportError")
                ignorable_error = (
                    isinstance(transport_err.status_code, int)
                    and transport_err.status_code <= 403
                )
                # Do not spam the logs with connection errors if we already know there is a problem.
                if not ignorable_error and not self.active_connection_error:
                    LOGGER.exception(
                        "Connection error. Operations will be paused until connection is reestablished. %s",
                        transport_err,
                    )
                    self._active_connection_error = True
            except Exception as err:
                LOGGER.exception("Error during connection monitoring task %s", err)
            finally:
                if self._connection_monitor_active:
                    await asyncio.sleep(1)

    @classmethod
    async def test_connection(
        self,
        url: str,
        username: str = None,
        password: str = None,
        api_key: str = None,
        verify_certs: bool = True,
        ca_certs: str = None,
        timeout: int = 30,
        verify_permissions=None,
    ):
        """Non-I/O bound init."""

        self._hass = hass
        self._client = self._create_es_client(self._client_args)
        self._client_args = self._create_es_client_args(url, username, password, api_key, verify_certs, ca_certs, timeout)
        self._connection_monitor: ConnectionMonitor = None
        self._minimum_privileges = minimum_privileges

    @abstractmethod
    async def async_init(self):
        """I/O bound init."""

        # Perform the connection
        await self.client.async_init()

        # if we have minimum privileges, enforce them
        if self._minimum_privileges:
            has_all_privileges = await self._has_required_privileges(self._minimum_privileges)

            if not has_all_privileges:
                raise InsufficientPrivileges()

        # Start a new connection monitor
        self._connection_monitor = ConnectionMonitor(self)
        await self._connection_monitor.async_init()

    @property
    def client(self):
        """Return the underlying ES Client."""
        return self._client

    @property
    def authentication_type(self):
        """Return the authentication type."""
        if self.username and self.password:
            return "basic"
        elif self.api_key:
            return "api_key"
        else:
            return "none"

    # Getter for hass
    @property
    def hass(self) -> HomeAssistant:
        """Return the Home Assistant instance."""
        return self._hass

    # Getter for connection_monitor
    @property
    def connection_monitor(self):
        """Return the connection monitor."""
        return self._connection_monitor

    @abstractmethod
    async def stop(self):
        """Stop the ES Gateway."""
        LOGGER.debug("Stopping Elasticsearch Gateway")

        if self.client:
            await self.client.close()
            self.client = None

        LOGGER.debug("Elasticsearch Gateway stopped")

    @classmethod
    async def _test_connection(self, **kwargs):
        """Test the connection to the Elasticsearch server."""

        es_client = self._create_es_client(
            url=url,
            username=username,
            password=password,
            api_key=api_key,
            verify_certs=verify_certs,
            ca_certs=ca_certs,
            timeout=timeout,
        )

        try:
            result = await self._test_connection_with_es_client(
                es_client, verify_permissions
            )
        finally:
            if es_client is not None:
                await es_client.close()

        return result

    @classmethod
    async def _test_connection_with_es_client(
        self,
        es_client,
        verify_permissions=None,
    ):
        """Test the connection to the Elasticsearch server."""
        from elasticsearch7 import TransportError

        try:
            es_client_info = await es_client.info()

            if verify_permissions is not None:
                await self._enforce_privileges(es_client, verify_permissions)

            es_version = ElasticsearchVersion(es_client)
            await es_version.async_init()

            if not es_version.is_supported_version():
                LOGGER.fatal(
                    "UNSUPPORTED VERSION OF ELASTICSEARCH DETECTED: %s.",
                    es_version.to_string(),
                )
                raise UnsupportedVersion()

            return es_client_info
        except InsufficientPrivileges as insuff_err:
            raise insuff_err
        except TransportError as transport_err:
            raise convert_es_error(
                "Connection test failed", transport_err
            ) from transport_err
        except Exception as err:
            raise convert_es_error("Connection test failed", err) from err
        finally:
            if es_client is not None:
                await es_client.close()

    @classmethod
    async def _enforce_privileges(self, es_client, required_privileges):
        """Enforce the required privileges."""
        from elasticsearch7 import TransportError

        try:
            privilege_response = await es_client.security.has_privileges(
                body=required_privileges
            )

            if not privilege_response.get("has_all_requested"):
                LOGGER.debug("Required privileges are missing.")
                raise InsufficientPrivileges()

            return privilege_response
        except TransportError as transport_err:
            raise convert_es_error(
                "Error enforcing privileges", transport_err
            ) from transport_err
        except Exception as err:
            raise convert_es_error("Error enforcing privileges", err) from err

    @classmethod
    def _create_es_client(
        self, url, username, password, api_key, verify_certs, ca_certs, timeout
    ):
        """Construct an instance of the Elasticsearch client."""
        from elasticsearch7._async.client import AsyncElasticsearch

        es_client_args = self._create_es_client_args(
            url, username, password, api_key, verify_certs, ca_certs
        )

        return AsyncElasticsearch(**es_client_args)

    @classmethod
    def _create_es_client_args(
        self,
        url: str,
        username: str = None,
        password: str = None,
        api_key: str = None,
        verify_certs: bool = True,
        ca_certs: str = None,
        timeout: int = 30,
    ):
        """Construct the arguments for the Elasticsearch client."""
        use_basic_auth = username is not None and password is not None
        use_api_key = api_key is not None

        args = {
            "hosts": [url],
            "serializer": get_serializer(),
            "verify_certs": verify_certs,
            "ssl_show_warn": verify_certs,
            "ca_certs": ca_certs,
            "timeout": timeout,
        }

        if use_basic_auth:
            args["http_auth"] = (username, password)

        if use_api_key:
            args["headers"] = {"Authorization": f"ApiKey {api_key}"}

        return args

    @classmethod
    async def _enforce_privileges(self, es_client, required_privileges):
        pass

    async def _get_cluster_info(self, es_client) -> dict:
        """Retrieve info about the connected elasticsearch cluster."""
        try:
            return await es_client.info()

        except Exception as err:
            raise convert_es_error("Connection test failed", err) from err

    def _create_es_client(self, url, username, password, api_key, verify_certs, ca_certs, timeout):
        pass

    def _create_es_client_args(
        self,
        url: str,
        username: str = None,
        password: str = None,
        api_key: str = None,
        verify_certs: bool = True,
        ca_certs: str = None,
        timeout: int = 30,
    ):
        pass


class Elasticsearch8Gateway(ElasticsearchGateway):
    """Encapsulates Elasticsearch operations."""

    client: AsyncElasticsearch8 = None

    @classmethod
    def _create_es_client(self, url, username, password, api_key, verify_certs, ca_certs, timeout):
        """Construct an instance of the Elasticsearch client."""

        es_client_args = self._create_es_client_args(url, username, password, api_key, verify_certs, ca_certs)

        return AsyncElasticsearch8(**es_client_args)

    async def _has_required_privileges(self, required_privileges):
        """Enforce the required privileges."""
        try:
            privilege_response = await self.client.security.has_privileges(body=required_privileges)

            if not privilege_response.get("has_all_requested"):
                LOGGER.debug("Required privileges are missing.")
                raise InsufficientPrivileges()

            return privilege_response
        except Exception as err:
            raise convert_es_error("Error enforcing privileges", err) from err


class Elasticsearch7Gateway(ElasticsearchGateway):
    """Encapsulates Elasticsearch operations."""

    client: AsyncElasticsearch7 = None

    @classmethod
    def _create_es_client(self, url, username, password, api_key, verify_certs, ca_certs, timeout):
        """Construct an instance of the Elasticsearch client."""

        es_client_args = self._create_es_client_args(url, username, password, api_key, verify_certs, ca_certs)

        return AsyncElasticsearch7(**es_client_args)

    async def _has_required_privileges(self, required_privileges):
        """Enforce the required privileges."""

        try:
            privilege_response = await self.client.security.has_privileges(body=required_privileges)

            if not privilege_response.get("has_all_requested"):
                LOGGER.debug("Required privileges are missing.")
                raise InsufficientPrivileges()

            return privilege_response
        except Exception as err:
            raise convert_es_error("Error enforcing privileges", err) from err


class ConnectionMonitor:
    """Connection monitor for Elasticsearch."""

    def __init__(self, gateway):
        """Initialize the connection monitor."""
        self._gateway: ElasticsearchGateway = gateway
        self._previous: bool = False
        self._active: bool = False
        self._task: asyncio.Task = None

    async def async_init(self):
        """Start the connection monitor."""

        # we have already been async_init'd
        if self._task is not None:
            return

        LOGGER.debug("Starting new connection monitor.")

        # Ensure our connection is active
        await self._connection_monitor_task(single_test=True)

        self._task = self.gateway.hass.async_create_background_task(
            self.gateway.hass,
            self._connection_monitor_task(),
            "connection_monitor",
        )

    @property
    def gateway(self):
        """Return the Elasticsearch gateway."""
        return self._gateway

    # Getter for active
    @property
    def active(self):
        """Return the connection monitor status."""
        return self._active

    # Getter for previous
    @property
    def previous(self):
        """Return the previous connection monitor status."""
        return self._previous

    # Getter for task
    @property
    def task(self):
        """Return the asyncio task for the connection monitor."""
        return self._task

    @classmethod
    def _is_ignorable_error(transport_err):
        """Determine if a transport error is ignorable."""

        if isinstance(transport_err, TransportError7 | TransportError8):
            return isinstance(transport_err.status_code, int) and transport_err.status_code <= 403

        return False

    def schedule_next_test(self) -> None:
        """Schedule the next connection test."""
        self._next_test = time.monotonic() + 30

    def should_test(self):
        """Determine if a test should be run."""
        return self._next_test <= time.monotonic()

    async def spin(self) -> None:
        """Spin the event loop."""
        await asyncio.sleep(1)

    async def _connection_monitor_task(self, single_test: bool = False):
        """Perform tasks required for connection monitoring."""

        # Start the connection monitor in 30s
        self.schedule_next_test()

        # Connection monitor event loop
        while True:
            if not self.should_test():
                await self.spin()
                continue

            # This part runs every 30 seconds
            LOGGER.debug("Checking status of the connection to [%s].", self.gateway.url)

            # Backup our current state to _previous and update our active state
            self._previous = self._active

            try:
                self._active = await self.test()
            except err as err:
                LOGGER.exception("Connection test to [%s] failed: %s", self.gateway.url, err)

            self.schedule_next_test()

            if self._active and not self._previous:
                LOGGER.info("Connection to [%s] has been reestablished.", self.gateway.url)
            elif self._active:
                LOGGER.info("Successfully initialized new connection to [%s].", self.gateway.url)
            else:
                LOGGER.error("Connection to [%s] is currently inactive.", self.gateway.url)

            if single_test:
                break

    async def test(self) -> bool:
        """Perform a connection test."""

        return await self._gateway.test()

    async def stop(self) -> None:
        """Stop the connection monitor."""
        LOGGER.warn("Stopping connection monitor.")

        if not self.active:
            LOGGER.debug(
                "Connection monitor did not have an active connection to [%s].",
                self.gateway.url,
            )
            return

        self._active = False

        if self.task is not None:
            self._task.cancel()
            self._task = None

        LOGGER.warn("Connection monitor stopped.")

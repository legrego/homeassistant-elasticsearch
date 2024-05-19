"""Encapsulates Elasticsearch operations."""

import asyncio
import time
from abc import ABC, abstractmethod

from elasticsearch7 import TransportError as TransportError7
from elasticsearch8 import TransportError as TransportError8
from elasticsearch8._async.client import AsyncElasticsearch as AsyncElasticsearch7
from elasticsearch8._async.client import AsyncElasticsearch as AsyncElasticsearch8
from homeassistant.core import HomeAssistant

from .const import ES_CHECK_PERMISSIONS_DATASTREAM
from .errors import (
    InsufficientPrivileges,
    convert_es_error,
)
from .es_serializer import get_serializer
from .logger import LOGGER


class ElasticsearchGateway(ABC):
    """Encapsulates Elasticsearch operations."""

    # Implement all the methods from the Elasticsearch7Gateway class but as abstract methods

    def __init__(
        self,
        hass: HomeAssistant = None,
        url: str = None,
        username: str = None,
        password: str = None,
        api_key: str = None,
        verify_certs: bool = True,
        ca_certs: str = None,
        timeout: int = 30,
        minimum_privileges: dict = None,
    ):
        """Non-I/O bound init."""

        self._hass = hass
        self._url = url
        client_args = self._create_es_client_args(
            url=url, username=username, password=password, api_key=api_key, verify_certs=verify_certs, ca_certs=ca_certs, timeout=timeout
        )
        self._client = self._create_es_client(**client_args)
        self._connection_monitor: ConnectionMonitor = None
        self._minimum_privileges = minimum_privileges

    async def async_init(self):
        """I/O bound init."""

        # Test the connection
        await self.test()

        # if we have minimum privileges, enforce them
        if self._minimum_privileges:
            has_all_privileges = await self._has_required_privileges(self._minimum_privileges)

            if not has_all_privileges:
                raise InsufficientPrivileges()

        # Start a new connection monitor
        self._connection_monitor = ConnectionMonitor(self)
        await self._connection_monitor.async_init()

    @classmethod
    def build_gateway_parameters(self, hass, config_entry):
        """Build the parameters for the Elasticsearch gateway."""
        return {
            "hass": hass,
            "url": config_entry.data.get("url"),
            "username": config_entry.data.get("username"),
            "password": config_entry.data.get("password"),
            "api_key": config_entry.data.get("api_key"),
            "verify_certs": config_entry.data.get("verify_certs"),
            "ca_certs": config_entry.data.get("ca_certs"),
            "timeout": config_entry.data.get("timeout"),
            "minimum_privileges": ES_CHECK_PERMISSIONS_DATASTREAM,
        }

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

    async def stop(self):
        """Stop the ES Gateway."""
        LOGGER.debug("Stopping Elasticsearch Gateway")

        if self.client:
            await self.client.close()
            self.client = None

        LOGGER.debug("Elasticsearch Gateway stopped")

    # @classmethod
    # async def _test_connection(self):
    #     """Test the connection to the Elasticsearch server."""

    #     try:
    #         # Create an Elasticsearch client
    #         es_client = await self._create_es_client(**kwargs)
    #         await self._get_cluster_info(es_client)

    #         LOGGER.debug("Connection test to [%s] was successful.", url)

    #         return True

    #     except Exception as err:
    #         LOGGER.debug("Connection test to [%s] failed: %s", url, err)

    #     return False

    async def test(self):
        """Test the connection to the Elasticsearch server."""

        LOGGER.debug("Testing the connection for [%s].", self._url)

        if not await self._client.ping():
            LOGGER.debug("Connection test to [%s] failed.", self._url)
            return False

        LOGGER.debug("Connection test to [%s] was successful.", self._url)
        return True

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

    @abstractmethod
    async def _has_required_privileges(self, required_privileges):
        pass

    async def _get_cluster_info(self, es_client) -> dict:
        """Retrieve info about the connected elasticsearch cluster."""
        try:
            return await es_client.info()

        except Exception as err:
            raise convert_es_error("Connection test failed", err) from err

    @abstractmethod
    def _create_es_client(self, hosts, username, password, api_key, verify_certs, ca_certs, timeout):
        pass


class Elasticsearch8Gateway(ElasticsearchGateway):
    """Encapsulates Elasticsearch operations."""

    client: AsyncElasticsearch8

    @classmethod
    def _create_es_client(self, **kwargs):
        """Construct an instance of the Elasticsearch client."""

        return AsyncElasticsearch8(**kwargs)

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

    client: AsyncElasticsearch7

    @classmethod
    def _create_es_client(self, **kwargs):
        return AsyncElasticsearch7(**kwargs)

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

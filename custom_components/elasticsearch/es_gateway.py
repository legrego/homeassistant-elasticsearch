"""Encapsulates Elasticsearch operations."""

import asyncio
import sys
import time
from abc import ABC, abstractmethod
from logging import Logger
from typing import Any, NoReturn

from elasticsearch7 import TransportError as TransportError7
from elasticsearch7._async.client import AsyncElasticsearch as AsyncElasticsearch7
from elasticsearch7.helpers import async_streaming_bulk as async_streaming_bulk7
from elasticsearch7.serializer import JSONSerializer as JSONSerializer7
from elasticsearch8 import TransportError as TransportError8
from elasticsearch8._async.client import AsyncElasticsearch as AsyncElasticsearch8
from elasticsearch8.helpers import async_streaming_bulk as async_streaming_bulk8
from elasticsearch8.serializer import JSONSerializer as JSONSerializer8
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.elasticsearch.const import (
    CAPABILITIES,
    ES_CHECK_PERMISSIONS_DATASTREAM,
)
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    CannotConnect,
    ClientError,
    ESIntegrationException,
    InsufficientPrivileges,
    UnsupportedVersion,
    UntrustedCertificate,
)

from .logger import LOGGER as BASE_LOGGER


class ElasticsearchGateway(ABC):
    """Encapsulates Elasticsearch operations."""

    _logger = BASE_LOGGER

    def __init__(
        self,
        hass: HomeAssistant,
        url: str,
        username: str | None = None,
        password: str | None = None,
        api_key: str | None = None,
        verify_certs: bool = True,
        ca_certs: str | None = None,
        request_timeout: int = 30,
        minimum_privileges: dict | None = None,
        use_connection_monitor: bool = True,
        log: Logger = BASE_LOGGER,
    ) -> None:
        """Non-I/O bound init."""

        self._logger: Logger = log
        self._hass: HomeAssistant = hass
        self._url: str = url
        self._client_args = self._create_es_client_args(
            url=url,
            username=username,
            password=password,
            api_key=api_key,
            verify_certs=verify_certs,
            ca_certs=ca_certs,
            request_timeout=request_timeout,
        )
        self._client: AsyncElasticsearch7 | AsyncElasticsearch8 = self._create_es_client(**self._client_args)
        self._connection_monitor: ConnectionMonitor = ConnectionMonitor(gateway=self, log=self._logger)
        self._minimum_privileges: dict | None = minimum_privileges
        self._info: dict[str, Any] = {}
        self._capabilities: dict = {}
        self._use_connection_monitor: bool = use_connection_monitor

    async def async_init(self) -> None:
        """I/O bound init."""

        # if not await self.test():
        #     msg = "Connection test failed."  # noqa: ERA001
        #     raise convert_es_error(msg, ConnectionError)  # noqa: ERA001

        # Test the connection
        self._info = await self._get_cluster_info()

        if not await self.test():
            msg = "Connection test failed."
            raise ConnectionError(msg)

        # Obtain the capabilities of the Elasticsearch instance
        self._capabilities = self._build_capabilities()

        # Enforce minimum version
        if self.has_capability(CAPABILITIES.SUPPORTED) is False:
            raise UnsupportedVersion

        # if we have minimum privileges, enforce them
        if self._minimum_privileges is not None:
            has_all_privileges = await self._has_required_privileges(self._minimum_privileges)

            if not has_all_privileges:
                raise InsufficientPrivileges

        if self._use_connection_monitor:
            # Start the connection monitor
            await self._connection_monitor.async_init()

    def _build_capabilities(self) -> dict[str, int | bool | str]:
        def meets_minimum_version(version_info: dict, major: int, minor: int) -> bool:
            """Determine if this version of ES meets the minimum version requirements."""
            return version_info[CAPABILITIES.MAJOR] > major or (
                version_info[CAPABILITIES.MAJOR] == major and version_info[CAPABILITIES.MINOR] >= minor
            )

        if self._info is None:
            msg = "Cluster info is not available."
            raise ValueError(msg)

        version_info = {
            CAPABILITIES.MAJOR: int(self._info["version"]["number"].split(".")[0]),
            CAPABILITIES.MINOR: int(self._info["version"]["number"].split(".")[1]),
            CAPABILITIES.BUILD_FLAVOR: self._info["version"].get("build_flavor", None),
            # CAPABILITIES.OSS: self._info["version"]["build_flavor"] == "oss",
        }

        capabilities = {
            CAPABILITIES.SERVERLESS: version_info[CAPABILITIES.BUILD_FLAVOR] == "serverless",
            CAPABILITIES.SUPPORTED: meets_minimum_version(version_info, major=7, minor=11),
            CAPABILITIES.TIMESERIES_DATASTREAM: meets_minimum_version(version_info, major=8, minor=7),
            CAPABILITIES.IGNORE_MISSING_COMPONENT_TEMPLATES: meets_minimum_version(
                version_info,
                major=8,
                minor=7,
            ),
            CAPABILITIES.DATASTREAM_LIFECYCLE_MANAGEMENT: meets_minimum_version(
                version_info,
                major=8,
                minor=11,
            ),
            CAPABILITIES.MAX_PRIMARY_SHARD_SIZE: meets_minimum_version(version_info, major=7, minor=13),
        }

        return {**version_info, **capabilities}

    @classmethod
    def build_gateway_parameters(
        cls,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        minimum_privileges: dict = ES_CHECK_PERMISSIONS_DATASTREAM,
    ) -> dict:
        """Build the parameters for the Elasticsearch gateway."""
        return {
            "hass": hass,
            "url": config_entry.data.get("url"),
            "username": config_entry.data.get("username"),
            "password": config_entry.data.get("password"),
            "api_key": config_entry.data.get("api_key"),
            "verify_certs": config_entry.data.get("verify_certs"),
            "ca_certs": config_entry.data.get("ca_certs"),
            "request_timeout": config_entry.data.get("timeout"),
            "minimum_privileges": minimum_privileges,
        }

    @property
    def capabilities(self) -> dict:
        """Return the underlying ES Capabilities."""
        return self._capabilities

    def has_capability(self, capability: str) -> bool:
        """Determine if the Elasticsearch instance has the specified capability."""
        return self.capabilities.get(capability, False)

    @property
    def active(self) -> bool:
        """Return the state of the connection_monitor."""
        return self._connection_monitor.active

    @property
    def client(self) -> AsyncElasticsearch7 | AsyncElasticsearch8:
        """Return the underlying ES Client."""
        return self._client

    @property
    def authentication_type(self) -> str:
        """Return the authentication type."""

        if self._client_args.get("http_auth", None) is not None:
            return "basic"
        elif self._client_args.get("headers", None) is not None:
            return "api_key"
        else:
            return "none"

    # Getter for hass
    @property
    def hass(self) -> HomeAssistant:
        """Return the Home Assistant instance."""
        return self._hass

    # Getter for url
    @property
    def url(self) -> str:
        """Return the Home Assistant instance."""
        return self._url

    # Getter for connection_monitor
    @property
    def connection_monitor(self) -> "ConnectionMonitor":
        """Return the connection monitor."""
        return self._connection_monitor

    async def stop(self) -> None:
        """Stop the ES Gateway."""
        self._logger.warning("Stopping Elasticsearch Gateway")

        if self.client:
            await self.client.close()

        self._logger.warning("Stopped Elasticsearch Gateway")

    async def test(self) -> bool:
        """Test the connection to the Elasticsearch server."""
        try:
            await self._get_cluster_info()
        except Exception:
            return False
        else:
            return True

    @classmethod
    def _create_es_client_args(
        cls,
        url: str,
        username: str | None = None,
        password: str | None = None,
        api_key: str | None = None,
        verify_certs: bool = True,
        ca_certs: str | None = None,
        request_timeout: int = 30,
    ) -> dict:
        """Construct the arguments for the Elasticsearch client."""
        use_basic_auth = username is not None and password is not None
        use_api_key = api_key is not None

        args = {
            "hosts": [url],
            "serializer": cls.new_encoder(),
            "verify_certs": verify_certs,
            "ssl_show_warn": verify_certs,
            "ca_certs": ca_certs,
            "request_timeout": request_timeout,
        }

        if use_basic_auth:
            args["http_auth"] = (username, password)

        if use_api_key:
            args["headers"] = {"Authorization": f"ApiKey {api_key}"}

        return args

    async def _get_cluster_info(self) -> dict:
        """Retrieve info about the connected elasticsearch cluster."""
        try:
            info = await self._client.info()
        except Exception:
            self.convert_es_error()

        if not isinstance(info, dict):
            msg = "Invalid response from Elasticsearch"
            self.convert_es_error(msg)

        return dict(info)

    @abstractmethod
    async def bulk(self, **kwargs) -> None:
        """Perform a bulk operation."""

    def _convert_api_response_to_dict(self, response: object) -> dict:
        """Convert an API response to a dictionary."""
        if not isinstance(response, dict):
            msg = "Invalid response from Elasticsearch"
            raise TypeError(msg)

        return dict(response)

    async def get_index_template(self, **kwargs) -> dict:
        """Retrieve an index template."""
        self._logger.debug("Retrieving index template %s", kwargs.get("name", ""))

        try:
            result = await self._client.indices.get_template(**kwargs)

        except Exception:
            msg = "Error retrieving index template"
            self.convert_es_error(msg)

        if not isinstance(result, dict):
            self._logger.error("Invalid response from Elasticsearch")

        return self._convert_api_response_to_dict(result)

    async def put_index_template(self, **kwargs) -> dict:
        """Retrieve an index template."""
        self._logger.debug("Updating index template %s", kwargs.get("name", ""))

        try:
            result = await self._client.indices.put_index_template(**kwargs)

        except Exception:
            msg = "Error creating/updating index template"
            self.convert_es_error(msg)

        if not isinstance(result, dict):
            self._logger.error("Invalid response from Elasticsearch")

        return self._convert_api_response_to_dict(result)

    @abstractmethod
    async def _has_required_privileges(self, required_privileges: dict) -> bool:
        pass  # pragma: no cover

    @classmethod
    @abstractmethod
    def new_encoder(cls) -> JSONSerializer7 | JSONSerializer8:
        """Create a new instance of the JSON serializer."""
        # pragma: no cover

    @classmethod
    @abstractmethod
    def _create_es_client(
        cls,
        hosts: str,
        username: str | None = None,
        password: str | None = None,
        api_key: str | None = None,
        verify_certs: bool = True,
        ca_certs: str | None = None,
        request_timeout: int = 30,
    ) -> AsyncElasticsearch7 | AsyncElasticsearch8:
        pass  # pragma: no cover

    @classmethod
    @abstractmethod
    def convert_es_error(
        cls,
        msg: str | None = None,
        err: Exception | None = None,
    ) -> NoReturn:  # type: ignore  # noqa: PGH003
        """Convert an internal error from the elasticsearch package into one of our own."""
        # pragma: no cover


class Elasticsearch8Gateway(ElasticsearchGateway):
    """Encapsulates Elasticsearch operations."""

    client: AsyncElasticsearch8

    @classmethod
    def _create_es_client(cls, **kwargs) -> AsyncElasticsearch8:
        """Construct an instance of the Elasticsearch client."""

        return AsyncElasticsearch8(**kwargs)

    async def _has_required_privileges(self, required_privileges: dict) -> bool:
        """Enforce the required privileges."""
        try:
            privilege_response = await self.client.security.has_privileges(index=required_privileges)
        except Exception:
            msg = "Error enforcing privileges"
            self.convert_es_error(msg)

        if not privilege_response.get("has_all_requested"):
            self._logger.error("Required privileges are missing.")
            raise InsufficientPrivileges

        return True

    @classmethod
    def new_encoder(cls) -> JSONSerializer8:
        """Create a new instance of the JSON serializer."""

        class SetEncoder(JSONSerializer8):
            """JSONSerializer which serializes sets to lists."""

            def default(self, data: any) -> any:  # type: ignore # noqa: PGH003
                """JSONSerializer which serializes sets to lists."""
                if isinstance(data, set):
                    output = list(data)
                    output.sort()
                    return output

                return JSONSerializer8.default(self, data)

        return SetEncoder()

    async def bulk(self, actions) -> None:
        """Perform a bulk operation."""

        self._logger.debug("Performing bulk operation")
        async for ok, result in async_streaming_bulk8(
            client=self.client,
            actions=actions,
            yield_ok=False,
        ):
            action, outcome = result.popitem()
            if not ok:
                self._logger.error("failed to %s document %s", action, outcome)

    @classmethod
    def convert_es_error(
        cls,
        msg: str | None = None,
        err: Exception | None = None,
    ) -> NoReturn:
        """Convert an internal error from the elasticsearch package into one of our own."""
        from aiohttp import client_exceptions
        from elasticsearch8 import (
            AuthenticationException,
            AuthorizationException,
            SSLError,
        )
        from elasticsearch8 import (
            ConnectionError as ESConnectionError,
        )

        if err is None:
            t, v, tb = sys.exc_info()
        else:
            t, v = type(err), err

        new_err: Exception = ESIntegrationException(msg)

        if t is SSLError:
            new_err = UntrustedCertificate(msg, err)

        elif t is ESConnectionError:
            if isinstance(v.info, client_exceptions.ClientConnectorCertificateError):  # type: ignore  # noqa: PGH003
                new_err = UntrustedCertificate(msg, err)
            elif isinstance(v.info, client_exceptions.ClientConnectorError):  # type: ignore  # noqa: PGH003
                new_err = ClientError(msg, err)
            else:
                new_err = CannotConnect(msg, err)

        elif t is AuthenticationException:
            new_err = AuthenticationRequired(msg, err)

        elif t is AuthorizationException:
            new_err = InsufficientPrivileges(msg, err)

        new_err.__cause__ = v
        raise new_err


class Elasticsearch7Gateway(ElasticsearchGateway):
    """Encapsulates Elasticsearch operations."""

    client: AsyncElasticsearch7

    @classmethod
    def _create_es_client(cls, **kwargs) -> AsyncElasticsearch7:
        return AsyncElasticsearch7(**kwargs)

    async def _has_required_privileges(self, required_privileges: dict) -> bool:
        """Enforce the required privileges."""

        try:
            privilege_response = await self.client.security.has_privileges(body=required_privileges)
        except Exception:
            msg = "Error enforcing privileges"
            self.convert_es_error(msg)

        if not privilege_response.get("has_all_requested"):
            self._logger.error("Required privileges are missing.")
            raise InsufficientPrivileges

        return True

    @classmethod
    def new_encoder(cls) -> JSONSerializer7:
        """Create a new instance of the JSON serializer."""

        class SetEncoder(JSONSerializer7):
            """JSONSerializer which serializes sets to lists."""

            def default(self, data: any) -> any:  # type: ignore  # noqa: PGH003
                """Entry point."""
                if isinstance(data, set):
                    output = list(data)
                    output.sort()
                    return output

                return JSONSerializer7.default(self, data)

        return SetEncoder()

    async def bulk(self, actions) -> None:
        """Perform a bulk operation."""

        self._logger.debug("Performing bulk operation")
        async for ok, result in async_streaming_bulk7(
            client=self.client,
            actions=actions,
            yield_ok=False,
        ):
            action, outcome = result.popitem()
            if not ok:
                self._logger.error("failed to %s document %s", action, outcome)

    @classmethod
    def convert_es_error(
        cls,
        msg: str | None = None,
        err: Exception | None = None,
    ) -> NoReturn:
        """Convert an internal error from the elasticsearch package into one of our own."""
        from aiohttp import client_exceptions
        from elasticsearch7 import (
            AuthenticationException,
            AuthorizationException,
            ElasticsearchException,
            SSLError,
        )
        from elasticsearch7 import (
            ConnectionError as ESConnectionError,
        )

        if err is None:
            t, v, tb = sys.exc_info()
        else:
            t, v = type(err), err

        new_err: Exception = ESIntegrationException(msg)

        if t is SSLError:
            new_err = UntrustedCertificate(msg, err)

        elif t is ESConnectionError:
            if isinstance(v.info, client_exceptions.ClientConnectorCertificateError):  # type: ignore  # noqa: PGH003
                new_err = UntrustedCertificate(msg, err)
            elif isinstance(v.info, client_exceptions.ClientConnectorError):  # type: ignore  # noqa: PGH003
                new_err = ClientError(msg, err)
            else:
                new_err = CannotConnect(msg, err)

        elif t is AuthenticationException:
            new_err = AuthenticationRequired(msg, err)

        elif t is AuthorizationException:
            new_err = InsufficientPrivileges(msg, err)

        elif t is ElasticsearchException:
            new_err = ESIntegrationException(msg, err)

        new_err.__cause__ = v
        raise new_err


class ConnectionMonitor:
    """Connection monitor for Elasticsearch."""

    def __init__(self, gateway: ElasticsearchGateway, log: Logger = BASE_LOGGER) -> None:
        """Initialize the connection monitor."""
        self._logger = log

        self._gateway: ElasticsearchGateway = gateway
        self._previous: bool = False
        self._active: bool = False
        self._task: asyncio.Task | None = None
        self._next_test: float | None = 0

    async def async_init(self) -> None:
        """Start the connection monitor."""

        # Ensure our connection is active
        await self._connection_monitor_task(single_test=True)

    @property
    def gateway(self) -> ElasticsearchGateway:
        """Return the Elasticsearch gateway."""
        return self._gateway

    @property
    def active(self) -> bool:
        """Return the connection monitor status."""
        return self._active

    @property
    def previous(self) -> bool:
        """Return the previous connection monitor status."""
        return self._previous

    @classmethod
    def _is_ignorable_error(cls, err) -> bool:
        """Determine if a transport error is ignorable."""

        if isinstance(err, TransportError7 | TransportError8):
            return isinstance(err.status_code, int) and cls.status_code <= 403  # type: ignore # noqa: PLR2004, PGH003

        return False

    def schedule_next_test(self) -> None:
        """Schedule the next connection test."""
        self._next_test = time.monotonic() + 30

    def should_test(self) -> bool:
        """Determine if a test should be run."""
        return self._next_test is None or self._next_test <= time.monotonic()

    async def spin(self) -> None:
        """Spin the event loop."""
        await asyncio.sleep(1)

    async def _connection_monitor_task(self, single_test: bool = False) -> None:
        """Perform tasks required for connection monitoring."""

        # Connection monitor event loop
        while True:
            if not self.should_test():
                await self.spin()
                continue

            self.schedule_next_test()

            # This part runs every 30 seconds
            self._logger.debug("Checking status of the connection to [%s].", self.gateway.url)

            # Backup our current state to _previous and update our active state
            self._previous = self._active

            try:
                self._active = await self.test()
            except Exception as err:  # type: ignore  # noqa: PGH003
                if not self._is_ignorable_error(err):
                    self._logger.exception("Connection test to [%s] failed", self.gateway.url)
                    self._active = False

            self.schedule_next_test()

            if self._active and self._previous is None:
                self._logger.info("Connection to [%s] has been established.", self.gateway.url)
            if self._active and not self._previous:
                self._logger.info("Connection to [%s] has been reestablished.", self.gateway.url)
            elif self._active:
                self._logger.debug("Connection test to [%s] was successful.", self.gateway.url)
            else:
                self._logger.error("Connection to [%s] is currently inactive.", self.gateway.url)

            if single_test:
                break

    async def test(self) -> bool:
        """Perform a connection test."""

        return await self._gateway.test()

    def start(self, config_entry: ConfigEntry) -> None:
        """Start the connection monitor."""
        if not self._gateway._use_connection_monitor:  # noqa: SLF001
            return

        self._logger.info("Starting new connection monitor.")
        config_entry.async_create_background_task(
            self.gateway.hass,
            self._connection_monitor_task(),
            "connection_monitor",
        )

    def stop(self) -> None:
        """Stop the connection monitor."""
        self._logger.warning("Stopping connection monitor.")

        if not self._active:
            self._logger.debug(
                "Connection monitor did not have an active connection to [%s].",
                self.gateway.url,
            )
            return

        self._active = False

        self._logger.warning("Connection monitor stopped.")

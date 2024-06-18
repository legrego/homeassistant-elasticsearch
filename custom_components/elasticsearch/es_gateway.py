"""Encapsulates Elasticsearch operations."""

from __future__ import annotations

import asyncio  # pragma: no cover
import sys
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, NoReturn

from elasticsearch7 import AuthenticationException as AuthenticationException7
from elasticsearch7 import TransportError as TransportError7
from elasticsearch7._async.client import AsyncElasticsearch as AsyncElasticsearch7
from elasticsearch7.helpers import async_streaming_bulk as async_streaming_bulk7
from elasticsearch7.serializer import JSONSerializer as JSONSerializer7
from elasticsearch8 import AuthenticationException as AuthenticationException8
from elasticsearch8 import TransportError as TransportError8
from elasticsearch8._async.client import AsyncElasticsearch as AsyncElasticsearch8
from elasticsearch8.helpers import async_streaming_bulk as async_streaming_bulk8
from elasticsearch8.serializer import JSONSerializer as JSONSerializer8
from homeassistant.util.logging import async_create_catching_coro

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
from custom_components.elasticsearch.loop import LoopHandler

from .logger import LOGGER as BASE_LOGGER
from .logger import async_log_enter_exit_debug, log_enter_exit_debug

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from logging import Logger

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


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
        minimum_privileges: dict[str, Any] | None = None,
        use_connection_monitor: bool = True,
        log: Logger = BASE_LOGGER,
    ) -> None:
        """Non-I/O bound init."""

        self._logger: Logger = log
        self._hass: HomeAssistant = hass
        self._url: str = url

        self._minimum_privileges: dict[str, Any] | None = minimum_privileges
        self._info: dict[str, Any] = {}
        self._capabilities: dict = {}

        self._cancel_connection_monitor: asyncio.Task | None = None
        self._use_connection_monitor: bool = use_connection_monitor

        self._first_check: bool = True
        self._previous: bool = False
        self._active: bool = False

        self._initialized: bool = False

    @log_enter_exit_debug
    async def async_init(self, config_entry: ConfigEntry | None = None) -> None:
        """I/O bound init."""

        if config_entry is None and self._use_connection_monitor:
            msg = "config_entry is required to start the connection monitor."
            raise ValueError(msg)

        # Test the connection
        self._info = await self._get_cluster_info()

        if not await self.test_connection():
            msg = "Connection test failed."
            raise ConnectionError(msg)

        # Obtain the capabilities of the Elasticsearch instance
        self._capabilities = self._build_capabilities()

        # Enforce minimum version
        if self.has_capability(CAPABILITIES.SUPPORTED) is False:
            msg = "Unsupported version of Elasticsearch"
            raise UnsupportedVersion(msg)

        # if we have minimum privileges, enforce them
        if self._minimum_privileges is not None:
            has_all_privileges = await self._has_required_privileges(self._minimum_privileges)

            if not has_all_privileges:
                raise InsufficientPrivileges

        if config_entry is not None and self._use_connection_monitor:
            connection_loop = LoopHandler(
                name="es_update_connection_status_loop",
                func=self.update_connection_status,
                frequency=300,
                log=self._logger,
            )

            self._cancel_connection_monitor = config_entry.async_create_background_task(
                self._hass,
                async_create_catching_coro(connection_loop.start()),
                "es_gateway_monitor_task",
            )

        self._initialized = True

    @property
    def url(self) -> str:
        """Return the Home Assistant instance."""
        return self._url

    @property
    def capabilities(self) -> dict:
        """Return the underlying ES Capabilities."""
        if self._capabilities == {}:
            msg = "Capabilities have not been initialized, call async_init first."
            raise ValueError(msg)

        return self._capabilities

    @property
    def active(self) -> bool:
        """Return the state of the connection_monitor."""
        return self._active

    @property
    @abstractmethod
    def client(self) -> AsyncElasticsearch7 | AsyncElasticsearch8:
        """Return the underlying ES Client."""

    def has_capability(self, capability: str) -> bool:
        """Determine if the Elasticsearch instance has the specified capability."""
        return self.capabilities.get(capability, False)

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
    async def test_prospective_settings(
        cls,
        hass: HomeAssistant,
        url: str,
        username: str | None = None,
        password: str | None = None,
        api_key: str | None = None,
        verify_certs: bool = True,
        ca_certs: str | None = None,
        request_timeout: int = 30,
        minimum_privileges: dict[str, Any] = ES_CHECK_PERMISSIONS_DATASTREAM,
        logger: Logger = BASE_LOGGER,
    ) -> bool:
        """Test the settings provided by the user and make sure they work."""
        gateway: ElasticsearchGateway | None = None

        try:
            gateway = cls(
                hass=hass,
                url=url,
                username=username,
                password=password,
                api_key=api_key,
                verify_certs=verify_certs,
                ca_certs=ca_certs,
                request_timeout=request_timeout,
                minimum_privileges=minimum_privileges,
                use_connection_monitor=False,
            )

            await gateway.async_init()
        except ESIntegrationException:
            raise
        except Exception:
            logger.exception("Unknown error testing settings.")
            cls.convert_es_error()
        finally:
            if gateway is not None:
                await gateway.stop()

        return True

    @log_enter_exit_debug
    @abstractmethod
    async def stop(self) -> None:
        """Stop the ES Gateway."""
        self._logger.warning("Stopping Elasticsearch Gateway")

        if self._cancel_connection_monitor is not None:
            self._cancel_connection_monitor.cancel()

        self._logger.warning("Stopped Elasticsearch Gateway")

    async def update_connection_status(self) -> None:
        """Test the connection to the Elasticsearch server."""

        self._logger.debug("Checking status of the connection to [%s].", self.url)

        # Backup our current state to _previous and update our active state
        self._previous = self._active

        try:
            self._active = await self.test_connection()
        except TransportError7 as err:
            if isinstance(err.status_code, int) and err.status_code <= 403:  # noqa: PLR2004
                self._logger.exception(
                    "Ingorable error during connection test to [%s]",
                    self._url,
                    exc_info=err,
                )
                self._active = True
            else:
                self._logger.exception(
                    "Uningorable error during connection test to [%s]",
                    self._url,
                    exc_info=err,
                )
                self._active = False
        except TransportError8 as err:
            msg = "Elasticsearch 8 is not yet supported."
            raise NotImplementedError(msg) from err
        except Exception:  # type: ignore  # noqa: PGH003
            self._logger.exception("Connection test to [%s] failed", self._url)
            self._active = False

        if self._active and self._previous is None:
            self._logger.info("Connection to [%s] has been established.", self.url)
        if self._active and not self._previous and not self._first_check:
            self._logger.info("Connection to [%s] has been reestablished.", self.url)
        elif self._active:
            self._logger.debug("Connection test to [%s] was successful.", self.url)
        else:
            self._logger.error("Connection to [%s] is currently inactive.", self.url)

        if self._first_check:
            self._first_check = False

    async def test_connection(self) -> bool:
        """Test the connection to the Elasticsearch server."""
        try:
            await self._get_cluster_info()
        except ESIntegrationException:
            return False
        else:
            return True

    async def _get_cluster_info(self) -> dict:
        """Retrieve info about the connected elasticsearch cluster."""
        try:
            info = await self.client.info()
        except (TransportError7, TransportError8):
            self.convert_es_error("Error connecting to Elasticsearch")
        except (AuthenticationException7, AuthenticationException8):
            self.convert_es_error("Authentication error connecting to Elasticsearch")
        except Exception:
            self._logger.exception("Unknown error retrieving cluster info")
            raise
        if not isinstance(info, dict):
            msg = "Invalid response from Elasticsearch"
            self.convert_es_error(msg)

        return dict(info)

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
            result = await self.client.indices.get_index_template(**kwargs)

        except ConnectionError:
            msg = "Error retrieving index template"
            self.convert_es_error(msg)

        except Exception:
            self._logger.exception("Unknown error retrieving index templates")
            raise

        if not isinstance(result, dict):
            self._logger.error("Invalid response from Elasticsearch while retrieving index templates")

        return self._convert_api_response_to_dict(result)

    async def put_index_template(self, **kwargs) -> dict:
        """Retrieve an index template."""
        self._logger.debug("Updating index template %s", kwargs.get("name", ""))

        try:
            result = await self.client.indices.put_index_template(**kwargs)

        except ConnectionError:
            msg = "Error creating/updating index template"
            self.convert_es_error(msg)
        except Exception:
            self._logger.exception("Unknown error creating/updating index template")
            raise

        if not isinstance(result, dict):
            self._logger.error("Invalid response from Elasticsearch while creating/updating index template")

        return self._convert_api_response_to_dict(result)

    # Abstract Methods

    @abstractmethod
    async def bulk(self, actions: AsyncGenerator[dict[str, Any], Any]) -> None:
        """Perform a bulk operation."""

    @abstractmethod
    async def _has_required_privileges(self, required_privileges: dict[str, Any]) -> bool:
        pass  # pragma: no cover

    @classmethod
    @abstractmethod
    def new_encoder(cls) -> JSONSerializer7 | JSONSerializer8:
        """Create a new instance of the JSON serializer."""
        # pragma: no cover

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
        minimum_privileges: dict[str, Any] | None = None,
        use_connection_monitor: bool = True,
        log: Logger = BASE_LOGGER,
    ):
        """Initialize the Elasticsearch Gateway."""
        super().__init__(
            hass=hass,
            url=url,
            username=username,
            password=password,
            api_key=api_key,
            verify_certs=verify_certs,
            ca_certs=ca_certs,
            request_timeout=request_timeout,
            minimum_privileges=minimum_privileges,
            use_connection_monitor=use_connection_monitor,
            log=log,
        )

        client_args = self._create_es_client_args(
            url=url,
            username=username,
            password=password,
            api_key=api_key,
            verify_certs=verify_certs,
            ca_certs=ca_certs,
            request_timeout=request_timeout,
        )
        self._client: AsyncElasticsearch8 = AsyncElasticsearch8(**client_args)

    @property
    def client(self) -> AsyncElasticsearch8:
        """Return the underlying ES Client."""
        return self._client

    async def _has_required_privileges(self, required_privileges: dict[str, Any]) -> bool:
        """Enforce the required privileges."""
        try:
            privilege_response = await self.client.security.has_privileges(**required_privileges)
        except ConnectionError:
            msg = "Error enforcing privileges"
            self.convert_es_error(msg)

        except Exception:
            self._logger.exception("Unknown error enforcing privileges")
            raise

        if not privilege_response.get("has_all_requested"):
            self._logger.error("Required privileges are missing.")
            raise InsufficientPrivileges

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
            args["basic_auth"] = (username, password)

        if use_api_key:
            args["api_key"] = api_key

        return args

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

    async def bulk(self, actions: AsyncGenerator[dict[str, Any], Any]) -> None:
        """Perform a bulk operation."""

        count = 0
        self._logger.debug("Performing bulk operation")

        async for ok, result in async_streaming_bulk8(
            client=self.client,
            actions=actions,
            yield_ok=False,
        ):
            count += 1
            action, outcome = result.popitem()
            if not ok:
                self._logger.error("failed to %s document %s", action, outcome)

        self._logger.debug("Bulk operation completed. %s documents processed.", count)

    @classmethod
    def convert_es_error(
        cls,
        msg: str | None = None,
        err: Exception | None = None,
    ) -> NoReturn:
        """Convert an internal error from the elasticsearch package into one of our own."""
        from aiohttp import client_exceptions
        from elasticsearch8 import (
            ApiError,
            AuthenticationException,
            AuthorizationException,
            TransportError,
        )

        if err is None:
            _, v, _ = sys.exc_info()
        else:
            v = err

        new_err: Exception = ESIntegrationException(msg)

        if isinstance(v, AuthenticationException):
            new_err = AuthenticationRequired(msg)

        elif isinstance(v, AuthorizationException):
            new_err = InsufficientPrivileges(msg)

        elif isinstance(v, TransportError):
            if isinstance(v.info, client_exceptions.ClientConnectorCertificateError):  # type: ignore  # noqa: PGH003
                new_err = UntrustedCertificate(msg)
            elif isinstance(v.info, client_exceptions.ClientConnectorError):  # type: ignore  # noqa: PGH003
                new_err = ClientError(msg)
            else:
                new_err = CannotConnect(msg)

        elif isinstance(v, ApiError):
            new_err = ESIntegrationException(msg)

        raise new_err from v


class Elasticsearch7Gateway(ElasticsearchGateway):
    """Encapsulates Elasticsearch operations."""

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
        minimum_privileges: dict[str, Any] | None = None,
        use_connection_monitor: bool = True,
        log: Logger = BASE_LOGGER,
    ) -> None:
        """Initialize the Elasticsearch Gateway."""
        super().__init__(
            hass=hass,
            url=url,
            username=username,
            password=password,
            api_key=api_key,
            verify_certs=verify_certs,
            ca_certs=ca_certs,
            request_timeout=request_timeout,
            minimum_privileges=minimum_privileges,
            use_connection_monitor=use_connection_monitor,
            log=log,
        )

        client_args = self._create_es_client_args(
            url=url,
            username=username,
            password=password,
            api_key=api_key,
            verify_certs=verify_certs,
            ca_certs=ca_certs,
            request_timeout=request_timeout,
        )

        self._client: AsyncElasticsearch7 = AsyncElasticsearch7(**client_args)

    @property
    def client(self) -> AsyncElasticsearch7:
        """Return the underlying ES Client."""
        return self._client

    async def _has_required_privileges(self, required_privileges: dict[str, Any]) -> bool:
        """Enforce the required privileges."""

        try:
            privilege_response = await self.client.security.has_privileges(body=required_privileges)
        except ConnectionError:
            msg = "Error enforcing privileges"
            self.convert_es_error(msg)
        except Exception:
            self._logger.exception("Unknown error enforcing privileges")
            raise

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

    @async_log_enter_exit_debug
    async def bulk(self, actions: AsyncGenerator[dict[str, Any], Any]) -> None:
        """Perform a bulk operation."""

        count = 0
        async for ok, result in async_streaming_bulk7(
            client=self.client,
            actions=actions,
            yield_ok=True,
        ):
            count += 1
            action, outcome = result.popitem()
            if not ok:
                self._logger.error("failed to %s document %s", action, outcome)

        if count > 0:
            self._logger.info("Created %s new documents in Elasticsearch.", count)
        else:
            self._logger.debug("Publish skipped, no new events to publish.")

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
            TransportError,
        )

        if err is None:
            _, v, _ = sys.exc_info()
        else:
            v = err

        new_err: Exception = ESIntegrationException(msg)

        if isinstance(v, AuthenticationException):
            new_err = AuthenticationRequired(msg)

        elif isinstance(v, AuthorizationException):
            new_err = InsufficientPrivileges(msg)

        elif isinstance(v, TransportError):
            if isinstance(v.info, client_exceptions.ClientConnectorCertificateError):  # type: ignore  # noqa: PGH003
                new_err = UntrustedCertificate(msg)
            elif isinstance(v.info, client_exceptions.ClientConnectorError):  # type: ignore  # noqa: PGH003
                new_err = ClientError(msg)
            else:
                new_err = CannotConnect(msg)

        elif isinstance(v, ElasticsearchException):
            new_err = ESIntegrationException(msg)

        raise new_err from v

    async def stop(self) -> None:
        """Stop the ES Gateway."""
        await self._client.close()
        await super().stop()

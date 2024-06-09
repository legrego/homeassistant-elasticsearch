"""Encapsulates Elasticsearch operations."""

import sys
from abc import ABC, abstractmethod
from logging import Logger
from typing import TYPE_CHECKING, Any, NoReturn

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
from custom_components.elasticsearch.loop import LoopHandler

from .logger import LOGGER as BASE_LOGGER
from .logger import async_log_enter_exit, log_enter_exit

if TYPE_CHECKING:
    import asyncio  # nocover


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

        self._minimum_privileges: dict[str, Any] | None = minimum_privileges
        self._info: dict[str, Any] = {}
        self._capabilities: dict = {}

        self._cancel_connection_monitor: asyncio.Task | None = None
        self._use_connection_monitor: bool = use_connection_monitor

        self._first_check: bool = True
        self._previous: bool = False
        self._active: bool = False

    @log_enter_exit
    async def async_init(self, config_entry=None) -> None:
        """I/O bound init."""

        # if not await self.test_connection():
        #     msg = "Connection test failed."  # noqa: ERA001
        #     raise convert_es_error(msg, ConnectionError)  # noqa: ERA001
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
            raise UnsupportedVersion

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
                connection_loop.start(),
                "es_gateway_monitor_task",
            )

    @property
    def hass(self) -> HomeAssistant:
        """Return the Home Assistant instance."""
        return self._hass

    @property
    def url(self) -> str:
        """Return the Home Assistant instance."""
        return self._url

    @property
    def capabilities(self) -> dict:
        """Return the underlying ES Capabilities."""
        if self._capabilities == {}:
            msg = "Capabilities have not been initialized Call async_init first."
            raise ValueError(msg)

        return self._capabilities

    def has_capability(self, capability: str) -> bool:
        """Determine if the Elasticsearch instance has the specified capability."""
        return self.capabilities.get(capability, False)

    @property
    def active(self) -> bool:
        """Return the state of the connection_monitor."""
        return self._active

    @property
    def client(self) -> AsyncElasticsearch7 | AsyncElasticsearch8:
        """Return the underlying ES Client."""
        return self._client

    @property
    def authentication_type(self) -> str:
        """Return the authentication type."""

        if self._client_args.get("http_auth", None) or self._client_args.get("basic_auth", None) is not None:
            return "basic"
        elif self._client_args.get("headers", None) or self._client_args.get("api_key", None) is not None:
            return "api_key"
        else:
            return "none"

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
        minimum_privileges=ES_CHECK_PERMISSIONS_DATASTREAM,
        logger=BASE_LOGGER,
    ) -> bool:
        """Test the settings provided by the user and make sure they work."""
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
            gateway.convert_es_error()
        finally:
            await gateway.stop()

        return True

    @classmethod
    def build_gateway_parameters(
        cls,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        minimum_privileges: dict[str, Any] | None = ES_CHECK_PERMISSIONS_DATASTREAM,
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

    @log_enter_exit
    async def stop(self) -> None:
        """Stop the ES Gateway."""
        self._logger.warning("Stopping Elasticsearch Gateway")

        if self.client:
            await self.client.close()

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

    @classmethod
    @abstractmethod
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

    async def _get_cluster_info(self) -> dict:
        """Retrieve info about the connected elasticsearch cluster."""
        try:
            info = await self._client.info()
        except (TransportError7, TransportError8):
            self.convert_es_error()
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
            result = await self._client.indices.get_template(**kwargs)

        except ConnectionError:
            msg = "Error retrieving index template"
            self.convert_es_error(msg)

        except Exception:
            self._logger.exception("Unknown error retrieving cluster info")
            raise

        if not isinstance(result, dict):
            self._logger.error("Invalid response from Elasticsearch")

        return self._convert_api_response_to_dict(result)

    async def put_index_template(self, **kwargs) -> dict:
        """Retrieve an index template."""
        self._logger.debug("Updating index template %s", kwargs.get("name", ""))

        try:
            result = await self._client.indices.put_index_template(**kwargs)

        except ConnectionError:
            msg = "Error creating/updating index template"
            self.convert_es_error(msg)
        except Exception:
            self._logger.exception("Unknown error creating/updating index template")
            raise

        if not isinstance(result, dict):
            self._logger.error("Invalid response from Elasticsearch")

        return self._convert_api_response_to_dict(result)

    # Abstract Methods

    @abstractmethod
    async def bulk(self, **kwargs) -> None:
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

    async def bulk(self, actions) -> None:
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

    @async_log_enter_exit
    async def bulk(self, actions) -> None:
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

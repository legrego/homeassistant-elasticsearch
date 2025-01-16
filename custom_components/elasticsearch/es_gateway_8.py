"""Elasticsearch Gateway for Elasticsearch 8.0.0."""

from __future__ import annotations

import ssl
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import elasticsearch8
from elastic_transport import ObjectApiResponse
from elasticsearch8._async.client import AsyncElasticsearch
from elasticsearch8.helpers import async_streaming_bulk
from homeassistant.util.ssl import client_context

from custom_components.elasticsearch.const import ES_CHECK_PERMISSIONS_DATASTREAM
from custom_components.elasticsearch.encoder import Serializer
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    CannotConnect,
    InsufficientPrivileges,
    ServerError,
    UntrustedCertificate,
)
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway, GatewaySettings

from .logger import LOGGER as BASE_LOGGER
from .logger import async_log_enter_exit_debug

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncGenerator
    from logging import Logger


@dataclass
class Gateway8Settings(GatewaySettings):
    """Elasticsearch Gateway settings object."""

    def to_client(self) -> AsyncElasticsearch:
        """Create an Elasticsearch client from the settings."""

        settings = {
            "hosts": [self.url],
            "serializer": Serializer(),
            "request_timeout": self.request_timeout,
        }

        if self.url.startswith("https"):
            context: ssl.SSLContext = client_context()

            if not self.verify_certs:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            else:
                context.check_hostname = self.verify_hostname
                context.verify_mode = ssl.CERT_REQUIRED

                if self.ca_certs:
                    context.load_verify_locations(cafile=self.ca_certs)

            settings["ssl_context"] = context

        if self.username:
            settings["basic_auth"] = (self.username, self.password)

        if self.api_key:
            settings["api_key"] = self.api_key

        return AsyncElasticsearch(**settings)


class Elasticsearch8Gateway(ElasticsearchGateway):
    """Encapsulates Elasticsearch operations."""

    _settings: Gateway8Settings
    _client: AsyncElasticsearch

    def __init__(
        self,
        gateway_settings: Gateway8Settings,
        log: Logger = BASE_LOGGER,
    ) -> None:
        """Initialize the Elasticsearch Gateway."""

        super().__init__(
            gateway_settings=gateway_settings,
            log=log,
        )

        self._settings = gateway_settings
        self._client = self._settings.to_client()

    async def async_init(self) -> None:
        """Initialize the Elasticsearch Gateway."""

        await super().async_init()

    @classmethod
    async def async_init_then_stop(
        cls,
        url: str,
        username: str | None = None,
        password: str | None = None,
        api_key: str | None = None,
        verify_certs: bool = True,
        verify_hostname: bool = True,
        ca_certs: str | None = None,
        request_timeout: int = 30,
        minimum_privileges: MappingProxyType[str, Any] = ES_CHECK_PERMISSIONS_DATASTREAM,
        log: Logger = BASE_LOGGER,
    ) -> None:
        """Initialize the gateway and then stop it."""

        gateway = cls(
            Gateway8Settings(
                url=url,
                username=username,
                password=password,
                api_key=api_key,
                verify_certs=verify_certs,
                verify_hostname=verify_hostname,
                ca_certs=ca_certs,
                request_timeout=request_timeout,
                minimum_privileges=minimum_privileges,
            ),
            log=log,
        )

        try:
            await gateway.async_init()
        finally:
            await gateway.stop()

    @property
    def client(self) -> AsyncElasticsearch:
        """Return the underlying ES Client."""

        return self._client

    @property
    def settings(self) -> Gateway8Settings:
        """Return the settings."""

        return self._settings

    @async_log_enter_exit_debug
    async def info(self) -> dict:
        """Retrieve info about the connected elasticsearch cluster."""

        with self._error_converter(msg="Error retrieving cluster info from Elasticsearch"):
            response = await self.client.info()

        return self._convert_response(response)

    @async_log_enter_exit_debug
    async def ping(self) -> bool:
        """Ping the Elasticsearch cluster. Raises only on Authentication issues."""
        try:
            await self.info()

        except AuthenticationRequired:
            self._previous_ping = False

            self._logger.debug("Authentication error pinging Elasticsearch", exc_info=True)

            raise
        except:  # noqa: E722
            self._previous_ping = False

            self._logger.debug("Error pinging Elasticsearch", exc_info=True)

            return False
        else:
            self._previous_ping = True

            return True

    @async_log_enter_exit_debug
    async def has_security(self) -> bool:
        """Check if the cluster has security enabled."""

        with self._error_converter(msg="Error checking whether platform is serverless"):
            # Check if the cluster is serverless, security is always enabled in serverless
            info: dict = await self.info()

        if self._is_serverless(info):
            return True

        with self._error_converter(msg="Error checking for security features"):
            # If we are not serverless, check if security is enabled using xpack APIs
            response = await self.client.xpack.usage()

        xpack_features = self._convert_response(response)

        if "security" in xpack_features:
            return xpack_features["security"].get("enabled", False)

        return False

    @async_log_enter_exit_debug
    async def has_privileges(self, privileges) -> bool:
        """Check if the user has the required privileges."""
        with self._error_converter(msg="Error checking user privileges"):
            response = await self.client.security.has_privileges(**privileges)

        return self._convert_response(response).get("has_all_requested", False)

    @async_log_enter_exit_debug
    async def get_index_template(self, name, ignore: list[int] | None = None) -> dict:
        """Retrieve an index template."""
        with self._error_converter(msg="Error retrieving index template"):
            options = {}
            if ignore:
                options["ignore_status"] = ignore
            response = await self.client.options(**options).indices.get_index_template(name=name)

        return self._convert_response(response)

    @async_log_enter_exit_debug
    async def put_index_template(self, name, body) -> dict:
        """Create an index template."""
        with self._error_converter(msg="Error creating index template"):
            response = await self.client.indices.put_index_template(name=name, **body)

        return self._convert_response(response)

    @async_log_enter_exit_debug
    async def get_datastream(self, datastream: str) -> dict:
        """Retrieve datastreams."""
        with self._error_converter(msg="Error retrieving datastreams"):
            response = await self.client.indices.get_data_stream(name=datastream)

        return self._convert_response(response)

    @async_log_enter_exit_debug
    async def rollover_datastream(self, datastream: str) -> dict:
        """Rollover an index."""
        with self._error_converter(msg="Error rolling over datastream"):
            response = await self.client.indices.rollover(alias=datastream)

        return self._convert_response(response)

    @async_log_enter_exit_debug
    async def bulk(self, actions: AsyncGenerator[dict[str, Any], Any]) -> None:
        """Perform a bulk operation."""

        with self._error_converter("Error performing bulk operation"):
            count = 0
            okcount = 0
            errcount = 0
            async for ok, result in async_streaming_bulk(
                client=self.client,
                actions=actions,
                max_retries=3,
                raise_on_error=False,
                yield_ok=True,
            ):
                count += 1
                action, outcome = result.popitem()
                if not ok:
                    errcount += 1
                    self._logger.error("failed to %s, error information: %s", action, outcome)
                else:
                    okcount += 1

            if count > 0:
                if errcount == 0:
                    self._logger.info("Successfully published %d documents", okcount)
                elif errcount > 0:
                    self._logger.error("Failed to publish %d of %d documents", errcount, count)
            else:
                self._logger.debug("Publish skipped, no new events to publish.")

    async def stop(self) -> None:
        """Stop the gateway."""
        if self._client is not None:
            await self.client.close()

    # Functions for handling errors and response conversion

    def _convert_response(self, response: ObjectApiResponse[Any]) -> dict[Any, Any]:
        """Convert the API response to a dictionary."""

        # The response body is always a dictionary, but mypy doesn't know that
        assert isinstance(response.body, dict)

        return dict(response.body)

    @contextmanager
    def _error_converter(self, msg: str | None = None):
        """Convert an internal error from the elasticsearch package into one of our own."""

        def append_msg(append_msg: str) -> str:
            """Append the exception's message to the caller's message."""
            if msg is None:
                return append_msg

            return f"{msg}. {append_msg}"

        def append_cause(err: elasticsearch8.ApiError, msg: str) -> str:
            """Append the root cause to the error message."""
            if err.info is None or err.info.get("error", None) is None:
                return msg

            error_details = err.info["error"]

            specifics: OrderedDict = OrderedDict()
            if "type" in error_details:
                specifics["type"] = error_details["type"]

            if "reason" in error_details:
                specifics["reason"] = error_details["reason"]

            # join specifics into a string with key: value pairs
            specific_str = "; ".join(f"{k}={v}" for k, v in specifics.items())

            return f"{msg} ({specific_str})"

        try:
            yield

        except elasticsearch8.UnsupportedProductError as err:
            # The HTTP response didn't include headers={"x-elastic-product": "Elasticsearch"}
            raise CannotConnect(append_msg("Unsupported product error connecting to Elasticsearch")) from err

        except elasticsearch8.AuthenticationException as err:
            raise AuthenticationRequired(
                append_cause(err, append_msg("Authentication error connecting to Elasticsearch"))
            ) from err

        except elasticsearch8.AuthorizationException as err:
            raise InsufficientPrivileges(
                append_cause(err, append_msg("Authorization error connecting to Elasticsearch"))
            ) from err

        except elasticsearch8.ConnectionTimeout as err:
            raise ServerError(append_msg("Connection timeout connecting to Elasticsearch")) from err

        except elasticsearch8.SSLError as err:
            raise UntrustedCertificate(
                append_msg(f"Could not complete TLS Handshake. {err.message}")
            ) from err

        except elasticsearch8.ConnectionError as err:
            raise CannotConnect(append_msg(f"Error connecting to Elasticsearch. {err.message}")) from err

        except elasticsearch8.TransportError as err:
            raise CannotConnect(
                append_msg(f"Unknown transport error connecting to Elasticsearch: {err.message}")
            ) from err

        except elasticsearch8.ApiError as err:
            if err.status_code is not None:
                raise ServerError(
                    append_msg(f"Error in request to Elasticsearch: {err.status_code}")
                ) from err
            else:
                raise ServerError(append_msg("Unknown API Error in request to Elasticsearch")) from err

        except Exception:
            BASE_LOGGER.exception("Unknown and unexpected exception occurred.")
            raise

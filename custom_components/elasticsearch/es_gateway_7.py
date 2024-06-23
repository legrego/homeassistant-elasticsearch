"""Elasticsearch Gateway for Elasticsearch 7.0.0."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import elasticsearch7
from aiohttp import client_exceptions
from elastic_transport import ObjectApiResponse
from elasticsearch7._async.client import AsyncElasticsearch
from elasticsearch7.helpers import BulkIndexError, async_streaming_bulk
from elasticsearch7.serializer import JSONSerializer

from custom_components.elasticsearch.const import ES_CHECK_PERMISSIONS_DATASTREAM
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    CannotConnect,
    ClientError,
    ESIntegrationException,
    IndexingError,
    InsufficientPrivileges,
    ServerError,
    SSLError,
    UntrustedCertificate,
)
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway, GatewaySettings

from .logger import LOGGER as BASE_LOGGER
from .logger import async_log_enter_exit_debug

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from logging import Logger


@dataclass
class Gateway7Settings(GatewaySettings):
    """Elasticsearch Gateway settings object."""

    def to_client(self) -> AsyncElasticsearch:
        """Convert the settings to a dictionary suitable for passing to the Elasticsearch client."""

        settings = {
            "hosts": [self.url],
            "serializer": Encoder(),
            "verify_certs": self.verify_certs,
            "ssl_show_warn": self.verify_certs,
            "ca_certs": self.ca_certs,
            "request_timeout": self.request_timeout,
        }

        if self.username:
            settings["http_auth"] = (self.username, self.password)

        if self.api_key:
            settings["headers"] = {"Authorization": f"ApiKey {self.api_key}"}

        return AsyncElasticsearch(**settings)


class Encoder(JSONSerializer):
    """JSONSerializer which serializes sets to lists."""

    def default(self, data: Any) -> Any:
        """Entry point."""
        if isinstance(data, set):
            output = list(data)
            output.sort()
            return output

        return JSONSerializer.default(self, data)


class Elasticsearch7Gateway(ElasticsearchGateway):
    """Encapsulates Elasticsearch operations."""

    def __init__(
        self,
        gateway_settings: Gateway7Settings,
        log: Logger = BASE_LOGGER,
    ) -> None:
        """Initialize the Elasticsearch Gateway."""
        super().__init__(
            gateway_settings=gateway_settings,
            log=log,
        )

        self._client: AsyncElasticsearch | None = None
        self._settings: Gateway7Settings = gateway_settings

    async def async_init(self) -> None:
        """Initialize the Elasticsearch Gateway."""
        self._client = self._settings.to_client()

        await super().async_init()

    @classmethod
    async def async_init_then_stop(
        cls,
        url: str,
        username: str | None = None,
        password: str | None = None,
        api_key: str | None = None,
        verify_certs: bool = True,
        ca_certs: str | None = None,
        request_timeout: int = 30,
        minimum_privileges: dict[str, Any] = ES_CHECK_PERMISSIONS_DATASTREAM,
        log: Logger = BASE_LOGGER,
    ) -> None:
        """Initialize the gateway and then stop it."""

        gateway = cls(
            Gateway7Settings(
                url=url,
                username=username,
                password=password,
                api_key=api_key,
                verify_certs=verify_certs,
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
        if self._client is None:
            raise CannotConnect("Elasticsearch client not initialized.")

        return self._client

    @property
    def settings(self) -> Gateway7Settings:
        """Return the settings."""
        if not self._settings:
            raise CannotConnect("Elasticsearch settings not initialized.")

        return self._settings

    # @async_log_enter_exit_debug
    # async def ping(self) -> bool:
    #     """Ping the Elasticsearch cluster."""

    #     with self._error_converter(msg=""):
    #         return await self.client.ping()

    @async_log_enter_exit_debug
    async def info(self) -> dict:
        """Retrieve info about the connected elasticsearch cluster."""

        with self._error_converter(msg="Error connecting to Elasticsearch"):
            response = await self.client.info()

        return self._convert_response(response)

    @async_log_enter_exit_debug
    async def ping(self) -> bool:
        """Ping the Elasticsearch cluster."""
        try:
            await self.client.info()
        except:  # noqa: E722
            self._logger.exception("Error pinging Elasticsearch")
            return False
        else:
            return True

    @async_log_enter_exit_debug
    async def has_privileges(self, privileges) -> dict:
        """Check if the user has the required privileges."""
        with self._error_converter(msg="Error checking user privileges"):
            response = await self.client.security.has_privileges(body=privileges)

        return self._convert_response(response)

    @async_log_enter_exit_debug
    async def get_index_template(self, name, ignore=None) -> dict:
        """Retrieve an index template."""
        with self._error_converter(msg="Error retrieving index template"):
            response = await self.client.indices.get_index_template(name=name, ignore=ignore)

        return self._convert_response(response)

    @async_log_enter_exit_debug
    async def put_index_template(self, name, body) -> dict:
        """Create an index template."""
        with self._error_converter(msg="Error creating index template"):
            response = await self.client.indices.put_index_template(name=name, body=body)

        return self._convert_response(response)

    @async_log_enter_exit_debug
    async def bulk(self, actions: AsyncGenerator[dict[str, Any], Any]) -> None:
        """Perform a bulk operation."""

        with self._error_converter("Error performing bulk operation"):
            count = 0
            async for ok, result in async_streaming_bulk(
                client=self.client,
                actions=actions,
                yield_ok=True,
                max_retries=3,
            ):
                count += 1
                action, outcome = result.popitem()
                if not ok:
                    self._logger.error("failed to %s document %s", action, outcome)

            if count > 0:
                self._logger.info("Created %s new documents in Elasticsearch.", count)
            else:
                self._logger.debug("Publish skipped, no new events to publish.")

    async def stop(self) -> None:
        """Stop the gateway."""
        if self._client is not None:
            await self.client.close()

    # Functions for handling errors and response conversion

    def _convert_response(self, response: ObjectApiResponse[Any]) -> dict[Any, Any]:
        """Convert the API response to a dictionary."""
        if not isinstance(response, dict):
            msg = "Invalid response from Elasticsearch"
            raise TypeError(msg)

        return dict(response)

    @contextmanager
    def _error_converter(self, msg: str | None = None):
        """Convert an internal error from the elasticsearch package into one of our own."""
        try:
            yield

        except BulkIndexError as err:
            msg = "Error indexing data"
            raise IndexingError(msg) from err

        except elasticsearch7.AuthenticationException as err:
            msg = "Authentication error connecting to Elasticsearch"
            raise AuthenticationRequired(msg) from err

        except elasticsearch7.AuthorizationException as err:
            msg = "Authorization error connecting to Elasticsearch"
            raise InsufficientPrivileges(msg) from err

        except elasticsearch7.SSLError as err:
            msg = "SSL error connecting to Elasticsearch"
            raise SSLError(msg) from err

        except elasticsearch7.ConnectionError as err:
            if isinstance(err.info, client_exceptions.ClientConnectorCertificateError):
                msg = "Untrusted certificate connecting to Elasticsearch"
                raise UntrustedCertificate(msg) from err

            if issubclass(type(err.info), client_exceptions.ServerConnectionError):
                msg = "Server error connecting to Elasticsearch"
                raise ServerError(msg) from err

            if issubclass(type(err.info), client_exceptions.ClientError):
                msg = "Client error connecting to Elasticsearch"
                raise ClientError(msg) from err

            msg = "Connection error connecting to Elasticsearch"
            raise CannotConnect(msg) from err

        except elasticsearch7.TransportError as err:
            msg = f"Error connecting to Elasticsearch: {err.status_code}"
            raise CannotConnect(msg) from err

        except elasticsearch7.ElasticsearchException as err:
            msg = "Unknown error connecting to Elasticsearch"
            raise ESIntegrationException(msg) from err

        except Exception:
            BASE_LOGGER.exception("Unknown and unexpected exception occurred.")
            raise

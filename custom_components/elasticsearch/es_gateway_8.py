"""Elasticsearch Gateway for Elasticsearch 8.0.0."""

from __future__ import annotations

import asyncio
import re
import ssl
from collections import OrderedDict
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

import aiohttp
import elasticsearch
from elastic_transport import (
    AiohttpHttpNode,
    AsyncTransport,
    HttpHeaders,
    ObjectApiResponse,
    SerializationError,
    TransportApiResponse,
)
from elastic_transport.client_utils import DEFAULT, DefaultType
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_streaming_bulk
from homeassistant.util.ssl import create_client_context, create_no_verify_ssl_context
from multidict import CIMultiDict, CIMultiDictProxy

from custom_components.elasticsearch.const import (
    ELASTIC_COMPATIBILITY_VERSION,
    ES_CHECK_PERMISSIONS_DATASTREAM,
)
from custom_components.elasticsearch.encoder import Serializer
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    BadRequest,
    CannotConnect,
    InsufficientPrivileges,
    InvalidCACertificate,
    InvalidQueryResponse,
    RequestTimeout,
    ServerError,
    UnsupportedServer,
    UntrustedCertificate,
)
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway, EsqlResponse, GatewaySettings

from .logger import LOGGER as BASE_LOGGER
from .logger import async_log_enter_exit_debug

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncGenerator, Iterator
    from logging import Logger


_COMPATIBLE_WITH = re.compile(r"compatible-with=\d+")
_COMPATIBLE_WITH_VERSION = f"compatible-with={ELASTIC_COMPATIBILITY_VERSION}"
_COMPATIBILITY_HEADERS = ("accept", "content-type")

# ES|QL warnings are moved to this header, so that the client doesn't see them. See
# CompatibilityTransport.
ESQL_WARNING_HEADER = "x-homeassistant-esql-warning"
_ESQL_TARGET = "/_query"

# One warning in a `Warning` header: a code, an agent, the quoted text, and an optional quoted date.
# The text is an HTTP quoted string, in which a backslash escapes the next character.
_WARNING_VALUE = re.compile(r'\d{3} \S+ "((?:[^"\\]|\\.)*)"(?: "[^"]*")?')
_ESCAPED_CHARACTER = re.compile(r"\\(.)")

# aiohttp decodes headers as UTF-8, and keeps bytes that aren't valid UTF-8 as lone surrogates.
# Elasticsearch sends non-ASCII characters in warnings as ISO-8859-1 bytes, which become these.
_ESCAPED_BYTE = re.compile("[\udc80-\udcff]")


def parse_warning_header(header: str) -> list[str]:
    """Return the text of each warning in a `Warning` header, decoded as Elasticsearch encodes it.

    Elasticsearch escapes quotes and backslashes in the text, then percent-encodes `%`.
    """

    header = _ESCAPED_BYTE.sub(lambda match: chr(ord(match.group()) - 0xDC00), header).strip()
    if not header:
        return []

    texts = [match.group(1) for match in _WARNING_VALUE.finditer(header)]
    if not texts:
        # Not a header Elasticsearch formatted, so it's returned as it is
        return [header]

    return [_ESCAPED_CHARACTER.sub(r"\1", unquote(text, errors="replace")) for text in texts]


class JoinedWarningsResponse(aiohttp.ClientResponse):
    """A response that joins repeated `Warning` headers into one.

    Elasticsearch sends each warning in its own header, but elastic-transport keeps only the first
    value of each header. ES|QL often sends several, and the first is usually only about the
    default row limit, so the warnings that matter would be lost.
    """

    @property
    def headers(self) -> CIMultiDictProxy[str]:
        """Return the response headers, with every warning in a single `Warning` header."""
        headers: CIMultiDictProxy[str] = super().headers
        values = headers.getall("warning", [])
        if len(values) < 2:
            return headers

        joined = CIMultiDict((name, value) for name, value in headers.items() if name.lower() != "warning")
        joined["Warning"] = ", ".join(values)
        return CIMultiDictProxy(joined)


class JoinedWarningsNode(AiohttpHttpNode):
    """An aiohttp node whose responses keep every warning Elasticsearch sends."""

    def _create_aiohttp_session(self) -> None:
        """Create the session, then have it build JoinedWarningsResponse responses."""
        super()._create_aiohttp_session()
        # aiohttp only takes the response class when the session is created, and the node
        # creates it without one. The attribute is checked by tests.
        self.session._response_class = JoinedWarningsResponse  # type: ignore[union-attr]  # noqa: SLF001


class CompatibilityTransport(AsyncTransport):
    """Transport that asks Elasticsearch for a fixed REST API compatibility version.

    The client asks for compatibility with its own major version, but Elasticsearch only accepts
    its own major version and the one before it. Asking for an older version lets one client work
    with every cluster version the integration supports.
    """

    async def perform_request(  # type: ignore[override]
        self,
        method: str,
        target: str,
        *,
        headers: Mapping[str, Any] | DefaultType = DEFAULT,
        **kwargs: Any,
    ) -> TransportApiResponse:
        """Rewrite the compatibility version in the request headers, then send the request."""

        if isinstance(headers, Mapping):
            headers = HttpHeaders(headers)
            for name in _COMPATIBILITY_HEADERS:
                if name in headers:
                    headers[name] = _COMPATIBLE_WITH.sub(_COMPATIBLE_WITH_VERSION, headers[name])

        response = await super().perform_request(method, target, headers=headers, **kwargs)

        # The client raises every `Warning` header as a Python warning, which Home Assistant logs.
        # ES|QL warnings quote the query, so they'd leak it into the log. They're returned with
        # the query's result instead.
        if target.split("?", 1)[0] == _ESQL_TARGET and "warning" in response.meta.headers:
            response.meta.headers[ESQL_WARNING_HEADER] = response.meta.headers["warning"]
            del response.meta.headers["warning"]

        return response


@dataclass
class Gateway8Settings(GatewaySettings):
    """Elasticsearch Gateway settings object."""

    def _build_ssl_context(self) -> ssl.SSLContext:
        """Build a TLS context that belongs to this client alone.

        Home Assistant's `client_context` is shared across the whole process, so our TLS
        settings must never be applied to it. Building a context reads certificates from
        disk, so this must not run on the event loop.
        """

        if not self.verify_certs:
            return create_no_verify_ssl_context()

        context = create_client_context()
        context.check_hostname = self.verify_hostname

        if self.ca_certs:
            try:
                context.load_verify_locations(cafile=self.ca_certs)
            except OSError as err:  # Includes ssl.SSLError
                msg = f"Unable to load certificate authority file [{self.ca_certs}]: {err}"
                raise InvalidCACertificate(msg) from err

        return context

    def to_client(self) -> AsyncElasticsearch:
        """Create an Elasticsearch client from the settings. This performs blocking I/O."""

        settings: dict[str, Any] = {
            "hosts": [self.url],
            "serializer": Serializer(),
            "request_timeout": self.request_timeout,
            "transport_class": CompatibilityTransport,
            "node_class": JoinedWarningsNode,
        }

        if self.url.startswith("https"):
            settings["ssl_context"] = self._build_ssl_context()

        if self.username:
            settings["basic_auth"] = (self.username, self.password)

        if self.api_key:
            settings["api_key"] = self.api_key

        return AsyncElasticsearch(**settings)


class Elasticsearch8Gateway(ElasticsearchGateway):
    """Encapsulates Elasticsearch operations."""

    _settings: Gateway8Settings
    _client: AsyncElasticsearch | None

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
        self._client = None

    async def async_init(self) -> None:
        """Initialize the Elasticsearch Gateway."""

        if self._client is None:
            self._client = await asyncio.to_thread(self._settings.to_client)

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
    ) -> str | None:
        """Initialize the gateway and then stop it, returning the UUID of the cluster."""

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

        return gateway.cluster_uuid

    @property
    def client(self) -> AsyncElasticsearch:
        """Return the underlying ES Client."""

        # The client exists once async_init has run, but mypy doesn't know that
        assert self._client is not None

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

        if not isinstance(response.body, dict):
            raise UnsupportedServer("The endpoint does not return Elasticsearch server information.")

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

        self._validate_cluster_info(info)
        if self._is_serverless(info):
            return True

        with self._error_converter(msg="Error checking for security features"):
            # If we are not serverless, check if security is enabled using xpack APIs
            response = await self.client.xpack.usage()

        xpack_features = self._convert_response(response)

        if "security" in xpack_features:
            return bool(xpack_features["security"].get("enabled", False))

        return False

    @async_log_enter_exit_debug
    async def has_privileges(self, privileges: Mapping[str, Any]) -> bool:
        """Check if the user has the required privileges."""
        with self._error_converter(msg="Error checking user privileges"):
            response = await self.client.security.has_privileges(**privileges)

        return bool(self._convert_response(response).get("has_all_requested", False))

    @async_log_enter_exit_debug
    async def get_index_template(self, name: str, ignore: list[int] | None = None) -> dict:
        """Retrieve an index template."""
        with self._error_converter(msg="Error retrieving index template"):
            options: dict[str, Any] = {}
            if ignore:
                options["ignore_status"] = ignore
            response = await self.client.options(**options).indices.get_index_template(name=name)

        return self._convert_response(response)

    @async_log_enter_exit_debug
    async def put_index_template(self, name: str, body: dict[str, Any]) -> dict:
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

    @async_log_enter_exit_debug
    async def esql_query(self, query: str, params: list[Any]) -> EsqlResponse:
        """Run an ES|QL query, never accepting partial results."""
        try:
            with self._error_converter(msg="Error running ES|QL query"):
                response = await self.client.esql.query(
                    query=query, params=params, allow_partial_results=False
                )
        except CannotConnect as err:
            # The client's error for a response it can't parse includes the whole response, which
            # can hold query results. It's replaced, and not chained, so the results aren't logged.
            if isinstance(err.__cause__, SerializationError):
                msg = "Elasticsearch returned a query response that couldn't be parsed."
                raise InvalidQueryResponse(msg) from None
            raise

        if not isinstance(response.body, dict):
            msg = "Elasticsearch returned a query response that isn't an object."
            raise InvalidQueryResponse(msg)

        warnings = parse_warning_header(response.meta.headers.get(ESQL_WARNING_HEADER) or "")

        return EsqlResponse(body=dict(response.body), warnings=warnings)

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
    def _error_converter(self, msg: str | None = None) -> Iterator[None]:
        """Convert an internal error from the elasticsearch package into one of our own."""

        def append_msg(append_msg: str) -> str:
            """Append the exception's message to the caller's message."""
            if msg is None:
                return append_msg

            return f"{msg}. {append_msg}"

        def append_cause(err: elasticsearch.ApiError, msg: str) -> str:
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

        except elasticsearch.UnsupportedProductError as err:
            # The HTTP response didn't include headers={"x-elastic-product": "Elasticsearch"}
            raise UnsupportedServer(
                append_msg("Unsupported product error connecting to Elasticsearch")
            ) from err

        except elasticsearch.AuthenticationException as err:
            raise AuthenticationRequired(
                append_cause(err, append_msg("Authentication error connecting to Elasticsearch"))
            ) from err

        except elasticsearch.AuthorizationException as err:
            raise InsufficientPrivileges(
                append_cause(err, append_msg("Authorization error connecting to Elasticsearch"))
            ) from err

        except elasticsearch.ConnectionTimeout as err:
            raise RequestTimeout(append_msg("Connection timeout connecting to Elasticsearch")) from err

        except elasticsearch.SSLError as err:
            raise UntrustedCertificate(
                append_msg(f"Could not complete TLS Handshake. {err.message}")
            ) from err

        except elasticsearch.ConnectionError as err:
            raise CannotConnect(append_msg(f"Error connecting to Elasticsearch. {err.message}")) from err

        except elasticsearch.TransportError as err:
            raise CannotConnect(
                append_msg(f"Unknown transport error connecting to Elasticsearch: {err.message}")
            ) from err

        except elasticsearch.BadRequestError as err:
            error_details = err.info.get("error") if isinstance(err.info, dict) else None
            if not isinstance(error_details, dict):
                error_details = {}
            raise BadRequest(
                append_msg(f"Error in request to Elasticsearch: {err.status_code}"),
                error_type=error_details.get("type"),
                reason=error_details.get("reason"),
            ) from err

        except elasticsearch.ApiError as err:
            if err.status_code is not None:
                raise ServerError(
                    append_msg(f"Error in request to Elasticsearch: {err.status_code}")
                ) from err
            else:
                raise ServerError(append_msg("Unknown API Error in request to Elasticsearch")) from err

        except Exception:
            BASE_LOGGER.exception("Unknown and unexpected exception occurred.")
            raise

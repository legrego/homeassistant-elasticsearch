"""Encapsulates Elasticsearch operations."""

from __future__ import annotations  # noqa: I001

from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING
from custom_components.elasticsearch.errors import (
    InsufficientPrivileges,
    UnsupportedServer,
    UnsupportedVersion,
)
from custom_components.elasticsearch.const import ES_CHECK_PERMISSIONS_DATASTREAM, ELASTIC_MINIMUM_VERSION

from .logger import LOGGER as BASE_LOGGER
from .logger import log_enter_exit_debug
from typing import Any

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncGenerator, Mapping
    from logging import Logger

    from elasticsearch import AsyncElasticsearch


@dataclass(frozen=True)
class EsqlResponse:
    """The body of an ES|QL query response, and the warnings Elasticsearch sent with it."""

    body: dict[str, Any]
    warnings: list[str]


@dataclass
class GatewaySettings(ABC):
    """Elasticsearch Gateway settings object."""

    url: str
    username: str | None = None
    password: str | None = None
    api_key: str | None = None
    verify_certs: bool = True
    ca_certs: str | None = None
    request_timeout: int = 30
    verify_hostname: bool = True
    minimum_version: tuple[int, int] | None = None
    minimum_privileges: MappingProxyType[str, Any] = MappingProxyType[str, Any]({})

    @abstractmethod
    def to_client(self) -> AsyncElasticsearch:
        """Return an Elasticsearch client."""

    def to_dict(self) -> dict:
        """Return a dictionary representation of the settings."""
        return {
            "url": self.url,
            "username": self.username,
            "password": self.password,
            "api_key": self.api_key,
            "verify_certs": self.verify_certs,
            "ca_certs": self.ca_certs,
            "request_timeout": self.request_timeout,
            "verify_hostname": self.verify_hostname,
            "minimum_version": self.minimum_version,
            # Perform a shallow copy of the mapping proxy to allow serialization
            "minimum_privileges": self.minimum_privileges.copy(),
        }


class ElasticsearchGateway(ABC):
    """Encapsulates Elasticsearch operations."""

    _logger: Logger = BASE_LOGGER

    def __init__(
        self,
        gateway_settings: GatewaySettings,
        log: Logger = BASE_LOGGER,
    ) -> None:
        """Non-I/O bound init."""

        self._logger = log

        self._previous_ping: bool | None = None
        self._cluster_uuid: str | None = None
        self._cluster_version: str | None = None
        self._build_flavor: str | None = None

    @log_enter_exit_debug
    async def async_init(self) -> None:
        """I/O bound init."""

        # Test the connection
        cluster_info = await self.info()
        self._validate_cluster_info(cluster_info)
        self._previous_ping = True

        # Elasticsearch reports "_na_" until the cluster has formed
        cluster_uuid = cluster_info.get("cluster_uuid")
        self._cluster_uuid = None if cluster_uuid == "_na_" else cluster_uuid

        self._cluster_version = cluster_info["version"]["number"]
        self._build_flavor = cluster_info["version"]["build_flavor"]

        # Minimum version check
        if not self._is_supported_version(cluster_info):
            msg = f"Elasticsearch version is not supported. Minimum version: {ELASTIC_MINIMUM_VERSION}"
            raise UnsupportedVersion(msg, version=cluster_info["version"]["number"])

        # Check minimum privileges
        if await self.has_security() and not await self.has_privileges(self.settings.minimum_privileges):
            raise InsufficientPrivileges

    @property
    @abstractmethod
    def client(self) -> AsyncElasticsearch:
        """Return the underlying ES Client."""

    @property
    @abstractmethod
    def settings(self) -> GatewaySettings:
        """Return the settings."""

    @property
    def cluster_uuid(self) -> str | None:
        """Return the UUID of the connected cluster, if it is known."""

        return self._cluster_uuid

    @property
    def cluster_version(self) -> str | None:
        """Return the version number the cluster reported, if it is known."""

        return self._cluster_version

    @property
    def build_flavor(self) -> str | None:
        """Return the build flavor the cluster reported, such as `default` or `serverless`."""

        return self._build_flavor

    @property
    def connected(self) -> bool | None:
        """Return the result of the last connection check, or None before the first one."""

        return self._previous_ping

    @classmethod
    @abstractmethod
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

    @abstractmethod
    async def info(self) -> dict:
        """Retrieve info about the connected elasticsearch cluster."""

    async def check_connection(self) -> bool:
        """Check if the connection to the Elasticsearch cluster is working."""

        previous_ping = self._previous_ping
        new_ping = await self.ping()

        # Our first connection check
        if previous_ping is None:
            established = new_ping
            if established:
                self._logger.info("Connection to Elasticsearch is established.")
            else:
                self._logger.error("Failed to establish connection to Elasticsearch.")

            return new_ping

        reestablished: bool = not previous_ping and new_ping
        maintained = previous_ping and new_ping
        lost: bool = previous_ping and not new_ping
        down: bool = not previous_ping and not new_ping

        if maintained:
            self._logger.debug("Connection to Elasticsearch is still available.")

        if lost:
            self._logger.error("Connection to Elasticsearch has been lost.")

        if down:
            self._logger.debug("Connection to Elasticsearch is still down.")

        if reestablished:
            self._logger.info("Connection to Elasticsearch has been reestablished.")

        return new_ping

    @abstractmethod
    async def ping(self) -> bool:
        """Pings the connected elasticsearch cluster."""

    @abstractmethod
    async def has_security(self) -> bool:
        """Check if the cluster has security enabled."""

    @abstractmethod
    async def has_privileges(self, privileges: Mapping[str, Any]) -> bool:
        """Check if the user has the specified privileges."""

    @abstractmethod
    async def get_index_template(self, name: str, ignore: list[int] | None = None) -> dict:
        """Retrieve an index template."""

    @abstractmethod
    async def put_index_template(self, name: str, body: dict[str, Any]) -> dict:
        """Update an index template."""

    @abstractmethod
    async def get_datastream(self, datastream: str) -> dict:
        """Retrieve datastreams."""

    @abstractmethod
    async def rollover_datastream(self, datastream: str) -> dict:
        """Rollover a datastream."""

    @abstractmethod
    async def bulk(self, actions: AsyncGenerator[dict[str, Any], Any]) -> None:
        """Perform a bulk operation."""

    @abstractmethod
    async def esql_query(self, query: str, params: list[Any]) -> EsqlResponse:
        """Run an ES|QL query, binding `params` to its `?` placeholders."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the gateway."""

    # Helper methods

    def _validate_cluster_info(self, cluster_info: dict) -> None:
        """Check that server metadata can be used for capability and version checks."""
        version = cluster_info.get("version")
        if not isinstance(version, dict):
            raise UnsupportedServer("The endpoint does not report supported Elasticsearch server metadata.")

        build_flavor = version.get("build_flavor")
        if not isinstance(build_flavor, str) or not build_flavor.strip():
            raise UnsupportedServer("The endpoint does not report supported Elasticsearch server metadata.")

        version_number = version.get("number")
        if not isinstance(version_number, str):
            raise UnsupportedServer("The endpoint does not report an Elasticsearch version number.")

        version_number_parts = version_number.split(".")
        if len(version_number_parts) < 2 or not all(part.isdecimal() for part in version_number_parts[:2]):
            raise UnsupportedServer("The endpoint reports an invalid Elasticsearch version number.")

    def _is_supported_version(self, cluster_info: dict) -> bool:
        """Check whether validated server metadata describes a supported version."""
        return self._is_serverless(cluster_info) or self._meets_minimum_version(
            cluster_info, ELASTIC_MINIMUM_VERSION
        )

    def _is_serverless(self, cluster_info: dict) -> bool:
        """Check whether validated server metadata describes a serverless instance."""
        return bool(cluster_info["version"]["build_flavor"] == "serverless")

    def _meets_minimum_version(self, cluster_info: dict, minimum_version: tuple[int, int]) -> bool:
        """Check whether a validated Elasticsearch version meets the minimum."""
        version_number_parts = cluster_info["version"]["number"].split(".")

        current_major = int(version_number_parts[0])
        current_minor = int(version_number_parts[1])

        minimum_major = minimum_version[0]
        minimum_minor = minimum_version[1]

        return (
            current_major > minimum_major or current_major == minimum_major and current_minor >= minimum_minor
        )

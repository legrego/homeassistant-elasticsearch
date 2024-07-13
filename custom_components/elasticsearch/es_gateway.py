"""Encapsulates Elasticsearch operations."""

from __future__ import annotations  # noqa: I001

from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING


from custom_components.elasticsearch.errors import InsufficientPrivileges, UnsupportedVersion
from custom_components.elasticsearch.const import ES_CHECK_PERMISSIONS_DATASTREAM, ELASTIC_MINIMUM_VERSION

from .logger import LOGGER as BASE_LOGGER
from .logger import log_enter_exit_debug

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from logging import Logger
    from typing import Any

    from elasticsearch7._async.client import AsyncElasticsearch as AsyncElasticsearch7
    from elasticsearch8._async.client import AsyncElasticsearch as AsyncElasticsearch8


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
    minimum_privileges: MappingProxyType[str, Any] | None = None

    @abstractmethod
    def to_client(self) -> AsyncElasticsearch7 | AsyncElasticsearch8:
        """Return an Elasticsearch client."""


class ElasticsearchGateway(ABC):
    """Encapsulates Elasticsearch operations."""

    _logger = BASE_LOGGER

    def __init__(
        self,
        gateway_settings: GatewaySettings,
        log: Logger = BASE_LOGGER,
    ) -> None:
        """Non-I/O bound init."""

        self._logger: Logger = log

    @log_enter_exit_debug
    async def async_init(self) -> None:
        """I/O bound init."""

        # Test the connection
        await self.info()

        # Minimum version check
        if not await self._is_supported_version():
            msg = f"Elasticsearch version is not supported. Minimum version: {ELASTIC_MINIMUM_VERSION}"
            raise UnsupportedVersion(msg)

        # Check minimum privileges
        if not await self._has_required_privileges():
            raise InsufficientPrivileges

    @property
    @abstractmethod
    def client(self) -> AsyncElasticsearch7 | AsyncElasticsearch8:
        """Return the underlying ES Client."""

    @property
    @abstractmethod
    def settings(self) -> GatewaySettings:
        """Return the settings."""

    @property
    def url(self) -> str:
        """Return the Home Assistant instance."""
        return self.settings.url

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
    ) -> None:
        """Initialize the gateway and then stop it."""

    @abstractmethod
    async def info(self) -> dict:
        """Retrieve info about the connected elasticsearch cluster."""

    @abstractmethod
    async def ping(self) -> bool:
        """Pings the connected elasticsearch cluster."""

    @abstractmethod
    async def has_privileges(self, privileges) -> dict:
        """Check if the user has the specified privileges."""

    @abstractmethod
    async def get_index_template(self, name, ignore=None) -> dict:
        """Retrieve an index template."""

    @abstractmethod
    async def put_index_template(self, name, body) -> dict:
        """Update an index template."""

    @abstractmethod
    async def get_datastreams(self, datastream: str) -> dict:
        """Retrieve datastreams."""

    @abstractmethod
    async def rollover_datastream(self, datastream: str) -> dict:
        """Rollover an index."""

    @abstractmethod
    async def bulk(self, actions: AsyncGenerator[dict[str, Any], Any]) -> None:
        """Perform a bulk operation."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the gateway."""

    # Helper methods

    async def _is_supported_version(self) -> bool:
        """Check if the Elasticsearch version is supported."""
        info: dict = await self.info()

        return self._is_serverless(info) or self._meets_minimum_version(info, ELASTIC_MINIMUM_VERSION)

    def _is_serverless(self, cluster_info: dict) -> bool:
        """Check if the Elasticsearch instance is serverless."""

        # Build flavor is missing in 7.x versions
        if "build_flavor" not in cluster_info["version"]:
            return False

        return cluster_info["version"]["build_flavor"] == "serverless"

    def _meets_minimum_version(self, cluster_info: dict, minimum_version: tuple[int, int]) -> bool:
        """Check if the Elasticsearch version is supported."""

        version_number_parts = cluster_info["version"]["number"].split(".")

        current_major = int(version_number_parts[0])
        current_minor = int(version_number_parts[1])

        minimum_major = minimum_version[0]
        minimum_minor = minimum_version[1]

        return (
            current_major > minimum_major or current_major == minimum_major and current_minor >= minimum_minor
        )

    async def _has_required_privileges(self) -> bool:
        """Check if the user has the required privileges."""
        response = await self.has_privileges(privileges=self.settings.minimum_privileges)

        return response.get("has_all_requested", False)

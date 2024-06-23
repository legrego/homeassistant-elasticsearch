"""Encapsulates Elasticsearch operations."""

from __future__ import annotations  # noqa: I001

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING


from custom_components.elasticsearch.errors import (
    InsufficientPrivileges,
)

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
    minimum_version: tuple[int, int] | None = None
    minimum_privileges: dict[str, Any] | None = None

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

        # Check minimum privileges
        if not await self._has_required_privileges(self.settings.minimum_privileges):
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
        ca_certs: str | None = None,
        request_timeout: int = 30,
        minimum_privileges: dict[str, Any] = {},
        log: Logger = BASE_LOGGER,
    ) -> None:
        """Initialize the gateway and then stop it."""

    # @classmethod
    # async def test_prospective_settings(
    #     cls,
    #     hass: HomeAssistant,
    #     url: str,
    #     username: str | None = None,
    #     password: str | None = None,
    #     api_key: str | None = None,
    #     verify_certs: bool = True,
    #     ca_certs: str | None = None,
    #     request_timeout: int = 30,
    #     minimum_privileges: dict[str, Any] = ES_CHECK_PERMISSIONS_DATASTREAM,
    #     logger: Logger = BASE_LOGGER,
    # ) -> bool:
    #     """Test the settings provided by the user and make sure they work."""
    #     gateway: ElasticsearchGateway | None = None

    #     try:
    #         gateway = cls(
    #             hass=hass,
    #             url=url,
    #             username=username,
    #             password=password,
    #             api_key=api_key,
    #             verify_certs=verify_certs,
    #             ca_certs=ca_certs,
    #             request_timeout=request_timeout,
    #             minimum_privileges=minimum_privileges,
    #         )

    #         await gateway.async_init()
    #     except ESIntegrationException:
    #         raise
    #     except Exception:
    #         logger.exception("Unknown error testing settings.")
    #         cls.convert_es_error()

    #     return True

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
    async def bulk(self, actions: AsyncGenerator[dict[str, Any], Any]) -> None:
        """Perform a bulk operation."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the gateway."""

    # Helper methods

    async def _has_required_privileges(self, privileges) -> bool:
        """Check if the user has the required privileges."""
        response = await self.has_privileges(privileges=privileges)

        return response.get("has_all_requested", False)

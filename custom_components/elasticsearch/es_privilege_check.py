"""Perform privilege checks to ensure credentials have all necessery permissions."""

import json
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ALIAS, CONF_API_KEY, CONF_USERNAME

from custom_components.elasticsearch.const import (
    CONF_INDEX_FORMAT,
    CONF_INDEX_MODE,
    INDEX_MODE_DATASTREAM,
    INDEX_MODE_LEGACY,
    VERSION_SUFFIX,
)
from custom_components.elasticsearch.errors import (
    InsufficientPrivileges,
    convert_es_error,
)
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from custom_components.elasticsearch.logger import LOGGER


@dataclass
class PrivilegeCheckResult:
    """Results of the privilege check."""

    username: str
    has_all_requested: bool
    missing_cluster_privileges: list[str]
    missing_index_privileges: [str, list[bool]]


class ESPrivilegeCheck:
    """Privilege check encapsulation."""

    def __init__(self, gateway: ElasticsearchGateway, config_entry: ConfigEntry):
        """Initialize Privilege Checker."""
        self.es_gateway = gateway

        self.username = config_entry.data.get(CONF_USERNAME)
        self.api_key = config_entry.data.get(CONF_API_KEY)
        self.index_mode = config_entry.data.get(CONF_INDEX_MODE)

        if self.index_mode is INDEX_MODE_LEGACY:
            self.index_format = config_entry.options.get(CONF_INDEX_FORMAT)
            self.index_alias = config_entry.options.get(CONF_ALIAS) + VERSION_SUFFIX

    async def enforce_privileges(self):
        """Ensure client is configured with properly authorized credentials."""
        LOGGER.debug("Starting privilege enforcement")

        if self.username is None and self.api_key is None:
            return

        LOGGER.debug("Checking privileges of %s", self.username or "API key")

        result = await self.check_privileges()

        if not result.has_all_requested:
            LOGGER.debug("Required privileges are missing.")
            raise InsufficientPrivileges()

    async def check_privileges(self) -> PrivilegeCheckResult:
        """Determine client privileges."""
        from elasticsearch7 import ElasticsearchException

        required_cluster_privileges = [
            "manage_index_templates",
            "manage_ilm",
            "monitor",
        ]

        # if index_mode is datastream, we only need to check for datastream privileges
        if self.index_mode == INDEX_MODE_DATASTREAM:
            required_index_privileges = [
                {
                    "names": [
                        "metrics-homeassistant.*",
                    ],
                    "privileges": ["manage", "index", "create_index", "create"],
                }
            ]
        else:
            required_index_privileges = [
                {
                    "names": [
                        f"{self.index_format}*",
                        f"{self.index_alias}-*",
                        "all-hass-events",
                    ],
                    "privileges": ["manage", "index", "create_index", "create"],
                }
            ]

        try:
            LOGGER.debug("Privilege check starting")
            es_client = self.es_gateway.get_client()
            privilege_response = await es_client.security.has_privileges(
                body={
                    "cluster": required_cluster_privileges,
                    "index": required_index_privileges,
                }
            )
            LOGGER.debug(
                "Received privilege check response: %s", json.dumps(privilege_response)
            )
            return self._create_result(privilege_response)
        except ElasticsearchException as err:
            LOGGER.exception("Error performing privilege check: %s", err)
            raise convert_es_error("Error performing privilege check", err)

    def _create_result(self, privilege_response) -> PrivilegeCheckResult:
        """Create privilege check result from raw ES response."""

        username = privilege_response["username"]
        has_all_requested = privilege_response["has_all_requested"]

        missing_cluster_privileges = []
        missing_index_privileges = []

        cluster_privileges = privilege_response["cluster"]
        missing_cluster_privileges = [
            cp for cp in cluster_privileges if not cluster_privileges[cp]
        ]

        index_privileges = privilege_response["index"]
        missing_index_privileges = {}
        for index in index_privileges:
            missing = [
                ip for ip in index_privileges[index] if not index_privileges[index][ip]
            ]
            if len(missing) > 0:
                missing_index_privileges[index] = missing

        return PrivilegeCheckResult(
            username,
            has_all_requested,
            missing_cluster_privileges,
            missing_index_privileges,
        )

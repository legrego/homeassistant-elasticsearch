"""Encapsulates component configuration."""

# Configuration constants
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ALIAS,
    CONF_API_KEY,
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)

from custom_components.elasticsearch.const import (
    CONF_EXCLUDED_DOMAINS,
    CONF_EXCLUDED_ENTITIES,
    CONF_ILM_DELETE_AFTER,
    CONF_ILM_ENABLED,
    CONF_ILM_MAX_SIZE,
    CONF_ILM_POLICY_NAME,
    CONF_INCLUDED_DOMAINS,
    CONF_INCLUDED_ENTITIES,
    CONF_INDEX_FORMAT,
    CONF_PUBLISH_ENABLED,
    CONF_PUBLISH_FREQUENCY,
    CONF_PUBLISH_MODE,
    CONF_SSL_CA_PATH,
    ONE_MINUTE,
    PUBLISH_MODE_ANY_CHANGES,
)
from custom_components.elasticsearch.utils import get_merged_config

# Default configuration values
DEFAULT_URL = "http://localhost:9200"
DEFAULT_ALIAS = "active-hass-index"
DEFAULT_INDEX_FORMAT = "hass-events"
DEFAULT_PUBLISH_ENABLED = True
DEFAULT_PUBLISH_FREQUENCY = ONE_MINUTE
DEFAULT_PUBLISH_MODE = PUBLISH_MODE_ANY_CHANGES
DEFAULT_VERIFY_SSL = True
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_ILM_ENABLED = True
DEFAULT_ILM_POLICY_NAME = "home-assistant"
DEFAULT_ILM_MAX_SIZE = "30gb"
DEFAULT_ILM_DELETE_AFTER = "365d"

class IntegrationConfig:
    """Configuration options for this integration."""

    def __init__(self, raw_config: dict) -> None:
        """Initialize class."""
        self._raw = raw_config

    @staticmethod
    def from_config_entry(entry: ConfigEntry):
        """Construct instance from a Config Entry."""
        return IntegrationConfig(get_merged_config(entry))

    @property
    def url(self) -> str:
        """URL of the Elasticsearch cluster.

        Default: http://localhost:9200.
        """
        return self._raw.get(CONF_URL, DEFAULT_URL)

    @property
    def api_key(self) -> str | None:
        """API Key to authenticate to the cluster. Cannot be combined with username/password.

        Default: None.
        """
        return self._raw.get(CONF_API_KEY)

    @property
    def username(self) -> str | None:
        """Username for basic authentication. Must be combined with password, Cannot be combined with api_key.

        Default: None.
        """
        return self._raw.get(CONF_USERNAME)

    @property
    def password(self) -> str | None:
        """Password for basic authentication. Must be combined with username, Cannot be combined with api_key."""
        return self._raw.get(CONF_PASSWORD)

    @property
    def timeout(self) -> int:
        """Connection timeout, in seconds, for all Elasticsearch operations.

        Default: 30.
        """
        return self._raw.get(CONF_TIMEOUT, DEFAULT_TIMEOUT_SECONDS)

    @property
    def verify_ssl(self) -> bool:
        """Determines if SSL certificates should be verified.

        Default: True.
        """
        return self._raw.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)

    @property
    def ssl_ca_path(self) -> str | None:
        """Path to custom CA certificates, if required.

        Default: None.
        """
        return self._raw.get(CONF_SSL_CA_PATH, None)

    @property
    def publish_enabled(self) -> bool:
        """Determines if states changes should be published to Elasticsearch.

        Default: True.
        """
        return self._raw.get(CONF_PUBLISH_ENABLED, DEFAULT_PUBLISH_ENABLED)

    @property
    def publish_frequency(self) -> int:
        """Determines how frequently, in seconds, state changes should be published.

        Default: 30.
        """
        return self._raw.get(CONF_PUBLISH_FREQUENCY, DEFAULT_PUBLISH_FREQUENCY)

    @property
    def publish_mode(self) -> str:
        """Determines the publish mode.

        Default: 'Any changes'.
        """
        return self._raw.get(CONF_PUBLISH_MODE, DEFAULT_PUBLISH_MODE)

    @property
    def alias(self) -> str:
        """Determines the alias of the active index.

        Default: 'active-hass-index'.
        """
        return self._raw.get(CONF_ALIAS, DEFAULT_ALIAS)

    @property
    def index_format(self) -> str:
        """Gets the index format.

        Default: 'hass-events'.
        """
        return self._raw.get(CONF_INDEX_FORMAT, DEFAULT_INDEX_FORMAT)

    @property
    def excluded_domains(self) -> list[str]:
        """Get the list of domains which should be excluded from publishing.

        Default: [].
        """
        return self._raw.get(CONF_EXCLUDED_DOMAINS, [])

    @property
    def excluded_entities(self) -> list[str]:
        """Get the list of entities which should be excluded from publishing.

        Default: [].
        """
        return self._raw.get(CONF_EXCLUDED_ENTITIES, [])

    @property
    def included_domains(self) -> list[str]:
        """Get the list of domains which should be included for publishing.

        Leaving this unset will include all domains.
        Default: [].
        """
        return self._raw.get(CONF_INCLUDED_DOMAINS, [])

    @property
    def included_entities(self) -> list[str]:
        """Get the list of entities which should be included for publishing.

        Leaving this unset will include all entities.
        Default: []
        """
        return self._raw.get(CONF_INCLUDED_ENTITIES, [])

    @property
    def ilm_enabled(self) -> bool:
        """Determines if Index Lifecycle Management ("ILM") features should be enabled.

        Default: True.
        """
        return self._raw.get(CONF_ILM_ENABLED, DEFAULT_ILM_ENABLED)

    @property
    def ilm_policy_name(self) -> str:
        """Get the Index Lifecycle Management ("ILM") policy name.

        Default: 'home-assistant'.
        """
        return self._raw.get(CONF_ILM_POLICY_NAME, DEFAULT_ILM_POLICY_NAME)

    @property
    def ilm_max_size(self) -> str:
        """Get the max size of the index before it should be rolled over.

        Default: '30gb'.
        """
        return self._raw.get(CONF_ILM_MAX_SIZE, DEFAULT_ILM_MAX_SIZE)

    @property
    def ilm_delete_after(self) -> str:
        """Determines when to delete documents.

        Default: '365d'.
        """
        return self._raw.get(CONF_ILM_DELETE_AFTER, DEFAULT_ILM_DELETE_AFTER)



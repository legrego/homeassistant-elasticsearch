"""Class for the Elastic integration config configuration objects."""

from dataclasses import dataclass

import voluptuous as vol
from elasticsearch.const import ONE_MINUTE, StateChangeType
from voluptuous import All, Exclusive, Inclusive, Optional, Required, Schema

DEFAULT_URL = "http://localhost:9200"

DEFAULT_PUBLISH_FREQUENCY = ONE_MINUTE
DEFAULT_POLLING_FREQUENCY = ONE_MINUTE

DEFAULT_CHANGE_DETECTION_ENABLED = True
DEFAULT_CHANGE_DETECTION_TYPE = [StateChangeType.STATE.value, StateChangeType.ATTRIBUTE.value]
DEFAULT_VERIFY_SSL = True
DEFAULT_TIMEOUT_SECONDS = 30


class Authentication:
    """Authentication for the Elastic integration."""


@dataclass
class ApiAuth(Authentication):
    """API Key authentication for the Elastic integration."""

    api_key: str | None


@dataclass
class BasicAuth(Authentication):
    """Basic authentication for the Elastic integration."""

    username: str | None
    password: str | None


@dataclass
class NoAuth(Authentication):
    """No authentication for the Elastic integration."""


class ElasticIntegrationConfig:
    """Data and options for the Elastic integration."""

    @dataclass
    class Data:
        """Data for the Elastic integration."""

        url: str
        timeout: int
        verify_ssl: bool
        ssl_ca_path: str | None
        authentication: Authentication

        def get_url_schema(self) -> dict[Required, type[str]]:
            """Get the URL schema."""
            return {vol.Required(self.url, default="http://localhost:9200"): str}

        def _get_validation_schema(self) -> Schema:
            """Validate the config entry."""

            return Schema(
                required=True,
                schema=All(
                    {
                        Required("url", default="test"): str,
                        Required("timeout"): int,
                        Required("verify_ssl"): bool,
                        Optional("ssl_ca_path"): str,
                        Optional("api_key"): str,
                        Optional("username"): str,
                        Optional("password"): str,
                    },
                    {
                        Inclusive("username", "password", msg="Both Username and Password must be set"),
                        Exclusive(
                            "api_key",
                            "username",
                            msg="Found API Key and Username, do not mix api key and username/password authentication",
                        ),
                        Exclusive(
                            "api_key",
                            "password",
                            msg="Found API Key and Password, do not mix api key and username/password authentication",
                        ),
                    },
                ),
            )

        def _auth_settings_to_object(self, auth_settings: dict) -> Authentication:
            """Create authentication object from settings."""
            if auth_settings.get("api_key") is not None:
                return ApiAuth(api_key=auth_settings["api_key"])

            if auth_settings.get("username") is not None and auth_settings.get("password") is not None:
                return BasicAuth(username=auth_settings["username"], password=auth_settings["password"])

            return NoAuth()

        def from_config_entry(self, config_entry) -> "ElasticIntegrationConfig.Data":
            """Create data from config entry."""
            data = config_entry.data
            validation_schema = self._get_validation_schema()
            validated_data = validation_schema(data)
            validated_data["authentication"] = self._auth_settings_to_object(validated_data)
            return ElasticIntegrationConfig.Data(**validated_data)

        def get_authentication_type(self) -> str:
            """Get the authentication type."""
            return self.authentication.__class__.__name__

        def get(self, key: str, default: str | None = None) -> str | None:
            """Get value from data."""
            return getattr(self, key, default)

    @dataclass
    class Options:
        """Options for the Elastic integration."""

        change_detection_enabled: bool
        change_detection_type: list[str]
        polling_frequency: int
        publish_frequency: int
        excluded_domains: list[str]
        excluded_entities: list[str]
        included_domains: list[str]
        included_entities: list[str]

        def get(self, key: str, default: str | None = None) -> str | None:
            """Get value from data."""
            return getattr(self, key, default)

"""Config flow for Elastic."""

from typing import Any

import probatio
from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, ConfigEntry, ConfigFlowResult
from homeassistant.const import (
    CONF_API_KEY,
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    BooleanSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    TargetSelector,
    TargetSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from custom_components.elasticsearch.const import (
    CONF_AUTHENTICATION_TYPE,
    CONF_CHANGE_DETECTION_TYPE,
    CONF_EXCLUDE_TARGETS,
    CONF_INCLUDE_TARGETS,
    CONF_POLLING_FREQUENCY,
    CONF_PUBLISH_ENABLED,
    CONF_PUBLISH_FREQUENCY,
    CONF_PUBLISH_QUERY_SENSORS,
    CONF_SSL_CA_PATH,
    CONF_SSL_VERIFY_HOSTNAME,
    CONF_TAGS,
    CONF_TARGETS_TO_EXCLUDE,
    CONF_TARGETS_TO_INCLUDE,
    ES_CHECK_PERMISSIONS_QUERY,
    ONE_MINUTE,
    StateChangeType,
)
from custom_components.elasticsearch.const import DOMAIN as ELASTIC_DOMAIN
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    CannotConnect,
    InsufficientPrivileges,
    InvalidCACertificate,
    UnsupportedServer,
    UnsupportedVersion,
    UntrustedCertificate,
)
from custom_components.elasticsearch.es_gateway_8 import Elasticsearch8Gateway

from .logger import LOGGER as BASE_LOGGER
from .logger import (
    async_log_enter_exit_debug,
    async_log_enter_exit_info,
    log_enter_exit_debug,
)
from .sensor_config_flow import QuerySensorSubentryFlow

CONFIG_TO_REDACT = {CONF_API_KEY, CONF_PASSWORD, CONF_USERNAME}

# The settings that reconfigure replaces, everything else in the entry's data is kept
CONNECTION_SETTINGS = {
    CONF_URL,
    CONF_VERIFY_SSL,
    CONF_SSL_VERIFY_HOSTNAME,
    CONF_SSL_CA_PATH,
    CONF_PUBLISH_ENABLED,
}

# Data Flow values
SCHEMA_URL: dict[Any, Any] = {"schema": CONF_URL, "default": "https://localhost:9200"}
SCHEMA_AUTHENTICATION_TYPE: dict[Any, Any] = {
    "schema": CONF_AUTHENTICATION_TYPE,
    "default": CONF_API_KEY,
}
SCHEMA_USERNAME: dict[str, Any] = {"schema": CONF_USERNAME, "default": None}
SCHEMA_PASSWORD: dict[str, Any] = {"schema": CONF_PASSWORD, "default": None}
SCHEMA_VERIFY_SSL: dict[str, Any] = {"schema": CONF_VERIFY_SSL, "default": True}
SCHEMA_SSL_VERIFY_HOSTNAME: dict[str, Any] = {"schema": CONF_SSL_VERIFY_HOSTNAME, "default": True}
SCHEMA_SSL_CA_PATH: dict[str, Any] = {"schema": CONF_SSL_CA_PATH}
SCHEMA_API_KEY: dict[str, Any] = {"schema": CONF_API_KEY, "default": None}
SCHEMA_TIMEOUT: dict[str, Any] = {"schema": CONF_TIMEOUT, "default": 30}


TRANSLATION_KEY_STATE = "state"
TRANSLATION_KEY_ATTRIBUTE = "attribute"
TRANSLATION_KEY_API_KEY = "api_key"
TRANSLATION_KEY_BASIC_AUTH = "basic_auth"


class ElasticFlowHandler(config_entries.ConfigFlow, domain=ELASTIC_DOMAIN):
    """Handle an Elastic config flow."""

    VERSION = 7
    GATEWAY = Elasticsearch8Gateway

    def __init__(self) -> None:
        """Initialize the Elastic flow."""
        self._prospective_config: dict[str, Any] = self.init_data or {}
        self._cluster_uuid: str | None = None
        self._certificate_input: dict[str, Any] = {}

    @callback
    def _async_update_reload_and_abort(self, entry: ConfigEntry, **kwargs: Any) -> ConfigFlowResult:
        """Use the entry listener when loaded, or explicitly retry an unloaded entry."""
        result = self.async_update_and_abort(entry, **kwargs)
        if not entry.update_listeners:
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
        return result

    def _privilege_settings(self) -> dict[str, Any]:
        """Validate only read-side privileges when publishing is disabled."""
        if not self._prospective_config.get(CONF_PUBLISH_ENABLED, True):
            return {"minimum_privileges": ES_CHECK_PERMISSIONS_QUERY}
        return {}

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[config_entries.ConfigSubentryFlow]]:
        """Allow independently configured query sensors."""
        return {"query_sensor": QuerySensorSubentryFlow}

    @async_log_enter_exit_info
    async def async_step_user(
        self, user_input: dict | None = None, errors: dict | None = None
    ) -> ConfigFlowResult:  # noqa: ARG002
        """Handle a flow initialized by the user. This is the first step in the flow.

        We will gather the url of the elasticsearch cluster and the desired authentication method.
        """

        if errors is not None:
            BASE_LOGGER.debug("async_step_user errors: %s", errors)

        if user_input is not None:
            # If the URL has an https schema, test the connection and see if we get an untrusted certificate error
            prospective_settings: dict = {CONF_URL: user_input.get(CONF_URL)}
            self._prospective_config.update(user_input)

            try:
                self._cluster_uuid = await Elasticsearch8Gateway.async_init_then_stop(
                    **prospective_settings, **self._privilege_settings()
                )

            except UntrustedCertificate:
                return await self.async_step_certificate_issues()
            except CannotConnect:
                BASE_LOGGER.debug("Cannot connect", exc_info=True)
                return await self.async_step_user(errors={CONF_URL: "cannot_connect"})
            except AuthenticationRequired:
                return await self.async_step_authentication_issues()
            except UnsupportedServer:
                BASE_LOGGER.debug("Unsupported server", exc_info=True)
                return await self.async_step_user(errors={"base": "unsupported_server"})
            except UnsupportedVersion:
                BASE_LOGGER.debug("Unsupported version", exc_info=True)
                return await self.async_step_user(errors={"base": "unsupported_version"})
            except Exception:  # noqa: BLE001
                BASE_LOGGER.exception("Unexpected error connecting to Elasticsearch")
                return await self.async_step_user(errors={"base": "unknown"})

            return await self.async_step_complete()

        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema(
                {
                    probatio.Optional(
                        CONF_PUBLISH_ENABLED, description={"suggested_value": True}
                    ): BooleanSelector(),
                    probatio.Required(**SCHEMA_URL): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.URL,
                        )
                    ),
                },
            ),
            errors=errors,
        )

    @async_log_enter_exit_info
    async def async_step_certificate_issues(
        self, user_input: dict | None = None, errors: dict | None = None
    ) -> ConfigFlowResult:
        """Check to see if we need to ask the user for more specific SSL settings."""

        if errors is not None:
            BASE_LOGGER.debug("async_step_certificate_issues errors: %s", errors)

        if user_input is not None:
            self._certificate_input = dict(user_input)
            try:
                self._cluster_uuid = await Elasticsearch8Gateway.async_init_then_stop(
                    url=self._prospective_config[CONF_URL],
                    **self._privilege_settings(),
                    verify_certs=user_input.get(CONF_VERIFY_SSL, True),
                    ca_certs=user_input.get(CONF_SSL_CA_PATH),
                    verify_hostname=user_input.get(CONF_SSL_VERIFY_HOSTNAME, True),
                )

            except UntrustedCertificate:
                BASE_LOGGER.debug("Certificate issue", exc_info=True)
                return await self.async_step_certificate_issues(errors={"base": "untrusted_certificate"})

            except InvalidCACertificate:
                BASE_LOGGER.debug("Invalid certificate authority", exc_info=True)
                return await self.async_step_certificate_issues(errors={"base": "invalid_ca_certificate"})

            except CannotConnect:
                BASE_LOGGER.debug("Cannot connect", exc_info=True)

                # Reauth keeps the entry's URL, so the URL form has nothing to offer
                if self.source == SOURCE_REAUTH:
                    return await self.async_step_certificate_issues(errors={"base": "cannot_connect"})

                return await self.async_step_user(errors={"base": "cannot_connect"})

            except AuthenticationRequired:
                self._update_certificate_config(user_input)
                return await self.async_step_authentication_issues()

            except UnsupportedServer:
                BASE_LOGGER.debug("Unsupported server", exc_info=True)
                return await self.async_step_certificate_issues(errors={"base": "unsupported_server"})

            except UnsupportedVersion:
                BASE_LOGGER.debug("Unsupported version", exc_info=True)
                return await self.async_step_certificate_issues(errors={"base": "unsupported_version"})

            except Exception:  # noqa: BLE001
                BASE_LOGGER.exception("Unexpected error connecting to Elasticsearch")
                return await self.async_step_certificate_issues(errors={"base": "unknown"})

            # If we get here, we have a valid connection, so we can complete our flow
            self._update_certificate_config(user_input)
            return await self.async_step_complete()

        return self.async_show_form(
            step_id="certificate_issues",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(**SCHEMA_VERIFY_SSL): BooleanSelector(
                            BooleanSelectorConfig(),
                        ),
                        probatio.Required(**SCHEMA_SSL_VERIFY_HOSTNAME): BooleanSelector(
                            BooleanSelectorConfig(),
                        ),
                        probatio.Optional(**SCHEMA_SSL_CA_PATH): TextSelector(
                            TextSelectorConfig(
                                type=TextSelectorType.TEXT,
                            )
                        ),
                    },
                ),
                self._certificate_input or self._prospective_config,
            ),
            errors=errors,
        )

    def _update_certificate_config(self, user_input: dict[str, Any]) -> None:
        """Save TLS settings, removing a CA path cleared from the optional field."""
        self._prospective_config.pop(CONF_SSL_CA_PATH, None)
        self._prospective_config.update(user_input)

    @async_log_enter_exit_info
    async def async_step_authentication_issues(self, user_input: dict | None = None) -> ConfigFlowResult:
        """We require Authentication information to connect to Elasticsearch."""

        # Reauth updates the credentials the entry already has, it doesn't add another kind
        if self.source == SOURCE_REAUTH:
            return await self._async_step_entry_credentials()

        if user_input is not None:
            if user_input[CONF_AUTHENTICATION_TYPE] == TRANSLATION_KEY_BASIC_AUTH:
                return await self.async_step_basic_auth()

            return await self.async_step_api_key()

        # Show a form where we ask the user if they want to use API Key or Basic Auth
        return self.async_show_form(
            step_id="authentication_issues",
            data_schema=probatio.Schema(
                {
                    probatio.Required(**SCHEMA_AUTHENTICATION_TYPE): SelectSelector(
                        SelectSelectorConfig(
                            translation_key="authentication_issues",
                            options=[TRANSLATION_KEY_API_KEY, TRANSLATION_KEY_BASIC_AUTH],
                        )
                    ),
                }
            ),
        )

    @async_log_enter_exit_info
    async def async_step_basic_auth(
        self, user_input: dict | None = None, errors: dict | None = None
    ) -> ConfigFlowResult:
        """Prompt the user for the settings required to use Basic Authentication against the Elasticsearch cluster."""

        if errors is not None:
            BASE_LOGGER.debug("async_step_basic_auth errors: %s", errors)

        if user_input is not None:
            try:
                self._cluster_uuid = await Elasticsearch8Gateway.async_init_then_stop(
                    url=self._prospective_config[CONF_URL],
                    **self._privilege_settings(),
                    username=user_input.get(CONF_USERNAME),
                    password=user_input.get(CONF_PASSWORD),
                    verify_certs=self._prospective_config.get(CONF_VERIFY_SSL, True),
                    verify_hostname=self._prospective_config.get(CONF_SSL_VERIFY_HOSTNAME, True),
                    ca_certs=self._prospective_config.get(CONF_SSL_CA_PATH),
                )
            except InsufficientPrivileges:
                BASE_LOGGER.debug("Insufficient Privileges", exc_info=True)
                return await self.async_step_basic_auth(errors={"base": "insufficient_privileges"})
            except AuthenticationRequired:
                BASE_LOGGER.debug("Invalid basic authentication", exc_info=True)
                return await self.async_step_basic_auth(errors={"base": "invalid_basic_auth"})
            except InvalidCACertificate:
                BASE_LOGGER.debug("Invalid certificate authority", exc_info=True)
                return await self._async_step_tls_settings(errors={"base": "invalid_ca_certificate"})
            except CannotConnect:
                BASE_LOGGER.debug("Cannot connect", exc_info=True)
                return await self.async_step_basic_auth(errors={"base": "cannot_connect"})
            except UnsupportedServer:
                BASE_LOGGER.debug("Unsupported server", exc_info=True)
                return await self.async_step_basic_auth(errors={"base": "unsupported_server"})
            except UnsupportedVersion:
                BASE_LOGGER.debug("Unsupported version", exc_info=True)
                return await self.async_step_basic_auth(errors={"base": "unsupported_version"})
            except Exception:  # noqa: BLE001
                BASE_LOGGER.exception("Unexpected error connecting to Elasticsearch")
                return await self.async_step_basic_auth(errors={"base": "unknown"})

            # We are authenticated, update settings and complete flow
            self._prospective_config.update(user_input)
            return await self.async_step_complete()

        return self.async_show_form(
            step_id="basic_auth",
            data_schema=probatio.Schema(
                {
                    probatio.Required(**SCHEMA_USERNAME): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.TEXT,
                        )
                    ),
                    probatio.Required(**SCHEMA_PASSWORD): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD,
                        )
                    ),
                },
            ),
            errors=errors,
        )

    @async_log_enter_exit_info
    async def async_step_api_key(
        self, user_input: dict | None = None, errors: dict | None = None
    ) -> ConfigFlowResult:
        """Prompt the user for the settings required to use API Key Authentication against the Elasticsearch cluster."""

        if errors is not None:
            BASE_LOGGER.debug("async_step_api_key errors: %s", errors)

        if user_input is not None:
            try:
                self._cluster_uuid = await Elasticsearch8Gateway.async_init_then_stop(
                    url=self._prospective_config[CONF_URL],
                    **self._privilege_settings(),
                    api_key=user_input.get(CONF_API_KEY),
                    verify_certs=self._prospective_config.get(CONF_VERIFY_SSL, True),
                    verify_hostname=self._prospective_config.get(CONF_SSL_VERIFY_HOSTNAME, True),
                    ca_certs=self._prospective_config.get(CONF_SSL_CA_PATH),
                )
            except InsufficientPrivileges:
                BASE_LOGGER.debug("Insufficient Privileges", exc_info=True)
                return await self.async_step_api_key(errors={"base": "insufficient_privileges"})
            except AuthenticationRequired:
                BASE_LOGGER.debug("Invalid API Key", exc_info=True)
                return await self.async_step_api_key(errors={"base": "invalid_api_key"})
            except InvalidCACertificate:
                BASE_LOGGER.debug("Invalid certificate authority", exc_info=True)
                return await self._async_step_tls_settings(errors={"base": "invalid_ca_certificate"})
            except CannotConnect:
                BASE_LOGGER.debug("Cannot connect", exc_info=True)
                return await self.async_step_api_key(errors={"base": "cannot_connect"})
            except UnsupportedServer:
                BASE_LOGGER.debug("Unsupported server", exc_info=True)
                return await self.async_step_api_key(errors={"base": "unsupported_server"})
            except UnsupportedVersion:
                BASE_LOGGER.debug("Unsupported version", exc_info=True)
                return await self.async_step_api_key(errors={"base": "unsupported_version"})
            except Exception:  # noqa: BLE001
                BASE_LOGGER.exception("Unexpected error connecting to Elasticsearch")
                return await self.async_step_api_key(errors={"base": "unknown"})

            # We are authenticated, update settings and complete flow
            self._prospective_config.update(user_input)
            return await self.async_step_complete()

        return self.async_show_form(
            step_id="api_key",
            data_schema=probatio.Schema(
                {
                    probatio.Required(**SCHEMA_API_KEY): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD,
                        )
                    ),
                },
            ),
            errors=errors,
        )

    @async_log_enter_exit_info
    async def async_step_complete(self) -> ConfigFlowResult:
        """Handle the completion of the flow."""
        default_options = ElasticOptionsFlowHandler.default_options

        # Save the verification settings the connection was tested with, so that
        # the entry never depends on a default
        self._prospective_config.setdefault(CONF_VERIFY_SSL, True)
        self._prospective_config.setdefault(CONF_SSL_VERIFY_HOSTNAME, True)

        if self.source == SOURCE_REAUTH:
            return self._async_update_reload_and_abort(
                self._get_reauth_entry(), data=self._prospective_config
            )

        if self.source == SOURCE_RECONFIGURE:
            return self._async_finish_reconfigure()

        await self.async_set_unique_id(self._cluster_uuid)
        self._abort_if_unique_id_configured()

        title: str = self._prospective_config[CONF_URL]

        return self.async_create_entry(title=title, data=self._prospective_config, options=default_options)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return ElasticOptionsFlowHandler(config_entry)

    async def async_step_reauth(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle reauthorization."""
        self._prospective_config = dict(self._get_reauth_entry().data)

        return await self._async_step_entry_credentials(user_input)

    async def _async_step_entry_credentials(
        self, user_input: dict | None = None, errors: dict | None = None
    ) -> ConfigFlowResult:
        """Continue with the authentication method that the entry being updated uses."""

        if self._prospective_config.get(CONF_USERNAME, None) is not None:
            return await self.async_step_basic_auth(user_input=user_input, errors=errors)
        if self._prospective_config.get(CONF_API_KEY, None) is not None:
            return await self.async_step_api_key(user_input=user_input, errors=errors)

        if self.source == SOURCE_REAUTH:
            return self.async_abort(reason="no_auth")

        # An entry reconfigured to a URL that needs credentials it doesn't have picks a method, as in setup
        return await self.async_step_authentication_issues()

    async def _async_step_tls_settings(self, errors: dict) -> ConfigFlowResult:
        """Return to the form that holds the TLS settings, to correct them."""

        if self.source == SOURCE_RECONFIGURE:
            return await self.async_step_reconfigure(errors=errors)

        return await self.async_step_certificate_issues(errors=errors)

    @async_log_enter_exit_info
    async def async_step_reconfigure(
        self, user_input: dict | None = None, errors: dict | None = None
    ) -> ConfigFlowResult:
        """Change the URL and TLS settings of an existing entry, keeping its credentials and options."""

        entry = self._get_reconfigure_entry()

        if errors is not None:
            BASE_LOGGER.debug("async_step_reconfigure errors: %s", errors)

        if user_input is not None:
            self._prospective_config = {
                key: value for key, value in entry.data.items() if key not in CONNECTION_SETTINGS
            }
            self._prospective_config.update(user_input)

            # The form leaves out a CA path that has been cleared
            if not self._prospective_config.get(CONF_SSL_CA_PATH):
                self._prospective_config.pop(CONF_SSL_CA_PATH, None)

            try:
                self._cluster_uuid = await Elasticsearch8Gateway.async_init_then_stop(
                    url=self._prospective_config[CONF_URL],
                    **self._privilege_settings(),
                    username=self._prospective_config.get(CONF_USERNAME),
                    password=self._prospective_config.get(CONF_PASSWORD),
                    api_key=self._prospective_config.get(CONF_API_KEY),
                    verify_certs=self._prospective_config.get(CONF_VERIFY_SSL, True),
                    verify_hostname=self._prospective_config.get(CONF_SSL_VERIFY_HOSTNAME, True),
                    ca_certs=self._prospective_config.get(CONF_SSL_CA_PATH),
                )
            except UntrustedCertificate:
                BASE_LOGGER.debug("Certificate issue", exc_info=True)
                return await self.async_step_reconfigure(errors={"base": "untrusted_certificate"})
            except InvalidCACertificate:
                BASE_LOGGER.debug("Invalid certificate authority", exc_info=True)
                return await self.async_step_reconfigure(errors={"base": "invalid_ca_certificate"})
            except CannotConnect:
                BASE_LOGGER.debug("Cannot connect", exc_info=True)
                return await self.async_step_reconfigure(errors={CONF_URL: "cannot_connect"})
            except InsufficientPrivileges:
                BASE_LOGGER.debug("Insufficient Privileges", exc_info=True)
                return await self._async_step_entry_credentials(errors={"base": "insufficient_privileges"})
            except AuthenticationRequired:
                BASE_LOGGER.debug("Credentials rejected", exc_info=True)
                rejected = (
                    "invalid_basic_auth"
                    if self._prospective_config.get(CONF_USERNAME) is not None
                    else "invalid_api_key"
                )
                return await self._async_step_entry_credentials(errors={"base": rejected})
            except UnsupportedServer:
                BASE_LOGGER.debug("Unsupported server", exc_info=True)
                return await self.async_step_reconfigure(errors={"base": "unsupported_server"})
            except UnsupportedVersion:
                BASE_LOGGER.debug("Unsupported version", exc_info=True)
                return await self.async_step_reconfigure(errors={"base": "unsupported_version"})
            except Exception:  # noqa: BLE001
                BASE_LOGGER.exception("Unexpected error connecting to Elasticsearch")
                return await self.async_step_reconfigure(errors={"base": "unknown"})

            return await self.async_step_complete()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Optional(
                            CONF_PUBLISH_ENABLED, description={"suggested_value": True}
                        ): BooleanSelector(),
                        probatio.Required(**SCHEMA_URL): TextSelector(
                            TextSelectorConfig(
                                type=TextSelectorType.URL,
                            )
                        ),
                        probatio.Required(**SCHEMA_VERIFY_SSL): BooleanSelector(
                            BooleanSelectorConfig(),
                        ),
                        probatio.Required(**SCHEMA_SSL_VERIFY_HOSTNAME): BooleanSelector(
                            BooleanSelectorConfig(),
                        ),
                        probatio.Optional(**SCHEMA_SSL_CA_PATH): TextSelector(
                            TextSelectorConfig(
                                type=TextSelectorType.TEXT,
                            )
                        ),
                    },
                ),
                self._prospective_config or entry.data,
            ),
            errors=errors,
        )

    @callback
    def _async_finish_reconfigure(self) -> ConfigFlowResult:
        """Save the new connection settings, unless they reach a different cluster."""

        entry = self._get_reconfigure_entry()

        # Moving to another cluster means adding it as a new entry
        if (
            entry.unique_id is not None
            and self._cluster_uuid is not None
            and entry.unique_id != self._cluster_uuid
        ):
            return self.async_abort(reason="wrong_cluster")

        # Entries are named after their URL, so follow a new URL unless the entry was renamed
        title = entry.title
        if title == entry.data.get(CONF_URL):
            title = self._prospective_config[CONF_URL]

        return self._async_update_reload_and_abort(entry, title=title, data=self._prospective_config)


class ElasticOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Elastic options."""

    default_options: dict[str, Any] = {
        CONF_PUBLISH_FREQUENCY: ONE_MINUTE,
        CONF_POLLING_FREQUENCY: ONE_MINUTE,
        CONF_CHANGE_DETECTION_TYPE: [StateChangeType.STATE.value, StateChangeType.ATTRIBUTE.value],
        CONF_INCLUDE_TARGETS: False,
        CONF_EXCLUDE_TARGETS: False,
        CONF_TARGETS_TO_INCLUDE: {},
        CONF_TARGETS_TO_EXCLUDE: {},
        CONF_TAGS: [],
    }

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize Elastic options flow."""
        self.options = dict(config_entry.options)

    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Manage the Elastic options."""

        return await self.async_step_options(user_input=user_input)

    @async_log_enter_exit_debug
    async def async_step_options(
        self,
        user_input: dict | None = None,
    ) -> ConfigFlowResult:
        """Publish Options."""
        if user_input is not None:
            self.options.update(user_input)

            # The form leaves out a target selector that has been cleared
            self.options[CONF_TARGETS_TO_INCLUDE] = user_input.get(CONF_TARGETS_TO_INCLUDE, {})
            self.options[CONF_TARGETS_TO_EXCLUDE] = user_input.get(CONF_TARGETS_TO_EXCLUDE, {})

            if not self.config_entry.update_listeners:
                self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)

            return self.async_create_entry(title="", data=self.options)

        return self.async_show_form(
            step_id="options",
            data_schema=self._build_options_schema(),
        )

    @log_enter_exit_debug
    def _build_options_schema(self) -> probatio.Schema:
        """Build the options schema."""

        from_options = self.config_entry.options.get

        SCHEMA_PUBLISH_FREQUENCY: dict[str, Any] = {
            "schema": CONF_PUBLISH_FREQUENCY,
            "default": from_options(CONF_PUBLISH_FREQUENCY),
        }
        SCHEMA_POLLING_FREQUENCY: dict[str, Any] = {
            "schema": CONF_POLLING_FREQUENCY,
            "default": from_options(CONF_POLLING_FREQUENCY),
        }

        SCHEMA_CHANGE_DETECTION_TYPE: dict[str, Any] = {
            "schema": CONF_CHANGE_DETECTION_TYPE,
            "default": from_options(CONF_CHANGE_DETECTION_TYPE),
        }
        SCHEMA_TAGS: dict[str, Any] = {
            "schema": CONF_TAGS,
            "default": from_options(CONF_TAGS),
        }
        SCHEMA_INCLUDE_TARGETS: dict[str, Any] = {
            "schema": CONF_INCLUDE_TARGETS,
            "default": from_options(CONF_INCLUDE_TARGETS),
        }
        SCHEMA_TARGETS_TO_INCLUDE: dict[str, Any] = {
            "schema": CONF_TARGETS_TO_INCLUDE,
            "description": {"suggested_value": from_options(CONF_TARGETS_TO_INCLUDE)},
        }

        SCHEMA_EXCLUDE_TARGETS: dict[str, Any] = {
            "schema": CONF_EXCLUDE_TARGETS,
            "default": from_options(CONF_EXCLUDE_TARGETS),
        }
        SCHEMA_TARGETS_TO_EXCLUDE: dict[str, Any] = {
            "schema": CONF_TARGETS_TO_EXCLUDE,
            "description": {"suggested_value": from_options(CONF_TARGETS_TO_EXCLUDE)},
        }

        return probatio.Schema(
            {
                probatio.Optional(
                    CONF_PUBLISH_QUERY_SENSORS, default=from_options(CONF_PUBLISH_QUERY_SENSORS, False)
                ): BooleanSelector(),
                probatio.Optional(**SCHEMA_PUBLISH_FREQUENCY): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=600,
                        step=10,
                        unit_of_measurement="seconds",
                    )
                ),
                probatio.Optional(**SCHEMA_POLLING_FREQUENCY): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=3600,
                        step=10,
                        unit_of_measurement="seconds",
                    )
                ),
                probatio.Optional(**SCHEMA_CHANGE_DETECTION_TYPE): SelectSelector(
                    SelectSelectorConfig(
                        translation_key="change_detection_type",
                        options=[TRANSLATION_KEY_STATE, TRANSLATION_KEY_ATTRIBUTE],
                        multiple=True,
                    )
                ),
                probatio.Optional(**SCHEMA_TAGS): SelectSelector(
                    SelectSelectorConfig(options=[], custom_value=True, multiple=True)
                ),
                probatio.Optional(**SCHEMA_INCLUDE_TARGETS): BooleanSelector(
                    BooleanSelectorConfig(),
                ),
                probatio.Optional(**SCHEMA_TARGETS_TO_INCLUDE): TargetSelector(
                    TargetSelectorConfig(),
                ),
                probatio.Optional(**SCHEMA_EXCLUDE_TARGETS): BooleanSelector(
                    BooleanSelectorConfig(),
                ),
                probatio.Optional(**SCHEMA_TARGETS_TO_EXCLUDE): TargetSelector(
                    TargetSelectorConfig(),
                ),
            }
        )

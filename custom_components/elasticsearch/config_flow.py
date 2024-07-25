"""Config flow for Elastic."""

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
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
    CONF_PUBLISH_FREQUENCY,
    CONF_SSL_CA_PATH,
    CONF_SSL_VERIFY_HOSTNAME,
    CONF_TAGS,
    CONF_TARGETS_TO_EXCLUDE,
    CONF_TARGETS_TO_INCLUDE,
    ONE_MINUTE,
    StateChangeType,
)
from custom_components.elasticsearch.const import DOMAIN as ELASTIC_DOMAIN
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    CannotConnect,
    InsufficientPrivileges,
    UntrustedCertificate,
)
from custom_components.elasticsearch.es_gateway_8 import Elasticsearch8Gateway

from .logger import (
    async_log_enter_exit_debug,
    async_log_enter_exit_info,
    log_enter_exit_debug,
    log_enter_exit_info,
)

CONFIG_TO_REDACT = {CONF_API_KEY, CONF_PASSWORD, CONF_USERNAME}

# Data Flow values
SCHEMA_URL: dict[Any, Any] = {"schema": CONF_URL, "default": "https://localhost:9200"}
SCHEMA_AUTHENTICATION_TYPE: dict[Any, Any] = {
    "schema": CONF_AUTHENTICATION_TYPE,
    "default": CONF_API_KEY,
}
SCHEMA_USERNAME = {"schema": CONF_USERNAME, "default": None}
SCHEMA_PASSWORD = {"schema": CONF_PASSWORD, "default": None}
SCHEMA_VERIFY_SSL = {"schema": CONF_VERIFY_SSL, "default": True}
SCHEMA_SSL_VERIFY_HOSTNAME = {"schema": CONF_SSL_VERIFY_HOSTNAME, "default": True}
SCHEMA_SSL_CA_PATH: dict[str, Any] = {"schema": CONF_SSL_CA_PATH}
SCHEMA_API_KEY = {"schema": CONF_API_KEY, "default": None}
SCHEMA_TIMEOUT = {"schema": CONF_TIMEOUT, "default": 30}


TRANSLATION_KEY_STATE = "STATE"
TRANSLATION_KEY_ATTRIBUTE = "ATTRIBUTE"
TRANSLATION_KEY_API_KEY = "API_KEY"
TRANSLATION_KEY_BASIC_AUTH = "BASIC_AUTH"


class ElasticFlowHandler(config_entries.ConfigFlow, domain=ELASTIC_DOMAIN):
    """Handle an Elastic config flow."""

    VERSION = 6
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH
    GATEWAY = Elasticsearch8Gateway

    def __init__(self) -> None:
        """Initialize the Elastic flow."""
        self._reauth_entry: ConfigEntry | None = None
        self._prospective_config: dict[str, Any] = self.init_data or {}

    @async_log_enter_exit_info
    async def async_step_user(
        self, user_input: dict | None = None, errors: dict | None = None
    ) -> ConfigFlowResult:  # noqa: ARG002
        """Handle a flow initialized by the user. This is the first step in the flow.

        We will gather the url of the elasticsearch cluster and the desired authentication method.
        """
        if user_input is not None:
            # If the URL has an https schema, test the connection and see if we get an untrusted certificate error
            prospective_settings: dict = {CONF_URL: user_input.get(CONF_URL)}
            self._prospective_config.update(user_input)

            try:
                await Elasticsearch8Gateway.async_init_then_stop(**prospective_settings)

            except UntrustedCertificate:
                return await self.async_step_certificate_issues()
            except CannotConnect as err:
                return await self.async_step_user(errors={"base": f"cannot_connect {err}"})
            except AuthenticationRequired:
                return await self.async_step_authentication_issues()

            return self.async_step_complete()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(**SCHEMA_URL): TextSelector(
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

        if user_input is not None:
            try:
                await Elasticsearch8Gateway.async_init_then_stop(
                    url=self._prospective_config[CONF_URL],
                    verify_certs=user_input.get(CONF_VERIFY_SSL, True),
                    ca_certs=user_input.get(CONF_SSL_CA_PATH),
                    verify_hostname=user_input.get(CONF_SSL_VERIFY_HOSTNAME, True),
                )

                self._prospective_config.update(user_input)

                # If we get here, we have a valid connection, so we can complete our flow
                return self.async_step_complete()

            except UntrustedCertificate:
                return await self.async_step_certificate_issues(errors={"base": "untrusted_certificate"})

            except CannotConnect:
                return self.async_abort(reason="cannot_connect")
            except AuthenticationRequired:
                self._prospective_config.update(user_input)
                return await self.async_step_authentication_issues()

        return self.async_show_form(
            step_id="certificate_issues",
            data_schema=vol.Schema(
                {
                    vol.Required(**SCHEMA_VERIFY_SSL): BooleanSelector(
                        BooleanSelectorConfig(),
                    ),
                    vol.Required(**SCHEMA_SSL_VERIFY_HOSTNAME): BooleanSelector(
                        BooleanSelectorConfig(),
                    ),
                    vol.Optional(**SCHEMA_SSL_CA_PATH): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.TEXT,
                        )
                    ),
                    # To do: consider switching to a file selector to upload the ca cert vol.Optional(**SCHEMA_SSL_CA_PATH): FileSelector(FileSelectorConfig(accept=".pem,.crt")),
                },
            ),
            errors=errors,
        )

    @async_log_enter_exit_info
    async def async_step_authentication_issues(self, user_input: dict | None = None) -> ConfigFlowResult:
        """We require Authentication information to connect to Elasticsearch."""

        if user_input is not None:
            if user_input[CONF_AUTHENTICATION_TYPE] == TRANSLATION_KEY_BASIC_AUTH:
                return await self.async_step_basic_auth()
            if user_input[CONF_AUTHENTICATION_TYPE] == TRANSLATION_KEY_API_KEY:
                return await self.async_step_api_key()

        # Show a form where we ask the user if they want to use API Key or Basic Auth
        return self.async_show_form(
            step_id="authentication_issues",
            data_schema=vol.Schema(
                {
                    vol.Required(**SCHEMA_AUTHENTICATION_TYPE): SelectSelector(
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

        if user_input is not None:
            try:
                await Elasticsearch8Gateway.async_init_then_stop(
                    url=self._prospective_config[CONF_URL],
                    username=user_input.get(CONF_USERNAME),
                    password=user_input.get(CONF_PASSWORD),
                    verify_certs=self._prospective_config.get(CONF_VERIFY_SSL, True),
                    verify_hostname=self._prospective_config.get(CONF_SSL_VERIFY_HOSTNAME, True),
                    ca_certs=self._prospective_config.get(CONF_SSL_CA_PATH),
                )
            except InsufficientPrivileges:
                return await self.async_step_basic_auth(errors={"base": "insufficient_privileges"})
            except AuthenticationRequired:
                return await self.async_step_basic_auth(errors={"base": "invalid_basic_auth"})

            # We are authenticated, update settings and complete flow
            self._prospective_config.update(user_input)
            return self.async_step_complete()

        return self.async_show_form(
            step_id="basic_auth",
            data_schema=vol.Schema(
                {
                    vol.Required(**SCHEMA_USERNAME): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.TEXT,
                        )
                    ),
                    vol.Required(**SCHEMA_PASSWORD): TextSelector(
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

        if user_input is not None:
            try:
                await Elasticsearch8Gateway.async_init_then_stop(
                    url=self._prospective_config[CONF_URL],
                    api_key=user_input.get(CONF_API_KEY),
                    verify_certs=self._prospective_config.get(CONF_VERIFY_SSL, True),
                    verify_hostname=self._prospective_config.get(CONF_SSL_VERIFY_HOSTNAME, True),
                    ca_certs=self._prospective_config.get(CONF_SSL_CA_PATH),
                )
            except InsufficientPrivileges:
                return await self.async_step_api_key(errors={"base": "insufficient_privileges"})
            except AuthenticationRequired:
                return await self.async_step_api_key(errors={"base": "invalid_api_key"})

            # We are authenticated, update settings and complete flow
            self._prospective_config.update(user_input)
            return self.async_step_complete()

        return self.async_show_form(
            step_id="api_key",
            data_schema=vol.Schema(
                {
                    vol.Required(**SCHEMA_API_KEY): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD,
                        )
                    ),
                },
            ),
            errors=errors,
        )

    @log_enter_exit_info
    def async_step_complete(self) -> ConfigFlowResult:
        """Handle the completion of the flow."""
        default_options = ElasticOptionsFlowHandler.default_options

        if self._reauth_entry is not None:
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                unique_id=self._reauth_entry.unique_id,
                title=self._reauth_entry.title,
                data=self._prospective_config,
                options={**self._reauth_entry.options},
            )

        title: str = self._prospective_config[CONF_URL]

        return self.async_create_entry(title=title, data=self._prospective_config, options=default_options)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return ElasticOptionsFlowHandler(config_entry)

    async def async_step_reauth(self, user_input: dict | None) -> ConfigFlowResult:
        """Handle reauthorization."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="no_entry")

        self._reauth_entry = entry

        self._prospective_config = dict(entry.data)

        if self._prospective_config.get(CONF_USERNAME, None) is not None:
            return await self.async_step_basic_auth()
        if self._prospective_config.get(CONF_API_KEY, None) is not None:
            return await self.async_step_api_key()

        return self.async_abort(reason="no_auth")


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
        self.config_entry = config_entry
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

            if self.hass is not None:  # workaround: hass is not defined while testing
                self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)

            return self.async_create_entry(title="", data=self.options)

        return self.async_show_form(
            step_id="options",
            data_schema=self._build_options_schema(),
        )

    @log_enter_exit_debug
    def _build_options_schema(self) -> vol.Schema:
        """Build the options schema."""

        from_options = self.config_entry.options.get

        SCHEMA_PUBLISH_FREQUENCY = {
            "schema": CONF_PUBLISH_FREQUENCY,
            "default": from_options(CONF_PUBLISH_FREQUENCY),
        }
        SCHEMA_POLLING_FREQUENCY = {
            "schema": CONF_POLLING_FREQUENCY,
            "default": from_options(CONF_POLLING_FREQUENCY),
        }

        SCHEMA_CHANGE_DETECTION_TYPE = {
            "schema": CONF_CHANGE_DETECTION_TYPE,
            "default": from_options(CONF_CHANGE_DETECTION_TYPE),
        }
        SCHEMA_TAGS = {
            "schema": CONF_TAGS,
            "default": from_options(CONF_TAGS),
        }
        SCHEMA_INCLUDE_TARGETS = {
            "schema": CONF_INCLUDE_TARGETS,
            "default": from_options(CONF_INCLUDE_TARGETS),
        }
        SCHEMA_TARGETS_TO_INCLUDE = {
            "schema": CONF_TARGETS_TO_INCLUDE,
            "default": from_options(CONF_TARGETS_TO_INCLUDE),
        }

        SCHEMA_EXCLUDE_TARGETS = {
            "schema": CONF_EXCLUDE_TARGETS,
            "default": from_options(CONF_EXCLUDE_TARGETS),
        }
        SCHEMA_TARGETS_TO_EXCLUDE = {
            "schema": CONF_TARGETS_TO_EXCLUDE,
            "default": from_options(CONF_TARGETS_TO_EXCLUDE),
        }

        return vol.Schema(
            {
                vol.Optional(**SCHEMA_PUBLISH_FREQUENCY): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=600,
                        step=10,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional(**SCHEMA_POLLING_FREQUENCY): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=3600,
                        step=10,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional(**SCHEMA_CHANGE_DETECTION_TYPE): SelectSelector(
                    SelectSelectorConfig(
                        translation_key="change_detection_type",
                        options=[TRANSLATION_KEY_STATE, TRANSLATION_KEY_ATTRIBUTE],
                        multiple=True,
                    )
                ),
                vol.Optional(**SCHEMA_TAGS): SelectSelector(
                    SelectSelectorConfig(options=[], custom_value=True, multiple=True)
                ),
                vol.Optional(**SCHEMA_INCLUDE_TARGETS): BooleanSelector(
                    BooleanSelectorConfig(),
                ),
                vol.Optional(**SCHEMA_TARGETS_TO_INCLUDE): TargetSelector(
                    TargetSelectorConfig(),
                ),
                vol.Optional(**SCHEMA_EXCLUDE_TARGETS): BooleanSelector(
                    BooleanSelectorConfig(),
                ),
                vol.Optional(**SCHEMA_TARGETS_TO_EXCLUDE): TargetSelector(
                    TargetSelectorConfig(),
                ),
            }
        )

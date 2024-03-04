"""Config flow for Elastic."""


import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_IGNORE, SOURCE_IMPORT
from homeassistant.const import (
    CONF_ALIAS,
    CONF_API_KEY,
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.selector import selector

from custom_components.elasticsearch.es_privilege_check import ESPrivilegeCheck

from .const import (
    CONF_EXCLUDED_DOMAINS,
    CONF_EXCLUDED_ENTITIES,
    CONF_ILM_DELETE_AFTER,
    CONF_ILM_ENABLED,
    CONF_ILM_MAX_SIZE,
    CONF_ILM_POLICY_NAME,
    CONF_INCLUDED_DOMAINS,
    CONF_INCLUDED_ENTITIES,
    CONF_INDEX_FORMAT,
    CONF_INDEX_MODE,
    CONF_DATASTREAM_TYPE,
    CONF_DATASTREAM_NAME,
    CONF_DATASTREAM_NAMESPACE,
    CONF_PUBLISH_ENABLED,
    CONF_PUBLISH_FREQUENCY,
    CONF_PUBLISH_MODE,
    CONF_SSL_CA_PATH,
    ONE_MINUTE,
    PUBLISH_MODE_ALL,
    PUBLISH_MODE_ANY_CHANGES,
    PUBLISH_MODE_STATE_CHANGES,
)
from .const import DOMAIN as ELASTIC_DOMAIN
from .errors import (
    AuthenticationRequired,
    CannotConnect,
    InsufficientPrivileges,
    UnsupportedVersion,
    UntrustedCertificate,
)
from .es_gateway import ElasticsearchGateway
from .logger import LOGGER

DEFAULT_URL = "http://localhost:9200"
DEFAULT_ALIAS = "active-hass-index"
DEFAULT_INDEX_FORMAT = "hass-events"


DEFAULT_DATASTREAM_TYPE = "metrics"
DEFAULT_DATASTREAM_NAME = "homeassistant.events"
DEFAULT_DATASTREAM_NAMESPACE = "default"

DEFAULT_PUBLISH_ENABLED = True
DEFAULT_PUBLISH_FREQUENCY = ONE_MINUTE
DEFAULT_PUBLISH_MODE = PUBLISH_MODE_ANY_CHANGES
DEFAULT_VERIFY_SSL = True
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_ILM_ENABLED = True
DEFAULT_ILM_POLICY_NAME = "home-assistant"
DEFAULT_ILM_MAX_SIZE = "30gb"
DEFAULT_ILM_DELETE_AFTER = "365d"
DEFAULT_INDEX_MODE = "datastream"

def build_full_config(user_input=None):
    """Build the entire config validation schema."""
    if user_input is None:
        user_input = {}
    config = {
        CONF_URL: user_input.get(CONF_URL, DEFAULT_URL),
        CONF_API_KEY: user_input.get(CONF_API_KEY),
        CONF_USERNAME: user_input.get(CONF_USERNAME),
        CONF_PASSWORD: user_input.get(CONF_PASSWORD),
        CONF_TIMEOUT: user_input.get(CONF_TIMEOUT, DEFAULT_TIMEOUT_SECONDS),
        CONF_VERIFY_SSL: user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        CONF_SSL_CA_PATH: user_input.get(CONF_SSL_CA_PATH, None),
        CONF_PUBLISH_ENABLED: user_input.get(
            CONF_PUBLISH_ENABLED, DEFAULT_PUBLISH_ENABLED
        ),
        CONF_PUBLISH_FREQUENCY: user_input.get(
            CONF_PUBLISH_FREQUENCY, DEFAULT_PUBLISH_FREQUENCY
        ),
        CONF_PUBLISH_MODE: user_input.get(CONF_PUBLISH_MODE, DEFAULT_PUBLISH_MODE),
        CONF_ALIAS: user_input.get(CONF_ALIAS, DEFAULT_ALIAS),
        CONF_INDEX_FORMAT: user_input.get(CONF_INDEX_FORMAT, DEFAULT_INDEX_FORMAT),

        CONF_DATASTREAM_TYPE: user_input.get(CONF_DATASTREAM_TYPE, DEFAULT_DATASTREAM_TYPE),
        CONF_DATASTREAM_NAME: user_input.get(CONF_DATASTREAM_NAME, DEFAULT_DATASTREAM_NAME),
        CONF_DATASTREAM_NAMESPACE: user_input.get(CONF_DATASTREAM_NAMESPACE, DEFAULT_DATASTREAM_NAMESPACE),

        CONF_EXCLUDED_DOMAINS: user_input.get(CONF_EXCLUDED_DOMAINS, []),
        CONF_EXCLUDED_ENTITIES: user_input.get(CONF_EXCLUDED_ENTITIES, []),
        CONF_INCLUDED_DOMAINS: user_input.get(CONF_INCLUDED_DOMAINS, []),
        CONF_INCLUDED_ENTITIES: user_input.get(CONF_INCLUDED_ENTITIES, []),

        CONF_INDEX_MODE = user_input.get(CONF_INDEX_MODE, DEFAULT_INDEX_MODE),

        CONF_ILM_ENABLED: user_input.get(CONF_ILM_ENABLED, DEFAULT_ILM_ENABLED),
        CONF_ILM_POLICY_NAME: user_input.get(
            CONF_ILM_POLICY_NAME, DEFAULT_ILM_POLICY_NAME
        ),
        CONF_ILM_MAX_SIZE: user_input.get(CONF_ILM_MAX_SIZE, DEFAULT_ILM_MAX_SIZE),
        CONF_ILM_DELETE_AFTER: user_input.get(
            CONF_ILM_DELETE_AFTER, DEFAULT_ILM_DELETE_AFTER
        ),
    }

    if len(user_input.get(CONF_SSL_CA_PATH, "")):
        config[CONF_SSL_CA_PATH] = user_input[CONF_SSL_CA_PATH]

    return config


class ElasticFlowHandler(config_entries.ConfigFlow, domain=ELASTIC_DOMAIN):
    """Handle an Elastic config flow."""

    VERSION = 3
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return ElasticOptionsFlowHandler(config_entry)

    def __init__(self):
        """Initialize the Elastic flow."""
        self.config = {}

        self._reauth_entry = None

    def build_setup_menu(self):
        """Build setup menu to choose authentication method."""
        return self.async_show_menu(
            step_id="user",
            menu_options={
                "api_key": "Authenticate via API Key",
                "basic_auth": "Authenticate via username/password",
                "no_auth": "No authentication",
            },
        )

    def build_common_schema(self, errors=None):
        """Build validation schema that is common across all setup types."""
        schema = {
            vol.Required(
                CONF_URL, default=self.config.get(CONF_URL, "http://localhost:9200")
            ): str,
        }
        if errors:
            if errors["base"] == "untrusted_connection":
                schema.update(
                    {
                        vol.Required(
                            CONF_VERIFY_SSL,
                            default=self.config.get(
                                CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL
                            ),
                        ): bool,
                        vol.Optional(
                            CONF_SSL_CA_PATH
                        ): str,
                    }
                )

        return schema

    def build_no_auth_schema(self, errors=None):
        """Build validation schema for the no-authentication setup flow."""
        schema = {**self.build_common_schema(errors)}
        return schema

    def build_basic_auth_schema(self, errors=None, skip_common=False):
        """Build validation schema for the basic authentication setup flow."""
        schema = {} if skip_common else {**self.build_common_schema(errors)}
        schema.update(
            {
                vol.Required(
                    CONF_USERNAME, default=self.config.get(CONF_USERNAME, "")
                ): str,
                vol.Required(
                    CONF_PASSWORD, default=self.config.get(CONF_PASSWORD, "")
                ): str,
            }
        )
        return schema

    def build_api_key_auth_schema(self, errors=None, skip_common = False):
        """Build validation schema for the ApiKey authentication setup flow."""
        schema = {} if skip_common else {**self.build_common_schema(errors)}
        schema.update(
            {
                vol.Required(
                    CONF_API_KEY, default=self.config.get(CONF_API_KEY, "")
                ): str,
            }
        )
        return schema

    def build_reauth_schema(self, errors=None):
        """Build validation schema for all reauth flows."""
        assert self._reauth_entry
        if self._reauth_entry.data.get(CONF_API_KEY):
            return self.build_api_key_auth_schema(errors=errors, skip_common=True)
        return self.build_basic_auth_schema(errors=errors, skip_common=True)

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        return self.build_setup_menu()

    async def async_step_no_auth(self, user_input=None):
        """Handle connection to an unsecured Elasticsearch cluster."""
        if user_input is None:
            return self.async_show_form(
                step_id="no_auth", data_schema=vol.Schema(self.build_no_auth_schema())
            )

        self.config = build_full_config(user_input)
        (success, errors) = await self._async_elasticsearch_login()
        if success:
            return await self._async_create_entry()

        return self.async_show_form(
            step_id="no_auth",
            data_schema=vol.Schema(self.build_no_auth_schema(errors)),
            errors=errors,
        )

    async def async_step_basic_auth(self, user_input=None):
        """Handle connection to an Elasticsearch cluster using basic authentication."""
        if user_input is None:
            return self.async_show_form(
                step_id="basic_auth",
                data_schema=vol.Schema(self.build_basic_auth_schema()),
            )

        self.config = build_full_config(user_input)
        (success, errors) = await self._async_elasticsearch_login()

        if success:
            return await self._async_create_entry()

        return self.async_show_form(
            step_id="basic_auth",
            data_schema=vol.Schema(self.build_basic_auth_schema(errors)),
            errors=errors,
        )

    async def async_step_api_key(self, user_input=None):
        """Handle connection to an Elasticsearch cluster using basic authentication."""
        if user_input is None:
            return self.async_show_form(
                step_id="api_key",
                data_schema=vol.Schema(self.build_api_key_auth_schema()),
            )

        self.config = build_full_config(user_input)
        (success, errors) = await self._async_elasticsearch_login()

        if success:
            return await self._async_create_entry()

        return self.async_show_form(
            step_id="api_key",
            data_schema=vol.Schema(self.build_api_key_auth_schema(errors)),
            errors=errors,
        )

    async def async_step_import(self, import_config):
        """Import a config entry from configuration.yaml."""

        # Check if new config entry matches any existing config entries
        entries = self.hass.config_entries.async_entries(ELASTIC_DOMAIN)
        for entry in entries:
            # If source is ignore bypass host check and continue through loop
            if entry.source == SOURCE_IGNORE:
                continue

            if entry.data[CONF_URL] == import_config[CONF_URL]:
                self.hass.config_entries.async_update_entry(
                    entry=entry,
                    data=build_full_config(import_config),
                    options=import_config,
                )
                return self.async_abort(reason="updated_entry")

        if entries:
            LOGGER.warning("Already configured. Only a single configuration possible.")
            return self.async_abort(reason="single_instance_allowed")

        self.config = build_full_config(import_config)
        (success, errors) = await self._async_elasticsearch_login()

        if success:
            return await self._async_create_entry()

        raise ConfigEntryNotReady

    async def async_step_reauth(self, user_input) -> FlowResult:
        """Handle reauthorization."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None
        self._reauth_entry = entry
        return await self.async_step_reauth_confirm(user_input)

    async def async_step_reauth_confirm(self, user_input: dict | None = None) -> FlowResult:
        """Dialog that informs the user that reauth is required."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema(self.build_reauth_schema(user_input))
            )

        username = user_input.get(CONF_USERNAME)
        password = user_input.get(CONF_PASSWORD)
        api_key = user_input.get(CONF_API_KEY)

        self.config = self._reauth_entry.data.copy()
        if username:
            self.config[CONF_USERNAME] = username
            self.config[CONF_PASSWORD] = password
        if api_key:
            self.config[CONF_API_KEY] = api_key

        success, errors = await self._async_elasticsearch_login()
        if success:
            return await self._async_create_entry()

        return self.async_show_form(
            step_id="reauth_confirm",
            errors=errors,
            data_schema=vol.Schema(self.build_reauth_schema(errors))
        )

    async def _async_elasticsearch_login(self):
        """Handle connection & authentication to Elasticsearch."""
        errors = {}

        try:
            gateway = ElasticsearchGateway(raw_config=self.config)
            await gateway.async_init()

            privilege_check = ESPrivilegeCheck(gateway)
            await privilege_check.enforce_privileges(self.config)
        except UntrustedCertificate:
            errors["base"] = "untrusted_connection"
        except AuthenticationRequired:
            if self.config.get(CONF_API_KEY):
                errors["base"] = "invalid_api_key"
            else:
                errors["base"] = "invalid_basic_auth"
        except InsufficientPrivileges:
            errors["base"] = "insufficient_privileges"
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except UnsupportedVersion:
            errors["base"] = "unsupported_version"
        except Exception as ex:  # pylint: disable=broad-except
            LOGGER.error(
                "Unknown error connecting with Elasticsearch cluster. %s",
                ex,
            )
            errors["base"] = "cannot_connect"
        finally:
            if gateway:
                await gateway.async_stop_gateway()

        success = not errors
        return (success, errors)

    async def _async_create_entry(self):
        """Create the config entry."""

        if self._reauth_entry:
            LOGGER.debug("Reauthorization successful")
            self.hass.config_entries.async_update_entry(
                self._reauth_entry, data=self.config
            )

            # Reload the config entry otherwise devices will remain unavailable
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
            )

            return self.async_abort(reason="reauth_successful")

        return self.async_create_entry(title=self.config[CONF_URL], data=self.config)


class ElasticOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Elastic options."""

    def __init__(self, config_entry):
        """Initialize Elastic options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)

    async def async_step_init(self, hass):  # pylint disable=unused-argument
        """Manage the Elastic options."""

        if self.config_entry.source == SOURCE_IMPORT:
            return await self.async_step_yaml()

        return await self.async_step_publish_options()

    async def async_step_yaml(self, user_input=None):  # pylint disable=unused-argument
        """No options for yaml managed entries."""
        return self.async_abort(reason="configured_via_yaml")

    async def async_step_publish_options(self, user_input=None):
        """Publish Options."""
        if user_input is not None:
            self.options.update(user_input)
            return await self.async_step_ilm_options()

        return self.async_show_form(
            step_id="publish_options",
            data_schema=vol.Schema(await self.async_build_publish_options_schema()),
        )

    async def async_step_ilm_options(self, user_input=None):
        """ILM Options."""
        errors = {}

        if user_input is not None:
            self.options.update(user_input)
            return await self._update_options()

        return self.async_show_form(
            step_id="ilm_options",
            data_schema=vol.Schema(self._build_ilm_options_schema()),
            errors=errors,
        )

    async def _update_options(self):
        """Update config entry options."""
        return self.async_create_entry(title="", data=self.options)

    def _get_config_value(self, key, default):
        current = self.options.get(key, default)
        if current is None:
            return default
        return current

    async def async_build_publish_options_schema(self):
        """Build the schema for publish options."""
        domains, entities = await self._async_get_domains_and_entities()

        current_excluded_domains = self._get_config_value(CONF_EXCLUDED_DOMAINS, [])
        current_included_domains = self._get_config_value(CONF_INCLUDED_DOMAINS, [])
        domain_options = self._dedup_list(domains + current_excluded_domains + current_included_domains)

        current_excluded_entities = self._get_config_value(CONF_EXCLUDED_ENTITIES, [])
        current_included_entities = self._get_config_value(CONF_INCLUDED_ENTITIES, [])
        entity_options = self._dedup_list(
            entities + current_excluded_entities + current_included_entities
        )

        schema = {
            vol.Required(
                CONF_PUBLISH_ENABLED,
                default=self._get_config_value(
                    CONF_PUBLISH_ENABLED, DEFAULT_PUBLISH_ENABLED
                ),
            ): bool,
            vol.Required(
                CONF_PUBLISH_FREQUENCY,
                default=self._get_config_value(
                    CONF_PUBLISH_FREQUENCY, DEFAULT_PUBLISH_FREQUENCY
                ),
            ): int,
            vol.Required(
                CONF_PUBLISH_MODE,
                default=self._get_config_value(CONF_PUBLISH_MODE, DEFAULT_PUBLISH_MODE),
            ): selector(
                {
                    "select": {
                        "options": [
                            {"label": "All entities", "value": PUBLISH_MODE_ALL},
                            {
                                "label": "Entities with state changes",
                                "value": PUBLISH_MODE_STATE_CHANGES,
                            },
                            {
                                "label": "Entities with state or attribute changes",
                                "value": PUBLISH_MODE_ANY_CHANGES,
                            },
                        ]
                    }
                }
            ),
            vol.Required(
                CONF_EXCLUDED_DOMAINS,
                default=current_excluded_domains,
            ): cv.multi_select(domain_options),
            vol.Required(
                CONF_EXCLUDED_ENTITIES,
                default=current_excluded_entities,
            ): cv.multi_select(entity_options),
            vol.Required(
                CONF_INCLUDED_DOMAINS,
                default=current_included_domains,
            ): cv.multi_select(domain_options),
            vol.Required(
                CONF_INCLUDED_ENTITIES,
                default=current_included_entities,
            ): cv.multi_select(entity_options),
        }

        if self.show_advanced_options:
            schema[
                vol.Required(
                    CONF_INDEX_FORMAT,
                    default=self._get_config_value(
                        CONF_INDEX_FORMAT, DEFAULT_INDEX_FORMAT
                    ),
                )
            ] = str

            schema[
                vol.Required(
                    CONF_ALIAS,
                    default=self._get_config_value(CONF_ALIAS, DEFAULT_ALIAS),
                )
            ] = str

        return schema

    def _build_ilm_options_schema(self):
        schema = {
            vol.Required(
                CONF_ILM_ENABLED, default=self._get_config_value(CONF_ILM_ENABLED, True)
            ): bool,
            vol.Required(
                CONF_ILM_POLICY_NAME,
                default=self._get_config_value(
                    CONF_ILM_POLICY_NAME, DEFAULT_ILM_POLICY_NAME
                ),
            ): str,
            vol.Required(
                CONF_ILM_MAX_SIZE,
                default=self._get_config_value(CONF_ILM_MAX_SIZE, DEFAULT_ILM_MAX_SIZE),
            ): str,
            vol.Required(
                CONF_ILM_DELETE_AFTER,
                default=self._get_config_value(
                    CONF_ILM_DELETE_AFTER, DEFAULT_ILM_DELETE_AFTER
                ),
            ): str,
        }

        return schema

    def _dedup_list(self, list_to_dedup):
        return list(dict.fromkeys(list_to_dedup))

    @callback
    async def _async_get_domains_and_entities(self):
        states = self.hass.states.async_all()
        domains = set()
        entity_ids = []

        for state in states:
            entity_ids.append(state.entity_id)
            domains.add(state.domain)

        return sorted(domains), sorted(entity_ids)

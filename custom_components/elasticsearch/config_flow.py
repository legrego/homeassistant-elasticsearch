"""Config flow for Elastic."""


import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_IGNORE, SOURCE_IMPORT
from homeassistant.const import (
    CONF_ALIAS,
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import selector

from .const import (
    CONF_EXCLUDED_DOMAINS,
    CONF_EXCLUDED_ENTITIES,
    CONF_HEALTH_SENSOR_ENABLED,
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
)
from .const import DOMAIN as ELASTIC_DOMAIN
from .const import (
    ONE_MINUTE,
    PUBLISH_MODE_ALL,
    PUBLISH_MODE_ANY_CHANGES,
    PUBLISH_MODE_STATE_CHANGES,
)
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
DEFAULT_PUBLISH_ENABLED = True
DEFAULT_PUBLISH_FREQUENCY = ONE_MINUTE
DEFAULT_PUBLISH_MODE = PUBLISH_MODE_ANY_CHANGES
DEFAULT_VERIFY_SSL = True
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_ILM_ENABLED = True
DEFAULT_ILM_POLICY_NAME = "home-assistant"
DEFAULT_ILM_MAX_SIZE = "30gb"
DEFAULT_ILM_DELETE_AFTER = "365d"


class ElasticFlowHandler(config_entries.ConfigFlow, domain=ELASTIC_DOMAIN):
    """Handle an Elastic config flow."""

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return ElasticOptionsFlowHandler(config_entry)

    def __init__(self):
        """Initialize the Elastic flow."""
        self.config = {}

        self.tls_schema = {
            vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
            vol.Optional(CONF_SSL_CA_PATH, default=""): str,
        }

    def build_setup_schema(self):
        schema = {
            vol.Required(
                CONF_URL, default=self.config.get(CONF_URL, "http://localhost:9200")
            ): str,
            vol.Optional(CONF_USERNAME): str,
            vol.Optional(CONF_PASSWORD): str,
        }

        if self.show_advanced_options:
            schema[
                vol.Required(
                    CONF_TIMEOUT,
                    default=self.config.get(CONF_TIMEOUT, DEFAULT_TIMEOUT_SECONDS),
                )
            ] = int

        return schema

    def build_full_config(self, user_input={}):
        return {
            CONF_URL: user_input.get(CONF_URL, DEFAULT_URL),
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
            CONF_EXCLUDED_DOMAINS: user_input.get(CONF_EXCLUDED_DOMAINS, []),
            CONF_EXCLUDED_ENTITIES: user_input.get(CONF_EXCLUDED_ENTITIES, []),
            CONF_INCLUDED_DOMAINS: user_input.get(CONF_INCLUDED_DOMAINS, []),
            CONF_INCLUDED_ENTITIES: user_input.get(CONF_INCLUDED_ENTITIES, []),
            CONF_HEALTH_SENSOR_ENABLED: user_input.get(
                CONF_HEALTH_SENSOR_ENABLED, True
            ),
            CONF_ILM_ENABLED: user_input.get(CONF_ILM_ENABLED, DEFAULT_ILM_ENABLED),
            CONF_ILM_POLICY_NAME: user_input.get(
                CONF_ILM_POLICY_NAME, DEFAULT_ILM_POLICY_NAME
            ),
            CONF_ILM_MAX_SIZE: user_input.get(CONF_ILM_MAX_SIZE, DEFAULT_ILM_MAX_SIZE),
            CONF_ILM_DELETE_AFTER: user_input.get(
                CONF_ILM_DELETE_AFTER, DEFAULT_ILM_DELETE_AFTER
            ),
        }

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(self.build_setup_schema()),
            )

        self.config = self.build_full_config(user_input)

        return await self._async_elasticsearch_login()

    async def async_step_tls(self, user_input=None):
        """Handle establishing a trusted connection to Elasticsearch."""

        if user_input is None:
            return self.async_show_form(
                step_id="tls", data_schema=vol.Schema(self.tls_schema)
            )

        self.config[CONF_VERIFY_SSL] = user_input[CONF_VERIFY_SSL]
        if len(user_input[CONF_SSL_CA_PATH]):
            self.config[CONF_SSL_CA_PATH] = user_input[CONF_SSL_CA_PATH]

        return await self._async_elasticsearch_login()

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
                    data=self.build_full_config(import_config),
                    options=import_config,
                )
                return self.async_abort(reason="updated_entry")

        if entries:
            LOGGER.warning("Already configured. Only a single configuration possible.")
            return self.async_abort(reason="single_instance_allowed")

        return await self.async_step_user(user_input=import_config)

    async def _async_elasticsearch_login(self):
        """Handle connection & authentication to Elasticsearch"""
        errors = {}

        try:
            gateway = ElasticsearchGateway(self.config)
            await gateway.check_connection(self.hass)
        except UntrustedCertificate:
            errors["base"] = "untrusted_connection"
            return self.async_show_form(
                step_id="tls", data_schema=vol.Schema(self.tls_schema), errors=errors
            )
        except AuthenticationRequired:
            errors["base"] = "invalid_auth"
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

        if errors:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(self.build_setup_schema()),
                errors=errors,
            )

        return await self._async_create_entry()

    async def _async_create_entry(self):
        """Create the config entry."""
        existing_entry = await self.async_set_unique_id(self.config[CONF_URL])

        if existing_entry:
            self.hass.config_entries.async_update_entry(
                existing_entry, data=self.config
            )
            # Reload the config entry otherwise devices will remain unavailable
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(existing_entry.entry_id)
            )

            return self.async_abort(reason="reauth_successful")

        return self.async_create_entry(title=self.config[CONF_URL], data=self.config)


class ElasticOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Elastic options."""

    def __init__(self, config_entry):
        """Initialize Elastic options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):
        """Manage the Elastic options."""

        if self.config_entry.source == SOURCE_IMPORT:
            return await self.async_step_yaml(user_input)

        return await self.async_step_publish_options()

    async def async_step_yaml(self, user_input=None):
        """No options for yaml managed entries."""
        return self.async_abort(reason="configured_via_yaml")

    async def async_step_publish_options(self, user_input=None):
        """Publish Options"""
        if user_input is not None:
            self.options.update(user_input)
            return await self.async_step_ilm_options()

        return self.async_show_form(
            step_id="publish_options",
            data_schema=vol.Schema(await self.async_build_publish_options_schema()),
        )

    async def async_step_ilm_options(self, user_input=None):
        """ILM Options"""
        errors = {}

        if user_input is not None:
            self.options.update(user_input)
            return await self.async_step_health_options()

        return self.async_show_form(
            step_id="ilm_options",
            data_schema=vol.Schema(self._build_ilm_options_schema()),
            errors=errors,
        )

    async def async_step_health_options(self, user_input=None):
        """ Health Sensor Options"""
        if user_input is not None:
            self.options.update(user_input)
            return await self._update_options()

        return self.async_show_form(
            step_id="health_options",
            data_schema=vol.Schema(self._build_health_options_schema()),
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
        """Builds the schema for publish options."""
        domains, entities = await self._async_get_domains_and_entities()

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
                default=self._get_config_value(CONF_EXCLUDED_DOMAINS, []),
            ): cv.multi_select(domains),
            vol.Required(
                CONF_EXCLUDED_ENTITIES,
                default=self._get_config_value(CONF_EXCLUDED_ENTITIES, []),
            ): cv.multi_select(entities),
            vol.Required(
                CONF_INCLUDED_DOMAINS,
                default=self._get_config_value(CONF_INCLUDED_DOMAINS, []),
            ): cv.multi_select(domains),
            vol.Required(
                CONF_INCLUDED_ENTITIES,
                default=self._get_config_value(CONF_INCLUDED_ENTITIES, []),
            ): cv.multi_select(entities),
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

    def _build_health_options_schema(self):
        schema = {
            vol.Required(
                CONF_HEALTH_SENSOR_ENABLED,
                default=self._get_config_value(CONF_HEALTH_SENSOR_ENABLED, True),
            ): bool,
        }

        return schema

    @callback
    async def _async_get_domains_and_entities(self):
        states = self.hass.states.async_all()
        domains = set()
        entity_ids = []

        for state in states:
            entity_ids.append(state.entity_id)
            domains.add(state.domain)

        return sorted(list(domains)), sorted(entity_ids)

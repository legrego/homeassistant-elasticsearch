"""Config flow for Elastic."""

from dataclasses import dataclass

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
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
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import selector

from .const import (
    CONF_EXCLUDED_DOMAINS,
    CONF_EXCLUDED_ENTITIES,
    CONF_ILM_ENABLED,
    CONF_ILM_POLICY_NAME,
    CONF_INCLUDED_DOMAINS,
    CONF_INCLUDED_ENTITIES,
    CONF_INDEX_FORMAT,
    CONF_INDEX_MODE,
    CONF_PUBLISH_ENABLED,
    CONF_PUBLISH_FREQUENCY,
    CONF_PUBLISH_MODE,
    CONF_SSL_CA_PATH,
    ES_CHECK_PERMISSIONS_DATASTREAM,
    INDEX_MODE_DATASTREAM,
    INDEX_MODE_LEGACY,
    ONE_MINUTE,
    PUBLISH_MODE_ALL,
    PUBLISH_MODE_ANY_CHANGES,
    PUBLISH_MODE_STATE_CHANGES,
)
from .const import DOMAIN as ELASTIC_DOMAIN
from .errors import (
    AuthenticationRequired,
    CannotConnect,
    ClientError,
    InsufficientPrivileges,
    UnsupportedVersion,
    UntrustedCertificate,
)
from .es_gateway import Elasticsearch7Gateway
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
DEFAULT_INDEX_MODE = "datastream"


def build_new_options(existing_options: dict = None, user_input: dict = None):
    """Build the entire options validation schema."""
    if user_input is None:
        user_input = {}
    if existing_options is None:
        existing_options = {}
    options = {
        CONF_PUBLISH_ENABLED: user_input.get(
            CONF_PUBLISH_ENABLED,
            existing_options.get(CONF_PUBLISH_ENABLED, DEFAULT_PUBLISH_ENABLED),
        ),
        CONF_PUBLISH_FREQUENCY: user_input.get(
            CONF_PUBLISH_FREQUENCY,
            existing_options.get(CONF_PUBLISH_FREQUENCY, DEFAULT_PUBLISH_FREQUENCY),
        ),
        CONF_PUBLISH_MODE: user_input.get(
            CONF_PUBLISH_MODE,
            existing_options.get(CONF_PUBLISH_MODE, DEFAULT_PUBLISH_MODE),
        ),
        CONF_ALIAS: user_input.get(CONF_ALIAS, existing_options.get(CONF_ALIAS, DEFAULT_ALIAS)),
        CONF_INDEX_FORMAT: user_input.get(
            CONF_INDEX_FORMAT,
            existing_options.get(CONF_INDEX_FORMAT, DEFAULT_INDEX_FORMAT),
        ),
        CONF_ILM_POLICY_NAME: user_input.get(
            CONF_ILM_POLICY_NAME,
            existing_options.get(CONF_ILM_POLICY_NAME, DEFAULT_ILM_POLICY_NAME),
        ),
        CONF_ILM_ENABLED: user_input.get(
            CONF_ILM_ENABLED,
            existing_options.get(CONF_ILM_ENABLED, DEFAULT_ILM_ENABLED),
        ),
        CONF_EXCLUDED_DOMAINS: user_input.get(CONF_EXCLUDED_DOMAINS, existing_options.get(CONF_EXCLUDED_DOMAINS, [])),
        CONF_EXCLUDED_ENTITIES: user_input.get(CONF_EXCLUDED_ENTITIES, existing_options.get(CONF_EXCLUDED_ENTITIES, [])),
        CONF_INCLUDED_DOMAINS: user_input.get(CONF_INCLUDED_DOMAINS, existing_options.get(CONF_INCLUDED_DOMAINS, [])),
        CONF_INCLUDED_ENTITIES: user_input.get(CONF_INCLUDED_ENTITIES, existing_options.get(CONF_INCLUDED_ENTITIES, [])),
    }

    return options


def build_new_data(existing_data: dict = None, user_input: dict = None):
    """Build the entire data validation schema."""
    if user_input is None:
        user_input = {}
    if existing_data is None:
        existing_data = {}

    data = {
        CONF_URL: user_input.get(CONF_URL, existing_data.get(CONF_URL, DEFAULT_URL)),
        CONF_TIMEOUT: user_input.get(CONF_TIMEOUT, existing_data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT_SECONDS)),
        CONF_VERIFY_SSL: user_input.get(CONF_VERIFY_SSL, existing_data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)),
        CONF_SSL_CA_PATH: user_input.get(CONF_SSL_CA_PATH, existing_data.get(CONF_SSL_CA_PATH, None)),
        CONF_INDEX_MODE: user_input.get(CONF_INDEX_MODE, existing_data.get(CONF_INDEX_MODE, DEFAULT_INDEX_MODE)),
        "use_connection_monitor": existing_data.get("use_connection_monitor", True),
    }
    auth = {
        CONF_USERNAME: user_input.get(CONF_USERNAME, existing_data.get(CONF_USERNAME, None)),
        CONF_PASSWORD: user_input.get(CONF_PASSWORD, existing_data.get(CONF_PASSWORD, None)),
        CONF_API_KEY: user_input.get(CONF_API_KEY, existing_data.get(CONF_API_KEY, None)),
    }

    # Set auth method based on the user input provided, only save relevant params
    if auth.get(CONF_USERNAME) or auth.get(CONF_PASSWORD):
        data[CONF_USERNAME] = auth.get(CONF_USERNAME)
        data[CONF_PASSWORD] = auth.get(CONF_PASSWORD)

    elif auth.get(CONF_API_KEY):
        data[CONF_API_KEY] = auth.get(CONF_API_KEY)

    if data.get(CONF_SSL_CA_PATH) and len(data.get(CONF_SSL_CA_PATH)) > 0:
        data[CONF_SSL_CA_PATH] = user_input[CONF_SSL_CA_PATH]

    return data


@dataclass
class ClusterCheckResult:
    """Result of cluster connection check."""

    success: bool
    errors: dict | None


class ElasticFlowHandler(config_entries.ConfigFlow, domain=ELASTIC_DOMAIN):
    """Handle an Elastic config flow."""

    VERSION = 5
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return ElasticOptionsFlowHandler(config_entry)

    def __init__(self):
        """Initialize the Elastic flow."""
        self._cluster_check_result: ClusterCheckResult | None = None

    # Build the first step of the flow
    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        return self.async_show_menu(
            step_id="user",
            menu_options={
                "api_key": "Authenticate via API Key",
                "basic_auth": "Authenticate via username/password",
                "no_auth": "No authentication",
            },
        )

    async def _handle_auth_flow(
        self,
        type: str,
        user_input: dict | None,
        data: dict | None = None,
        options: dict | None = None,
        retry=True,
    ):
        # Combines the logic from all the async_step_*_auth methods into a single method

        def build_auth_schema(data, type: str, errors=None, skip_common=False):
            """Build the authentication schema."""

            schema = {}
            if not skip_common:
                schema.update(
                    {
                        vol.Required(
                            CONF_URL,
                            default=data.get(CONF_URL, "http://localhost:9200"),
                        ): str,
                    }
                )

            if errors and errors["base"] == "untrusted_connection":
                schema.update(
                    {
                        vol.Required(
                            CONF_VERIFY_SSL,
                            default=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                        ): bool,
                        vol.Optional(CONF_SSL_CA_PATH): str,
                    }
                )

            if type == "basic_auth":
                schema.update(
                    {
                        vol.Required(CONF_USERNAME, default=data.get(CONF_USERNAME, "")): str,
                        vol.Required(CONF_PASSWORD, default=data.get(CONF_PASSWORD, "")): str,
                    }
                )

            if type == "api_key":
                schema.update(
                    {
                        vol.Required(CONF_API_KEY, default=data.get(CONF_API_KEY, "")): str,
                    }
                )

            if type == "no_auth":
                pass

            return schema

        effective_data = build_new_data(existing_data=data, user_input=user_input)

        # Handle initial view of form
        if user_input is None:
            return self.async_show_form(
                step_id=type,
                data_schema=vol.Schema(
                    build_auth_schema(
                        type=type,
                        data=effective_data,
                        errors=None,
                    )
                ),
            )

        # Figure out what we need to auth check for
        verify_permissions = ES_CHECK_PERMISSIONS_DATASTREAM

        if effective_data.get(CONF_INDEX_MODE) == INDEX_MODE_LEGACY:
            verify_permissions = None

        params = {
            "url": user_input.get("url"),
            "verify_certs": user_input.get("verify_ssl", True),
            "ca_certs": user_input.get("ssl_ca_path"),
            "verify_permissions": verify_permissions,
        }

        # Handle testing various authentication methods
        if type == "basic_auth":
            params[CONF_USERNAME] = user_input.get(CONF_USERNAME)
            params[CONF_PASSWORD] = user_input.get(CONF_PASSWORD)
        if type == "api_key":
            params[CONF_API_KEY] = user_input.get(CONF_API_KEY)

        result = await self._async_elasticsearch_login(**params)

        # Connection to Elasticsearch was successful. Create the entry.
        if result.success:
            return await self._async_create_entry(
                data={**effective_data},
                options=build_new_options(options),
            )

        if retry:
            # Connection was not successful, reshow this form showing the previous connection error, retaining any user input
            return self.async_show_form(
                step_id=type,
                data_schema=vol.Schema(
                    build_auth_schema(
                        type=type,
                        data=effective_data,
                        errors=result.errors,
                    )
                ),
                errors=result.errors,
            )
        else:
            return self.async_abort(reason="cannot_connect")

    async def async_step_no_auth(self, user_input=map | None):
        """Handle connection to an unsecured Elasticsearch cluster."""

        return await self._handle_auth_flow(user_input=user_input, data=self.init_data, type="no_auth")

    async def async_step_basic_auth(self, user_input=map | None):
        """Handle connection to an unsecured Elasticsearch cluster."""

        return await self._handle_auth_flow(user_input=user_input, data=self.init_data, type="basic_auth")

    async def async_step_api_key(self, user_input=map | None):
        """Handle connection to an unsecured Elasticsearch cluster."""

        return await self._handle_auth_flow(user_input=user_input, data=self.init_data, type="api_key")

    async def async_step_reauth(self, user_input) -> FlowResult:
        """Handle reauthorization."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None

        auth_method = "no_auth"
        if entry.data.get(CONF_USERNAME):
            auth_method = "basic_auth"

        if entry.data.get(CONF_API_KEY):
            auth_method = "api_key"

        return await self._handle_auth_flow(
            data=entry.data,
            user_input=user_input,
            options=entry.options,
            type=auth_method,
        )

    async def _async_elasticsearch_login(
        self,
        url: str,
        verify_certs: bool,
        ca_certs: str,
        username: str = None,
        password: str = None,
        api_key: str = None,
        timeout: int = 30,
        verify_permissions: dict | None = None,
    ) -> ClusterCheckResult:
        """Handle connection & authentication to Elasticsearch."""
        errors = {}

        temp_gateway = Elasticsearch7Gateway(
            hass=self.hass,
            url=url,
            username=username,
            password=password,
            api_key=api_key,
            verify_certs=verify_certs,
            ca_certs=ca_certs,
            request_timeout=timeout,
            minimum_privileges=verify_permissions,
            use_connection_monitor=False,
        )

        try:
            await temp_gateway.async_init()

        except ClientError:
            # For a Client Error, try to initialize without SSL verification, if this works then there is a self-signed certificate being used
            try:
                temp_no_ssl_gateway = Elasticsearch7Gateway(
                    hass=self.hass,
                    url=url,
                    username=username,
                    password=password,
                    api_key=api_key,
                    verify_certs=False,
                    ca_certs=ca_certs,
                    request_timeout=timeout,
                    minimum_privileges=verify_permissions,
                    use_connection_monitor=False,
                )

                await temp_no_ssl_gateway.async_init()

                errors["base"] = "untrusted_connection"
            except Exception:
                errors["base"] = "client_error"
            finally:
                if temp_no_ssl_gateway is not None:
                    await temp_no_ssl_gateway.stop()
        except UntrustedCertificate:
            errors["base"] = "untrusted_connection"
        except AuthenticationRequired:
            if api_key is not None:
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
            if temp_gateway is not None:
                await temp_gateway.stop()

        success = not errors
        return ClusterCheckResult(success, errors)

    async def _async_create_entry(self, data, options):
        """Create the config entry."""

        entries = self.hass.config_entries.async_entries(ELASTIC_DOMAIN)

        if len(entries) == 0:
            return self.async_create_entry(title=data.get(CONF_URL), data=data, options=options)

        entry = entries[0]

        self.hass.config_entries.async_update_entry(entry, data=data, options=options)

        # Reload the config entry otherwise devices will remain unavailable
        self.hass.async_create_task(self.hass.config_entries.async_reload(entry.entry_id))

        return self.async_abort(reason="updated_entry")


class ElasticOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Elastic options."""

    def __init__(self, config_entry: ConfigEntry):
        """Initialize Elastic options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)

    async def async_step_init(self, hass):  # pylint disable=unused-argument
        """Manage the Elastic options."""

        return await self.async_step_publish_options()

    async def async_step_publish_options(self, user_input=None):
        """Publish Options."""
        if user_input is not None:
            self.options.update(user_input)
            if self.config_entry.data.get(CONF_INDEX_MODE, INDEX_MODE_DATASTREAM) == INDEX_MODE_DATASTREAM:
                return await self._update_options()
            else:
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
        entity_options = self._dedup_list(entities + current_excluded_entities + current_included_entities)

        schema = {
            vol.Required(
                CONF_PUBLISH_ENABLED,
                default=self._get_config_value(CONF_PUBLISH_ENABLED, DEFAULT_PUBLISH_ENABLED),
            ): bool,
            vol.Required(
                CONF_PUBLISH_FREQUENCY,
                default=self._get_config_value(CONF_PUBLISH_FREQUENCY, DEFAULT_PUBLISH_FREQUENCY),
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

        if self.show_advanced_options and self.config_entry.data.get(CONF_INDEX_MODE, DEFAULT_INDEX_MODE) != INDEX_MODE_DATASTREAM:
            schema[
                vol.Required(
                    CONF_INDEX_FORMAT,
                    default=self._get_config_value(CONF_INDEX_FORMAT, DEFAULT_INDEX_FORMAT),
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
            vol.Required(CONF_ILM_ENABLED, default=self._get_config_value(CONF_ILM_ENABLED, True)): bool,
            vol.Required(
                CONF_ILM_POLICY_NAME,
                default=self._get_config_value(CONF_ILM_POLICY_NAME, DEFAULT_ILM_POLICY_NAME),
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

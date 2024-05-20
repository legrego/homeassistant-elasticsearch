"""Support for sending event data to an Elasticsearch cluster."""

from elasticsearch.config_flow import ElasticFlowHandler
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import (
    CONF_HEALTH_SENSOR_ENABLED,
    CONF_INDEX_MODE,
    CONF_ONLY_PUBLISH_CHANGED,
    CONF_PUBLISH_MODE,
    DOMAIN,
    INDEX_MODE_LEGACY,
    PUBLISH_MODE_ALL,
    PUBLISH_MODE_ANY_CHANGES,
)
from .errors import AuthenticationRequired, InsufficientPrivileges, UnsupportedVersion
from .es_integration import ElasticIntegration
from .logger import LOGGER


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):  # pylint: disable=unused-argument
    """Migrate old entry."""

    latest_version = ElasticFlowHandler.VERSION

    if config_entry.version == latest_version:
        return True

    migrated_data, migrated_options, migrated_version = migrate_data_and_options_to_version(config_entry, latest_version)

    config_entry.version = migrated_version

    return hass.config_entries.async_update_entry(config_entry, data=migrated_data, options=migrated_options)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up integration via config flow."""

    LOGGER.debug("Setting up integration")
    init = await _async_init_integration(hass, config_entry)
    config_entry.add_update_listener(async_config_entry_updated)
    return init


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Teardown integration."""
    existing_instance = hass.data.get(DOMAIN)
    if isinstance(existing_instance, ElasticIntegration):
        LOGGER.debug("Shutting down previous integration")
        await existing_instance.async_shutdown(config_entry)
        hass.data[DOMAIN] = None
    return True


async def async_config_entry_updated(hass: HomeAssistant, config_entry: ConfigEntry):
    """Respond to config changes."""
    LOGGER.debug("Configuration change detected")
    return await _async_init_integration(hass, config_entry)


async def _async_init_integration(hass: HomeAssistant, config_entry: ConfigEntry):
    """Initialize integration."""
    await async_unload_entry(hass, config_entry)

    integration = None
    try:
        integration = ElasticIntegration(hass, config_entry)
        await integration.async_init()
    except UnsupportedVersion as err:
        msg = "Unsupported Elasticsearch version detected"
        LOGGER.error(msg)
        raise ConfigEntryNotReady(msg) from err
    except AuthenticationRequired as err:
        msg = "Missing or invalid credentials"
        LOGGER.error(msg)
        raise ConfigEntryAuthFailed(msg) from err
    except InsufficientPrivileges as err:
        LOGGER.error("Account does not have sufficient privileges")
        raise ConfigEntryAuthFailed from err
    except Exception as err:  # pylint disable=broad-exception-caught
        msg = "Exception during component initialization"
        LOGGER.error(msg + ": %s", err)
        raise ConfigEntryNotReady(msg) from err

    hass.data[DOMAIN] = integration

    return True


def migrate_data_and_options_to_version(config_entry: ConfigEntry, desired_version: int):
    """Migrate a config entry from its current version to a desired version."""
    LOGGER.debug(
        "Migrating config entry from version %s to %s",
        config_entry.version,
        desired_version,
    )

    data = {**config_entry.data}
    options = {**config_entry.options}
    begin_version = config_entry.version
    current_version = begin_version

    if current_version == 1 and desired_version >= 2:
        only_publish_changed = data.get(CONF_ONLY_PUBLISH_CHANGED, False)
        data[CONF_PUBLISH_MODE] = PUBLISH_MODE_ALL if not only_publish_changed else PUBLISH_MODE_ANY_CHANGES

        if CONF_ONLY_PUBLISH_CHANGED in data:
            del data[CONF_ONLY_PUBLISH_CHANGED]

        current_version = 2

    if current_version == 2 and desired_version >= 3:
        if CONF_HEALTH_SENSOR_ENABLED in data:
            del data[CONF_HEALTH_SENSOR_ENABLED]

        current_version = 3

    if current_version == 3 and desired_version >= 4:
        # Check the configured options for the index_mode
        if CONF_INDEX_MODE not in data:
            data[CONF_INDEX_MODE] = INDEX_MODE_LEGACY

        CONF_ILM_MAX_SIZE = "ilm_max_size"
        if CONF_ILM_MAX_SIZE in data:
            del data[CONF_ILM_MAX_SIZE]

        CONF_ILM_DELETE_AFTER = "ilm_delete_after"
        if CONF_ILM_DELETE_AFTER in data:
            del data[CONF_ILM_DELETE_AFTER]

        current_version = 4

    if current_version == 4 and desired_version >= 5:
        keys_to_remove = [
            "datastream_type",
            "datastream_name_prefix",
            "datastream_namespace",
        ]

        for key in keys_to_remove:
            if key in data:
                del data[key]

        keys_to_migrate = [
            "publish_enabled",
            "publish_frequency",
            "publish_mode",
            "excluded_domains",
            "excluded_entities",
            "included_domains",
            "included_entities",
        ]

        for key in keys_to_migrate:
            if key not in options and key in data:
                options[key] = data[key]
            if key in data:
                del data[key]

        # Check for the auth parameters and set the auth_method config based on which values are populated
        remove_keys_if_empty = [
            "username",
            "password",
            "api_key",
        ]

        for key in remove_keys_if_empty:
            if key in data and data[key] == "":
                del data[key]

        current_version = 5

    end_version = current_version

    LOGGER.info("Migration from version %s to version %s successful", begin_version, end_version)

    return data, options, end_version

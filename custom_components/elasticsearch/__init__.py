"""Support for sending event data to an Elasticsearch cluster."""

from __future__ import annotations

from logging import Logger
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, IntegrationError

from custom_components.elasticsearch.config_flow import ElasticFlowHandler
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    CannotConnect,
    ESIntegrationException,
    UnsupportedVersion,
)
from custom_components.elasticsearch.logger import (
    LOGGER,
    async_log_enter_exit_debug,
    async_log_enter_exit_info,
    have_child,
    log_enter_exit_debug,
)

from .es_integration import ElasticIntegration

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

type ElasticIntegrationConfigEntry = ConfigEntry[ElasticIntegration]


@async_log_enter_exit_info
async def async_setup_entry(hass: HomeAssistant, config_entry: ElasticIntegrationConfigEntry) -> bool:
    """Set up integration via config flow."""

    # Create an specific logger for this config entry
    _logger: Logger = have_child(name=config_entry.title)

    _logger.info("Initializing integration for %s", config_entry.title)

    try:
        integration = ElasticIntegration(hass=hass, config_entry=config_entry, log=_logger)
        await integration.async_init()
    except (UnsupportedVersion, CannotConnect) as err:
        raise ConfigEntryNotReady(err) from err
    except AuthenticationRequired as err:
        raise ConfigEntryAuthFailed(err) from err
    except ESIntegrationException as err:
        raise ConfigEntryNotReady(err) from err
    except Exception as err:
        msg = "Unknown error occurred"
        _logger.exception(msg)
        raise IntegrationError(err) from err

    config_entry.runtime_data = integration

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ElasticIntegrationConfigEntry) -> bool:
    """Teardown integration."""

    if (
        hasattr(config_entry, "runtime_data")
        and config_entry.runtime_data is not None
        and isinstance(config_entry.runtime_data, ElasticIntegration)
    ):
        integration = config_entry.runtime_data

        await integration.async_shutdown()
    else:
        LOGGER.warning(
            "Called to unload config entry %s, but it doesn't appear to be loaded", config_entry.title
        )

    return True


@async_log_enter_exit_debug
async def async_migrate_entry(hass: HomeAssistant, config_entry: ElasticIntegrationConfigEntry) -> bool:
    """Handle migration of config entry."""
    if config_entry.version == ElasticFlowHandler.VERSION:
        return True

    try:
        migrated_data, migrated_options, migrated_version = migrate_data_and_options_to_version(
            config_entry,
            ElasticFlowHandler.VERSION,
        )
    except ValueError:
        LOGGER.exception(
            "Migration failed attempting to migrate from version %s to version %s. Ended on %s.",
            config_entry.version,
            ElasticFlowHandler.VERSION,
        )
        return False

    hass.config_entries.async_update_entry(
        config_entry,
        data=migrated_data,
        options=migrated_options,
        version=migrated_version,
    )

    return True


@log_enter_exit_debug
def migrate_data_and_options_to_version(
    config_entry: ElasticIntegrationConfigEntry,
    desired_version: int,
) -> tuple[dict, dict, int]:
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

    if current_version < desired_version:
        for version in range(current_version + 1, desired_version + 1):
            migration_func = globals().get(f"migrate_to_version_{version}")
            if migration_func:
                data, options = migration_func(data, options)
                current_version = version

    end_version = current_version

    LOGGER.info("Migration from version %s to version %s successful", begin_version, end_version)

    return data, options, end_version


def migrate_to_version_2(data: dict, options: dict) -> tuple[dict, dict]:
    """Migrate config to version 2."""
    only_publish_changed = data.get("only_publish_changed", False)
    data["publish_mode"] = "All" if not only_publish_changed else "Any changes"

    if "only_publish_changed" in data:
        del data["only_publish_changed"]

    return data, options


def migrate_to_version_3(data: dict, options: dict) -> tuple[dict, dict]:
    """Migrate config to version 3."""
    if "health_sensor_enabled" in data:
        del data["health_sensor_enabled"]

    return data, options


def migrate_to_version_4(data: dict, options: dict) -> tuple[dict, dict]:
    """Migrate config to version 4."""
    if "index_mode" not in data:
        data["index_mode"] = "index"

    conf_ilm_max_size = "ilm_max_size"
    if conf_ilm_max_size in data:
        del data[conf_ilm_max_size]

    conf_ilm_delete_after = "ilm_delete_after"
    if conf_ilm_delete_after in data:
        del data[conf_ilm_delete_after]

    return data, options


def migrate_to_version_5(data: dict, options: dict) -> tuple[dict, dict]:
    """Migrate config to version 5."""
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

    remove_keys_if_empty = [
        "username",
        "password",
        "api_key",
    ]

    for key in remove_keys_if_empty:
        if key in data and data[key] == "":
            del data[key]

    return data, options


def migrate_to_version_6(data: dict, options: dict) -> tuple[dict, dict]:
    """Migrate config to version 6."""

    if data.get("index_mode") is not None:
        del data["index_mode"]

    # Change publish mode to change_detection_type
    if options.get("publish_mode") is not None:
        if options["publish_mode"] == "All":
            options["polling_frequency"] = options["publish_frequency"]
            options["change_detection_type"] = ["STATE", "ATTRIBUTE"]

        if options["publish_mode"] == "Any changes":
            options["change_detection_type"] = ["STATE", "ATTRIBUTE"]

        if options["publish_mode"] == "State changes":
            options["change_detection_type"] = ["STATE"]

        del options["publish_mode"]

    else:
        options["change_detection_type"] = ["STATE", "ATTRIBUTE"]

    # add dedicated settings for polling
    options_to_remove = [
        "ilm_enabled",
        "ilm_policy_name",
        "publish_mode",
        "publish_enabled",
        "index_format",
        "index_mode",
        "alias",
    ]

    for key in options_to_remove:
        if key in options:
            del options[key]

    return data, options

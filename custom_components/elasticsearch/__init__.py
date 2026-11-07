"""Support for sending event data to an Elasticsearch cluster."""

from __future__ import annotations

from logging import Logger
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.loader import (
    async_get_integration,
)

from custom_components.elasticsearch.config_flow import ElasticFlowHandler
from custom_components.elasticsearch.const import CONF_SSL_CA_PATH, DOMAIN, ELASTIC_DOMAIN
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    CannotConnect,
    ESIntegrationException,
    InvalidCACertificate,
    UnsupportedServer,
    UnsupportedVersion,
)
from custom_components.elasticsearch.issues import (
    MINIMUM_VERSION,
    async_create_unsupported_version_issue,
    async_delete_duplicate_cluster_issues_naming,
    async_delete_issues,
    async_delete_unsupported_version_issue,
)
from custom_components.elasticsearch.logger import (
    LOGGER,
    async_log_enter_exit_debug,
    async_log_enter_exit_info,
    have_child,
    log_enter_exit_debug,
)
from custom_components.elasticsearch.services import async_setup_services

from .es_integration import ElasticIntegration

if TYPE_CHECKING:  # pragma: no cover
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

type ElasticIntegrationConfigEntry = ConfigEntry[ElasticIntegration]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions, which work with any loaded entry."""

    async_setup_services(hass)

    return True


@async_log_enter_exit_info
async def async_setup_entry(hass: HomeAssistant, config_entry: ElasticIntegrationConfigEntry) -> bool:
    """Set up integration via config flow."""

    # Create an specific logger for this config entry
    _logger: Logger = have_child(name=config_entry.title)

    version = await get_integration_version(hass)

    _logger.info("Initializing integration v%s for %s", version, config_entry.title)

    try:
        integration = ElasticIntegration(hass=hass, config_entry=config_entry, log=_logger)
        await integration.async_init()
    except UnsupportedVersion as err:
        async_create_unsupported_version_issue(hass, config_entry, err.version)
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="unsupported_version",
            translation_placeholders={"minimum_version": MINIMUM_VERSION},
        ) from err
    except UnsupportedServer as err:
        raise ConfigEntryError(translation_domain=DOMAIN, translation_key="unsupported_server") from err
    except InvalidCACertificate as err:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="invalid_ca_certificate",
            translation_placeholders={"ca_path": str(config_entry.data.get(CONF_SSL_CA_PATH))},
        ) from err
    except CannotConnect as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        ) from err
    except AuthenticationRequired as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="authentication_failed"
        ) from err
    except ESIntegrationException as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="integration_error",
            translation_placeholders={"error": str(err)},
        ) from err
    except Exception as err:
        msg = "Unknown error occurred"
        _logger.exception(msg)
        raise ConfigEntryError(translation_domain=DOMAIN, translation_key="unexpected_error") from err

    async_delete_unsupported_version_issue(hass, config_entry)

    config_entry.runtime_data = integration
    return True


@async_log_enter_exit_info
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


async def async_remove_entry(hass: HomeAssistant, config_entry: ElasticIntegrationConfigEntry) -> None:
    """Clean up after an entry is removed."""

    async_delete_issues(hass, config_entry)

    # Entries that shared a cluster with the removed one no longer have a duplicate, whether or
    # not they're loaded. One that isn't loaded takes the cluster's UUID when it next loads.
    async_delete_duplicate_cluster_issues_naming(hass, config_entry)

    # A loaded entry can take the cluster's UUID now. If yet another entry still shares its
    # cluster, this raises its issue again, naming that entry.
    for entry in hass.config_entries.async_loaded_entries(ELASTIC_DOMAIN):
        if isinstance(getattr(entry, "runtime_data", None), ElasticIntegration):
            entry.runtime_data.backfill_unique_id()


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
    except Exception:  # noqa: BLE001
        LOGGER.exception(
            "Migration failed attempting to migrate from version %s to version %s.",
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


async def get_integration_version(hass: HomeAssistant) -> str:
    """Return the version of the integration."""
    integration = await async_get_integration(hass, ELASTIC_DOMAIN)

    if integration is None or integration.version is None:
        return "Unknown"

    return integration.version.string


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
            options["polling_frequency"] = 0
            options["change_detection_type"] = ["STATE", "ATTRIBUTE"]

        if options["publish_mode"] == "State changes":
            options["polling_frequency"] = 0
            options["change_detection_type"] = ["STATE"]

        del options["publish_mode"]

    else:
        options["polling_frequency"] = 0
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


def migrate_to_version_7(data: dict, options: dict) -> tuple[dict, dict]:
    """Migrate config to version 7."""

    # if tags does not exist, set it to an empty array
    if "tags" not in options:
        options["tags"] = []

    options["targets_to_include"] = {}
    options["targets_to_exclude"] = {}
    options["exclude_targets"] = False
    options["include_targets"] = False

    if "included_entities" in options and len(options["included_entities"]) != 0:
        options["include_targets"] = True
        options["targets_to_include"]["entity_id"] = options["included_entities"]

    if "excluded_entities" in options and len(options["excluded_entities"]) != 0:
        options["exclude_targets"] = True
        options["targets_to_exclude"]["entity_id"] = options["excluded_entities"]

    keys_to_remove = [
        "excluded_domains",
        "excluded_entities",
        "included_domains",
        "included_entities",
    ]

    # Lowercase values in array options["change_detection_type"]
    if "change_detection_type" in options:
        options["change_detection_type"] = [x.lower() for x in options["change_detection_type"]]

    for key in keys_to_remove:
        if key in options:
            del options[key]

    return data, options

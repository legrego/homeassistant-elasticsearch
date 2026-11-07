"""Repair issues the Elasticsearch integration raises for problems the user can fix."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers import issue_registry as ir

from custom_components.elasticsearch.const import DOMAIN, ELASTIC_MINIMUM_VERSION

if TYPE_CHECKING:  # pragma: no cover
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

ISSUE_DUPLICATE_CLUSTER: str = "duplicate_cluster"
ISSUE_UNSUPPORTED_VERSION: str = "unsupported_version"

TROUBLESHOOTING_URL: str = "https://legrego.github.io/homeassistant-elasticsearch/troubleshooting/"

MINIMUM_VERSION: str = ".".join(str(part) for part in ELASTIC_MINIMUM_VERSION)


def issue_id(issue: str, config_entry: ConfigEntry) -> str:
    """Return the ID of an issue for one config entry, so that entries don't share issues."""
    return f"{issue}_{config_entry.entry_id}"


def async_create_duplicate_cluster_issue(
    hass: HomeAssistant, config_entry: ConfigEntry, other_entry: ConfigEntry
) -> None:
    """Report that a config entry publishes to the same cluster as another entry."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id(ISSUE_DUPLICATE_CLUSTER, config_entry),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_DUPLICATE_CLUSTER,
        translation_placeholders={"entry_title": config_entry.title, "other_title": other_entry.title},
        learn_more_url=f"{TROUBLESHOOTING_URL}#two-entries-publish-to-the-same-cluster",
    )


def async_delete_duplicate_cluster_issue(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Remove the duplicate cluster issue for a config entry, if there is one."""
    ir.async_delete_issue(hass, DOMAIN, issue_id(ISSUE_DUPLICATE_CLUSTER, config_entry))


def async_create_unsupported_version_issue(
    hass: HomeAssistant, config_entry: ConfigEntry, version: str | None
) -> None:
    """Report that a config entry connects to a version of Elasticsearch that is too old."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id(ISSUE_UNSUPPORTED_VERSION, config_entry),
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_UNSUPPORTED_VERSION,
        translation_placeholders={
            "entry_title": config_entry.title,
            "version": version or "unknown",
            "minimum_version": MINIMUM_VERSION,
        },
        learn_more_url=f"{TROUBLESHOOTING_URL}#unsupported-version",
    )


def async_delete_unsupported_version_issue(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Remove the unsupported version issue for a config entry, if there is one."""
    ir.async_delete_issue(hass, DOMAIN, issue_id(ISSUE_UNSUPPORTED_VERSION, config_entry))


def async_delete_issues(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Remove every issue raised for a config entry."""
    async_delete_duplicate_cluster_issue(hass, config_entry)
    async_delete_unsupported_version_issue(hass, config_entry)

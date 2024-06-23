"""constants."""

from enum import Enum
from typing import Any

DOMAIN: str = "elasticsearch"
ELASTIC_DOMAIN: str = "elasticsearch"

CONF_PUBLISH_FREQUENCY: str = "publish_frequency"
CONF_POLLING_FREQUENCY: str = "polling_frequency"
CONF_AUTHENTICATION_TYPE: str = "authentication_type"

CONF_CHANGE_DETECTION_ENABLED: str = "change_detection_enabled"
CONF_CHANGE_DETECTION_TYPE: str = "change_detection_type"

CONF_INCLUDE_TARGETS: str = "include_targets"
CONF_EXCLUDE_TARGETS: str = "exclude_targets"

CONF_TARGETS_TO_INCLUDE: str = "targets_to_include"
CONF_TARGETS_TO_EXCLUDE: str = "targets_to_exclude"

CONF_EXCLUDED_DOMAINS: str = "excluded_domains"
CONF_EXCLUDED_ENTITIES: str = "excluded_entities"
CONF_INCLUDED_DOMAINS: str = "included_domains"
CONF_INCLUDED_ENTITIES: str = "included_entities"

CONF_SSL_CA_PATH: str = "ssl_ca_path"

CONF_TAGS: str = "tags"

CONST_ENTITY_DETAILS_TO_ES_DOCUMENT: dict[str, str] = {
    # Keys are the key in the ES Document
    # Values are the keys from the ExtendedEntityRegistry flattened dict
    # Entity Attributes
    "area.floor.id": "floor.floor_id",
    "area.floor.name": "floor.name",
    "area.id": "area.id",
    "area.name": "area.name",
    "labels": "labels",
    "name": "name",
    "id": "object_id",
    "friendly_name": "friendly_name",
    "platform": "platform",
    "unit_of_measurement": "unit_of_measurement",
    "state.class": "state_class",
    # Device Attributes
    "device.class": "device.class",
    # "device.id": "device.id",
    "device.labels": "device.labels",
    "device.name": "device.name",
    "device.friendly_name": "device.friendly_name",
    "device.area.floor.id": "device.floor.floor_id",
    "device.area.floor.name": "device.floor.name",
    "device.area.id": "device.area.id",
    "device.area.name": "device.area.name",
}

CONST_ENTITY_DETAILS_TO_ES_DOCUMENT_KEYS = list(CONST_ENTITY_DETAILS_TO_ES_DOCUMENT.values())


ONE_MINUTE: int = 60
ONE_HOUR: int = 60 * 60

DATASTREAM_TYPE: str = "metrics"
DATASTREAM_DATASET_PREFIX: str = "homeassistant"
DATASTREAM_NAMESPACE: str = "default"

# Set to match the datastream prefix name
DATASTREAM_METRICS_INDEX_TEMPLATE_NAME: str = DATASTREAM_TYPE + "-" + DATASTREAM_DATASET_PREFIX

PUBLISH_REASON_POLLING: str = "Polling"
PUBLISH_REASON_STATE_CHANGE: str = "State change"
PUBLISH_REASON_ATTR_CHANGE: str = "Attribute change"

STATE_CHANGE_TYPE_VALUE: str = PUBLISH_REASON_STATE_CHANGE
STATE_CHANGE_TYPE_ATTR: str = PUBLISH_REASON_ATTR_CHANGE

ES_CHECK_PERMISSIONS_DATASTREAM: dict[str, Any] = {
    "cluster": ["manage_index_templates", "manage_ilm", "monitor"],
    "index": [
        {
            "names": [
                "metrics-homeassistant.*",
            ],
            "privileges": [
                "manage",
                "index",
                "create_index",
                "create",
            ],
        },
    ],
}


class StateChangeType(Enum):
    """Elasticsearch State Change Types constants."""

    STATE = "STATE"
    ATTRIBUTE = "ATTRIBUTE"
    NO_CHANGE = "POLLING"

    def to_publish_reason(self) -> str:
        """Return the publish reason for the state change type."""
        if self == StateChangeType.STATE:
            return PUBLISH_REASON_STATE_CHANGE
        if self == StateChangeType.ATTRIBUTE:
            return PUBLISH_REASON_ATTR_CHANGE
        return PUBLISH_REASON_POLLING


class CAPABILITIES:
    """Elasticsearch CAPABILITIES constants."""

    MAJOR: str = "MAJOR"
    MINOR: str = "MINOR"
    BUILD_FLAVOR: str = "BUILD_FLAVOR"
    SERVERLESS: str = "SERVERLESS"
    OSS: str = "OSS"
    SUPPORTED: str = "SUPPORTED"
    TIMESERIES_DATASTREAM: str = "TIMESERIES_DATASTREAM"
    IGNORE_MISSING_COMPONENT_TEMPLATES: str = "IGNORE_MISSING_COMPONENT_TEMPLATES"
    DATASTREAM_LIFECYCLE_MANAGEMENT: str = "DATASTREAM_LIFECYCLE_MANAGEMENT"
    MAX_PRIMARY_SHARD_SIZE: str = "MAX_PRIMARY_SHARD_SIZE"


# BEGIN DEPRECATED CONFIG
CONF_HEALTH_SENSOR_ENABLED: str = "health_sensor_enabled"
CONF_ONLY_PUBLISH_CHANGED: str = "only_publish_changed"

VERSION_SUFFIX: str = "-v4_2"
DATASTREAM_METRICS_ILM_POLICY_NAME: str = DATASTREAM_TYPE + "-" + DATASTREAM_DATASET_PREFIX

LEGACY_TEMPLATE_NAME: str = "hass-index-template" + VERSION_SUFFIX

INDEX_MODE_LEGACY: str = "index"
INDEX_MODE_DATASTREAM: str = "datastream"


PUBLISH_MODE_ALL: str = "All"
PUBLISH_MODE_STATE_CHANGES: str = "State changes"
PUBLISH_MODE_ANY_CHANGES: str = "Any changes"

CONF_ILM_ENABLED: str = "ilm_enabled"
CONF_ILM_POLICY_NAME: str = "ilm_policy_name"
CONF_PUBLISH_MODE: str = "publish_mode"
CONF_INDEX_FORMAT: str = "index_format"
CONF_INDEX_MODE: str = "index_mode"
# END DEPRECATED CONFIG

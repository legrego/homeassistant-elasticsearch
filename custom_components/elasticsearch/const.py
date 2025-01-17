"""constants."""

from enum import Enum
from types import MappingProxyType
from typing import Any

DOMAIN: str = "elasticsearch"
ELASTIC_DOMAIN: str = "elasticsearch"

ELASTIC_MINIMUM_VERSION: tuple[int, int] = (8, 14)

CONF_PUBLISH_FREQUENCY: str = "publish_frequency"
CONF_POLLING_FREQUENCY: str = "polling_frequency"
CONF_AUTHENTICATION_TYPE: str = "authentication_type"

CONF_CHANGE_DETECTION_TYPE: str = "change_detection_type"

CONF_DEBUG_ATTRIBUTE_FILTERING: str = "debug_attribute_filtering"

CONF_INCLUDE_TARGETS: str = "include_targets"
CONF_EXCLUDE_TARGETS: str = "exclude_targets"

CONF_TARGETS_TO_INCLUDE: str = "targets_to_include"
CONF_TARGETS_TO_EXCLUDE: str = "targets_to_exclude"

CONF_SSL_VERIFY_HOSTNAME: str = "ssl_verify_hostname"
CONF_SSL_CA_PATH: str = "ssl_ca_path"

CONF_TAGS: str = "tags"

# For trimming keys with values that are None, empty lists, or empty objects
SKIP_VALUES = [None, [], {}]

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

ES_CHECK_PERMISSIONS_DATASTREAM: MappingProxyType[str, Any] = MappingProxyType(
    {
        "cluster": ["manage_index_templates", "monitor"],
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
)


class StateChangeType(Enum):
    """Elasticsearch State Change Types constants."""

    STATE = "state"
    ATTRIBUTE = "attribute"
    NO_CHANGE = "polling"

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

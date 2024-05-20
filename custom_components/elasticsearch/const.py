"""constants."""

DOMAIN = "elasticsearch"

CONF_PUBLISH_ENABLED = "publish_enabled"
CONF_INDEX_FORMAT = "index_format"

CONF_INDEX_MODE = "index_mode"

CONF_PUBLISH_FREQUENCY = "publish_frequency"
CONF_EXCLUDED_DOMAINS = "excluded_domains"
CONF_EXCLUDED_ENTITIES = "excluded_entities"
CONF_PUBLISH_MODE = "publish_mode"
CONF_INCLUDED_DOMAINS = "included_domains"
CONF_INCLUDED_ENTITIES = "included_entities"

CONF_ILM_ENABLED = "ilm_enabled"
CONF_ILM_POLICY_NAME = "ilm_policy_name"
CONF_SSL_CA_PATH = "ssl_ca_path"

# BEGIN DEPRECATED CONFIG
CONF_HEALTH_SENSOR_ENABLED = "health_sensor_enabled"
CONF_ONLY_PUBLISH_CHANGED = "only_publish_changed"
# END DEPRECATED CONFIG

CONF_TAGS = "tags"

ONE_MINUTE = 60
ONE_HOUR = 60 * 60

VERSION_SUFFIX = "-v4_2"

DATASTREAM_TYPE = "metrics"
DATASTREAM_DATASET_PREFIX = "homeassistant"
DATASTREAM_NAMESPACE = "default"

# Set to match the datastream prefix name
DATASTREAM_METRICS_INDEX_TEMPLATE_NAME = DATASTREAM_TYPE + "-" + DATASTREAM_DATASET_PREFIX
DATASTREAM_METRICS_ILM_POLICY_NAME = DATASTREAM_TYPE + "-" + DATASTREAM_DATASET_PREFIX

LEGACY_TEMPLATE_NAME = "hass-index-template" + VERSION_SUFFIX

PUBLISH_MODE_ALL = "All"
PUBLISH_MODE_STATE_CHANGES = "State changes"
PUBLISH_MODE_ANY_CHANGES = "Any changes"

PUBLISH_REASON_POLLING = "Polling"
PUBLISH_REASON_STATE_CHANGE = "State change"
PUBLISH_REASON_ATTR_CHANGE = "Attribute change"

INDEX_MODE_LEGACY = "index"
INDEX_MODE_DATASTREAM = "datastream"

ES_CHECK_PERMISSIONS_DATASTREAM = {
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
        }
    ],
}


class CAPABILITIES:
    """Elasticsearch CAPABILITIES constants."""

    MAJOR = "MAJOR"
    MINOR = "MINOR"
    BUILD_FLAVOR = "BUILD_FLAVOR"
    SERVERLESS = "SERVERLESS"
    OSS = "OSS"
    SUPPORTED = "SUPPORTED"
    TIMESERIES_DATASTREAM = "TIMESERIES_DATASTREAM"
    IGNORE_MISSING_COMPONENT_TEMPLATES = "IGNORE_MISSING_COMPONENT_TEMPLATES"
    DATASTREAM_LIFECYCLE_MANAGEMENT = "DATASTREAM_LIFECYCLE_MANAGEMENT"
    MAX_PRIMARY_SHARD_SIZE = "MAX_PRIMARY_SHARD_SIZE"

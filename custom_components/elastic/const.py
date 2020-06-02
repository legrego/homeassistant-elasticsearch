""" constants """

DOMAIN = 'elastic'

CONF_PUBLISH_ENABLED = 'publish_enabled'
CONF_HEALTH_SENSOR_ENABLED = 'health_sensor_enabled'
CONF_INDEX_FORMAT = 'index_format'
CONF_PUBLISH_FREQUENCY = 'publish_frequency'
CONF_ONLY_PUBLISH_CHANGED = 'only_publish_changed'
CONF_ILM_ENABLED = 'ilm_enabled'
CONF_ILM_POLICY_NAME = 'ilm_policy_name'
CONF_ILM_MAX_SIZE = 'ilm_max_size'
CONF_ILM_DELETE_AFTER = 'ilm_delete_after'
CONF_SSL_CA_PATH = 'ssl_ca_path'
CONF_CLOUD_ID = 'cloud_id'

CONF_TAGS = 'tags'

ONE_MINUTE = 60
ONE_HOUR = 60 * 60

VERSION_SUFFIX = "-v4_1"

INDEX_TEMPLATE_NAME = "hass-index-template" + VERSION_SUFFIX

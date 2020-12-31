from homeassistant.const import (
    CONF_URL,
    CONF_VERIFY_SSL,
    CONF_ALIAS,
    CONF_EXCLUDE,
    CONF_ENTITIES,
    CONF_DOMAINS,
)
from custom_components.elastic.const import (
    CONF_PUBLISH_ENABLED,
    CONF_HEALTH_SENSOR_ENABLED,
    CONF_ILM_ENABLED,
)

MOCK_LEGACY_CONFIG = {
    CONF_URL: "http://my-es:9200",
    CONF_PUBLISH_ENABLED: False,
    CONF_ILM_ENABLED: False,
    CONF_HEALTH_SENSOR_ENABLED: False,
    CONF_VERIFY_SSL: False,
    CONF_ALIAS: "my-alias",
    CONF_EXCLUDE: {
        CONF_ENTITIES: ["switch.my_switch"],
        CONF_DOMAINS: ["sensor", "weather"],
    },
}

CLUSTER_INFO_RESPONSE_BODY = {
    "name": "775d9437a770",
    "cluster_name": "home-assistant-cluster",
    "cluster_uuid": "hz1_5bImTh-45ERkrHS7vg",
    "version": {
        "number": "7.10.1",
        "build_flavor": "default",
        "build_type": "deb",
        "build_hash": "1c34507e66d7db1211f66f3513706fdf548736aa",
        "build_date": "2020-12-05T01:00:33.671820Z",
        "build_snapshot": False,
        "lucene_version": "8.7.0",
        "minimum_wire_compatibility_version": "6.8.0",
        "minimum_index_compatibility_version": "6.0.0-beta1",
    },
    "tagline": "You Know, for Search",
}

CLUSTER_HEALTH_RESPONSE_BODY = {
    "cluster_name": "home-assistant-cluster",
    "status": "green",
    "timed_out": False,
    "number_of_nodes": 1,
    "number_of_data_nodes": 1,
    "active_primary_shards": 0,
    "active_shards": 0,
    "relocating_shards": 0,
    "initializing_shards": 0,
    "unassigned_shards": 0,
    "delayed_unassigned_shards": 0,
    "number_of_pending_tasks": 0,
    "number_of_in_flight_fetch": 0,
    "task_max_waiting_in_queue_millis": 0,
    "active_shards_percent_as_number": 100.0,
}
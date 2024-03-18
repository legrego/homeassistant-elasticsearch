"""Test Constants."""

from homeassistant.const import (
    CONF_ALIAS,
    CONF_DOMAINS,
    CONF_ENTITIES,
    CONF_EXCLUDE,
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)

from custom_components.elasticsearch.const import (
    CONF_HEALTH_SENSOR_ENABLED,
    CONF_ILM_DELETE_AFTER,
    CONF_ILM_ENABLED,
    CONF_ILM_MAX_SIZE,
    CONF_ILM_POLICY_NAME,
    CONF_INDEX_FORMAT,
    CONF_ONLY_PUBLISH_CHANGED,
    CONF_PUBLISH_ENABLED,
    CONF_PUBLISH_FREQUENCY,
)

MOCK_MINIMAL_LEGACY_CONFIG = {
    CONF_URL: "http://my-es:9200",
}

MOCK_COMPLEX_LEGACY_CONFIG = {
    CONF_URL: "https://my-complex-es:9200",
    CONF_USERNAME: "username",
    CONF_PASSWORD: "changeme",
    CONF_TIMEOUT: 60,
    CONF_PUBLISH_ENABLED: True,
    CONF_PUBLISH_FREQUENCY: 1,
    CONF_ILM_ENABLED: True,
    CONF_ILM_DELETE_AFTER: "1d",
    CONF_ILM_MAX_SIZE: "1b",
    CONF_ILM_POLICY_NAME: "custom-policy-name",
    CONF_INDEX_FORMAT: "custom-index-format",
    CONF_HEALTH_SENSOR_ENABLED: True,
    CONF_VERIFY_SSL: False,
    CONF_ONLY_PUBLISH_CHANGED: True,
    CONF_ALIAS: "my-alias",
    CONF_EXCLUDE: {
        CONF_ENTITIES: ["switch.my_switch"],
        CONF_DOMAINS: ["sensor", "weather"],
    },
}

CLUSTER_INFO_MISSING_CREDENTIALS_RESPONSE_BODY = {
    "error": {
        "root_cause": [
            {
                "type": "security_exception",
                "reason": "missing authentication credentials for REST request [/?pretty]",
                "header": {
                    "WWW-Authenticate": [
                        'Basic realm="security" charset="UTF-8"',
                        'Bearer realm="security"',
                        "ApiKey",
                    ]
                },
            }
        ],
        "type": "security_exception",
        "reason": "missing authentication credentials for REST request [/?pretty]",
        "header": {
            "WWW-Authenticate": [
                'Basic realm="security" charset="UTF-8"',
                'Bearer realm="security"',
                "ApiKey",
            ]
        },
    },
    "status": 401,
}

CLUSTER_INFO_SERVERLESS_RESPONSE_BODY = {
    "name": "serverless",
    "cluster_name": "home-assistant-cluster",
    "cluster_uuid": "xtsjNokTQGClXbRibWjxyg",
    "version": {
        "number": "8.11.0",
        "build_flavor": "serverless",
        "build_type": "docker",
        "build_hash": "00000000",
        "build_date": "2023-10-31",
        "build_snapshot": False,
        "lucene_version": "9.7.0",
        "minimum_wire_compatibility_version": "8.11.0",
        "minimum_index_compatibility_version": "8.11.0",
    },
    "tagline": "You Know, for Search",
}

CLUSTER_INFO_8DOT8_RESPONSE_BODY = {
    "name": "775d9437a77088",
    "cluster_name": "home-assistant-cluster",
    "cluster_uuid": "xtsjNokTQGClXbRibWjxyg",
    "version": {
        "number": "8.8.0",
        "build_type": "docker",
        "build_hash": "00000000",
        "build_date": "2023-10-31",
        "build_snapshot": False,
        "lucene_version": "9.7.0",
        "minimum_wire_compatibility_version": "8.11.0",
        "minimum_index_compatibility_version": "8.11.0",
    },
    "tagline": "You Know, for Search",
}

CLUSTER_INFO_UNSUPPORTED_RESPONSE_BODY = {
    "name": "775d9437a770",
    "cluster_name": "home-assistant-cluster",
    "cluster_uuid": "hz1_5bImTh-45ERkrHS7vg",
    "version": {
        "number": "7.10.0",
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

CLUSTER_INFO_RESPONSE_BODY = {
    "name": "775d9437a770",
    "cluster_name": "home-assistant-cluster",
    "cluster_uuid": "hz1_5bImTh-45ERkrHS7vg",
    "version": {
        "number": "7.11.0",
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

"""Test Constants."""

from datetime import datetime

from custom_components.elasticsearch.const import (
    CONF_CHANGE_DETECTION_ENABLED,
    CONF_CHANGE_DETECTION_TYPE,
    CONF_EXCLUDE_TARGETS,
    CONF_INCLUDE_TARGETS,
    CONF_POLLING_FREQUENCY,
    CONF_PUBLISH_FREQUENCY,
    CONF_TAGS,
    CONF_TARGETS_TO_EXCLUDE,
    CONF_TARGETS_TO_INCLUDE,
    StateChangeType,
)
from homeassistant.components.counter import DOMAIN as COUNTER_DOMAIN
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)

TEST_DEVICE_AREA_NAME = "device area"
TEST_DEVICE_FLOOR_NAME = "device floor"
TEST_DEVICE_LABELS = ["device label 1", "device label 2", "device label 3"]

TEST_DEVICE_NAME = "device name"

TEST_ENTITY_DOMAIN = COUNTER_DOMAIN
TEST_ENTITY_AREA_ID = "entity_area"
TEST_ENTITY_AREA_NAME = "entity area"
TEST_ENTITY_FLOOR_NAME = "entity floor"
TEST_ENTITY_LABELS = ["entity label 1", "entity label 2", "entity label 3"]
TEST_ENTITY_PLATFORM = "entity platform"
TEST_ENTITY_DEVICE_CLASS = "entity device class"

TEST_ENTITY_STATE = "entity state"
TEST_ENTITY_STATE_FLOAT = "123.456"
TEST_ENTITY_STATE_INT = "123"
TEST_ENTITY_STATE_STRING = "abc123"
TEST_ENTITY_STATE_NONE = None
TEST_ENTITY_STATE_DATETIME = "2024-04-12T00:00:00+00:00"
TEST_ENTITY_STATE_DATE = "2024-04-12"
TEST_ENTITY_STATE_TIME = "00:00:00"
TEST_ENTITY_STATE_BOOLEAN = "True"
TEST_ENTITY_STATE_BOOLEAN_ON = "on"

TEST_ENTITY_STATE_ATTRIBUTES_INCLUDE = [
    {
        "string": "abc123",
        "int": 123,
        "float": 123.456,
        "list": [1, 2, 3, 4],
        "set": {5, 5},
        "tuple": (6, 6),
        "list_of_tuples": [(7, 7), (8, 8)],
        "list_of_sets": [{9, 9}, {10, 10}],
        "complex_dict": {
            "string": "abc123",
            "int": 123,
            "float": 123.456,
            "list": [1, 2, 3, 4],
            "set": {5, 5},
            "tuple": (6, 6),
            "list_of_tuples": [(7, 7), (8, 8)],
            "list_of_sets": [{9, 9}, {10, 10}],
            "another_dict": {
                "string": "abc123",
                "int": 123,
                "float": 123.456,
                "list": [1, 2, 3, 4],
                "set": {5, 5},
                "tuple": (6, 6),
                "list_of_tuples": [(7, 7), (8, 8)],
                "list_of_sets": [{9, 9}, {10, 10}],
            },
        },
        "none": None,
        "Collision Test": "first value",
        "collision_test": "second value",
        "*_Non ECS-Compliant    Attribute.ñame! 😀": True,
        "datetime": datetime(year=2024, month=4, day=12),
        "bool": True,
    }
]

TEST_ENTITY_STATE_ATTRIBUTES_EXCLUDE = [
    {
        "": "Key is empty, and should be excluded",
        "naughty": object(),
        datetime(year=2024, month=4, day=12): "Key is a datetime, and should be excluded",
        123: "Key is a number, and should be excluded",
        True: "Key is a bool, and should be excluded",
        "attribute is a function, and should be excluded": lambda x: x,
    }
]

TEST_ENTITY_STATE_ATTRIBUTES_ALL = [
    {
        **TEST_ENTITY_STATE_ATTRIBUTES_INCLUDE[0],
        **TEST_ENTITY_STATE_ATTRIBUTES_EXCLUDE[0],
    }
]

TEST_ENTITY_STATE_ATTRIBUTE_COMBINATION_FIELD_NAMES = ["attributes"]

TEST_ENTITY_STATE_ATTRIBUTE_COMBINATIONS = [
    TEST_ENTITY_STATE_ATTRIBUTES_INCLUDE,
    TEST_ENTITY_STATE_ATTRIBUTES_EXCLUDE,
    TEST_ENTITY_STATE_ATTRIBUTES_ALL,
]

TEST_ENTITY_STATE_ATTRIBUTE_COMBINATION_IDS = [
    "With compliant attributes",
    "With non-compliant attributes",
    "With compliant and non-compliant attributes",
]

TEST_ENTITY_OBJECT_ID_0 = "entity_object_id"
TEST_ENTITY_OBJECT_ID_1 = "entity_object_id_1"
TEST_ENTITY_OBJECT_ID_2 = "entity_object_id_2"
TEST_ENTITY_OBJECT_ID_3 = "entity_object_id_3"
TEST_ENTITY_OBJECT_ID_4 = "entity_object_id_4"
TEST_ENTITY_OBJECT_ID_5 = "entity_object_id_5"


TEST_CONFIG_ENTRY_DATA_URL = "https://mock_es_integration:9200"
TEST_CONFIG_ENTRY_DATA_URL_INSECURE = "http://mock_es_integration:9200"
TEST_CONFIG_ENTRY_DATA_USERNAME = "hass_writer"
TEST_CONFIG_ENTRY_DATA_PASSWORD = "changeme"
TEST_CONFIG_ENTRY_DATA_TIMEOUT = 30
TEST_CONFIG_ENTRY_DATA_VERIFY_SSL = False

TEST_CONFIG_ENTRY_BASE_DATA = {
    CONF_URL: TEST_CONFIG_ENTRY_DATA_URL,
    CONF_TIMEOUT: 30,
    CONF_VERIFY_SSL: False,
    CONF_USERNAME: "hass_writer",
    CONF_PASSWORD: "changeme",
}

TEST_CONFIG_ENTRY_BASE_OPTIONS = {
    CONF_CHANGE_DETECTION_ENABLED: False,
    CONF_CHANGE_DETECTION_TYPE: [],
    CONF_TAGS: [],
    CONF_POLLING_FREQUENCY: 0,
    CONF_PUBLISH_FREQUENCY: 0,
    CONF_INCLUDE_TARGETS: False,
    CONF_EXCLUDE_TARGETS: False,
    CONF_TARGETS_TO_INCLUDE: {},
    CONF_TARGETS_TO_EXCLUDE: {},
}


TEST_CONFIG_ENTRY_DEFAULT_OPTIONS = {
    CONF_CHANGE_DETECTION_ENABLED: True,
    CONF_CHANGE_DETECTION_TYPE: [StateChangeType.STATE.value, StateChangeType.ATTRIBUTE.value],
    CONF_TAGS: [],
    CONF_POLLING_FREQUENCY: 60,
    CONF_PUBLISH_FREQUENCY: 60,
    CONF_INCLUDE_TARGETS: False,
    CONF_EXCLUDE_TARGETS: False,
    CONF_TARGETS_TO_INCLUDE: {},
    CONF_TARGETS_TO_EXCLUDE: {},
}

TEST_CONFIG_ENTRY_FAST_PUBLISH_OPTIONS = {
    CONF_CHANGE_DETECTION_ENABLED: True,
    CONF_CHANGE_DETECTION_TYPE: [StateChangeType.STATE.value, StateChangeType.ATTRIBUTE.value],
    CONF_TAGS: [],
    CONF_POLLING_FREQUENCY: 2,
    CONF_PUBLISH_FREQUENCY: 2,
    CONF_INCLUDE_TARGETS: False,
    CONF_EXCLUDE_TARGETS: False,
    CONF_TARGETS_TO_INCLUDE: {},
    CONF_TARGETS_TO_EXCLUDE: {},
}

TEST_DEVICE_COMBINATION_FIELD_NAMES = (
    "device_name",
    "device_area_name",
    "device_floor_name",
    "device_labels",
)
TEST_DEVICE_COMBINATIONS = [
    (TEST_DEVICE_NAME, TEST_DEVICE_AREA_NAME, TEST_DEVICE_FLOOR_NAME, TEST_DEVICE_LABELS),
    (TEST_DEVICE_NAME, TEST_DEVICE_AREA_NAME, None, TEST_DEVICE_LABELS),
    (TEST_DEVICE_NAME, None, None, TEST_DEVICE_LABELS),
    (TEST_DEVICE_NAME, None, None, None),
    (None, None, None, None),
]
TEST_DEVICE_COMBINATION_IDS = [
    "With device",
    "With device no floor",
    "With device no area and floor",
    "With device no area, floor, or labels",
    "With no device",
]

TEST_ENTITY_COMBINATION_FIELD_NAMES = (
    "entity_object_id",
    "entity_area_name",
    "entity_floor_name",
    "entity_labels",
)
TEST_ENTITY_COMBINATIONS = [
    (TEST_ENTITY_OBJECT_ID_0, TEST_ENTITY_AREA_NAME, TEST_ENTITY_FLOOR_NAME, TEST_ENTITY_LABELS),
    (TEST_ENTITY_OBJECT_ID_0, TEST_ENTITY_AREA_NAME, None, TEST_ENTITY_LABELS),
    (TEST_ENTITY_OBJECT_ID_0, None, None, TEST_ENTITY_LABELS),
    (TEST_ENTITY_OBJECT_ID_0, None, None, None),
]

TEST_ENTITY_COMBINATION_IDS = [
    "With entity",
    "With entity no floor",
    "With entity no area and floor",
    "With entity no area, floor, or labels",
]

TEST_ENTITY_STATE_COMBINATIONS = [
    {
        "state": TEST_ENTITY_STATE,
        "attributes": {
            "string": "abc123",
            "int": 123,
            "float": 123.456,
        },
    }
]

MOCK_NOON_APRIL_12TH_2023 = "2023-04-12T12:00:00+00:00"

MOCK_LOCATION_SERVER = {
    "lat": 99.0,
    "lon": 99.0,
}

MOCK_LOCATION_DEVICE = {
    "lat": 44.0,
    "lon": 44.0,
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
                    ],
                },
            },
        ],
        "type": "security_exception",
        "reason": "missing authentication credentials for REST request [/?pretty]",
        "header": {
            "WWW-Authenticate": [
                'Basic realm="security" charset="UTF-8"',
                'Bearer realm="security"',
                "ApiKey",
            ],
        },
    },
    "status": 401,
}

CLUSTER_INFO_8DOT0_RESPONSE_BODY = {
    "name": "b33ad024a3eb",
    "cluster_name": "docker-cluster",
    "cluster_uuid": "0gTsD5juRwmRElXBCEfk6Q",
    "version": {
        "number": "8.0.0",
        "build_flavor": "default",
        "build_type": "docker",
        "build_hash": "1b6a7ece17463df5ff54a3e1302d825889aa1161",
        "build_date": "2022-02-03T16:47:57.507843096Z",
        "build_snapshot": False,
        "lucene_version": "9.0.0",
        "minimum_wire_compatibility_version": "7.17.0",
        "minimum_index_compatibility_version": "7.0.0",
    },
    "tagline": "You Know, for Search",
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

CLUSTER_INFO_8DOT11_RESPONSE_BODY = {
    "name": "640dcce4be79",
    "cluster_name": "docker-cluster",
    "cluster_uuid": "R-PPqCZYQTCMvkpGcyL4mA",
    "version": {
        "number": "8.11.0",
        "build_flavor": "default",
        "build_type": "docker",
        "build_hash": "d9ec3fa628c7b0ba3d25692e277ba26814820b20",
        "build_date": "2023-11-04T10:04:57.184859352Z",
        "build_snapshot": False,
        "lucene_version": "9.8.0",
        "minimum_wire_compatibility_version": "7.17.0",
        "minimum_index_compatibility_version": "7.0.0",
    },
    "tagline": "You Know, for Search",
}

CLUSTER_INFO_8DOT17_RESPONSE_BODY = {
    "name": "640dcce4be79",
    "cluster_name": "docker-cluster",
    "cluster_uuid": "R-PPqCZYQTCMvkpGcyL4mA",
    "version": {
        "number": "8.17.0",
        "build_flavor": "default",
        "build_type": "docker",
        "build_hash": "d9ec3fa628c7b0ba3d25692e277ba26814820b20",
        "build_date": "2023-11-04T10:04:57.184859352Z",
        "build_snapshot": False,
        "lucene_version": "9.8.0",
        "minimum_wire_compatibility_version": "7.17.0",
        "minimum_index_compatibility_version": "7.0.0",
    },
}
CLUSTER_INFO_8DOT14_RESPONSE_BODY = {
    "name": "640dcce4be79",
    "cluster_name": "docker-cluster",
    "cluster_uuid": "R-PPqCZYQTCMvkpGcyL4mA",
    "version": {
        "number": "8.14.0",
        "build_flavor": "default",
        "build_type": "docker",
        "build_hash": "d9ec3fa628c7b0ba3d25692e277ba26814820b20",
        "build_date": "2023-11-04T10:04:57.184859352Z",
        "build_snapshot": False,
        "lucene_version": "9.8.0",
        "minimum_wire_compatibility_version": "7.17.0",
        "minimum_index_compatibility_version": "7.0.0",
    },
}

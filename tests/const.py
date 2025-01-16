"""Test Constants."""

from datetime import UTC, datetime

from custom_components.elasticsearch.const import (
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

DEVICE_AREA_ID = "device_area"
DEVICE_AREA_NAME = "device area"
DEVICE_FLOOR_ID = "device_floor"
DEVICE_FLOOR_NAME = "device floor"
DEVICE_LABELS = ["device label 1", "device label 2", "device label 3"]
DEVICE_NO_LABELS = []
DEVICE_ID = "very_unique_device_id"
DEVICE_NAME = "device name"

ENTITY_DOMAIN = COUNTER_DOMAIN
ENTITY_OBJECT_ID = "entity_object_id"
ENTITY_ID = ENTITY_DOMAIN + "." + ENTITY_OBJECT_ID

ENTITY_AREA_ID = "entity_area"
ENTITY_AREA_NAME = "entity area"
ENTITY_FLOOR_ID = "entity_floor"
ENTITY_FLOOR_NAME = "entity floor"
ENTITY_LABELS = ["entity label 1", "entity label 2", "entity label 3"]
ENTITY_NO_LABELS = []
ENTITY_PLATFORM = "entity platform"
ENTITY_ORIGINAL_DEVICE_CLASS = "original entity device class"
ENTITY_DEVICE_CLASS = "user-modified entity device class"
ENTITY_ORIGINAL_NAME = "original entity name"
ENTITY_NAME = "user-modified entity name"
ENTITY_UNIT_OF_MEASUREMENT = "Mbit/s"

ENTITY_STATE_LAST_UPDATED = datetime(year=2024, month=4, day=12, hour=1)
ENTITY_STATE_LAST_CHANGED = datetime(year=2024, month=4, day=12, hour=2)

ENTITY_STATE_FLOAT = "123.456"
ENTITY_STATE_INT = "123"
ENTITY_STATE_STRING = "string state value"
ENTITY_STATE_NONE = None
ENTITY_STATE_DATETIME = "2024-04-12T00:00:00+00:00"
ENTITY_STATE_DATE = "2024-04-12"
ENTITY_STATE_TIME = "00:00:00"
ENTITY_STATE_BOOLEAN = "True"
ENTITY_STATE_BOOLEAN_ON = "on"
ENTITY_STATE_BOOLEAN_OFF = "off"

ENTITY_ATTRIBUTES_EMPTY = {}

ENTITY_ATTRIBUTES = {
    "string": "abc123",
    "int": 123,
    "float": 123.456,
}

ENTITY_ATTRIBUTES_COMPREHENSIVE = {
    **ENTITY_ATTRIBUTES,
    "list": [1, 4],
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

ENTITY_ATTRIBUTES_INVALID = {
    "": "Key is empty, and should be excluded",
    "naughty": object(),
    datetime(year=2024, month=4, day=12): "Key is a datetime, and should be excluded",
    123: "Key is a number, and should be excluded",
    True: "Key is a bool, and should be excluded",
    "attribute is a function, and should be excluded": lambda x: x,
}

ENTITY_ATTRIBUTES_WITH_INVALID = {**ENTITY_ATTRIBUTES, **ENTITY_ATTRIBUTES_INVALID}

ENTITY_STATE_ATTRIBUTE_COMBINATION_FIELD_NAMES = ["attributes"]

ENTITY_STATE_ATTRIBUTE_COMBINATIONS = [
    [ENTITY_ATTRIBUTES],
    [ENTITY_ATTRIBUTES_INVALID],
    [{**ENTITY_ATTRIBUTES_COMPREHENSIVE, **ENTITY_ATTRIBUTES_INVALID}],
]

ENTITY_STATE_ATTRIBUTE_COMBINATION_IDS = [
    "With sample compliant attributes",
    "With sample non-compliant attributes",
    "With comprehensive compliant and non-compliant attributes",
]

CONFIG_ENTRY_DATA_URL = "https://mock_es_integration:9200"
CONFIG_ENTRY_DATA_URL_INSECURE = "http://mock_es_integration:9200"
CONFIG_ENTRY_DATA_TIMEOUT = 30
CONFIG_ENTRY_DATA_VERIFY_SSL = False

CONFIG_ENTRY_DATA_USERNAME = "hass_writer"
CONFIG_ENTRY_DATA_PASSWORD = "changeme"

CONFIG_ENTRY_DATA_API_KEY = "1234567"


CONFIG_ENTRY_BASE_DATA = {CONF_URL: CONFIG_ENTRY_DATA_URL, CONF_TIMEOUT: 30, CONF_VERIFY_SSL: False}

CONFIG_ENTRY_DEFAULT_DATA = {
    **CONFIG_ENTRY_BASE_DATA,
    CONF_USERNAME: "hass_writer",
    CONF_PASSWORD: "changeme",
}

CONFIG_ENTRY_BASE_OPTIONS = {
    CONF_CHANGE_DETECTION_TYPE: [],
    CONF_TAGS: [],
    CONF_POLLING_FREQUENCY: 0,
    CONF_PUBLISH_FREQUENCY: 0,
    CONF_INCLUDE_TARGETS: False,
    CONF_EXCLUDE_TARGETS: False,
    CONF_TARGETS_TO_INCLUDE: {},
    CONF_TARGETS_TO_EXCLUDE: {},
}

CONFIG_ENTRY_DEFAULT_OPTIONS = {
    CONF_CHANGE_DETECTION_TYPE: [StateChangeType.STATE.value, StateChangeType.ATTRIBUTE.value],
    CONF_TAGS: [],
    CONF_POLLING_FREQUENCY: 60,
    CONF_PUBLISH_FREQUENCY: 60,
    CONF_INCLUDE_TARGETS: False,
    CONF_EXCLUDE_TARGETS: False,
    CONF_TARGETS_TO_INCLUDE: {},
    CONF_TARGETS_TO_EXCLUDE: {},
}

CONFIG_ENTRY_FAST_PUBLISH_OPTIONS = {
    CONF_CHANGE_DETECTION_TYPE: [StateChangeType.STATE.value, StateChangeType.ATTRIBUTE.value],
    CONF_TAGS: [],
    CONF_POLLING_FREQUENCY: 2,
    CONF_PUBLISH_FREQUENCY: 2,
    CONF_INCLUDE_TARGETS: False,
    CONF_EXCLUDE_TARGETS: False,
    CONF_TARGETS_TO_INCLUDE: {},
    CONF_TARGETS_TO_EXCLUDE: {},
}


def join_testing_matrix(first_matrix, second_matrix):
    """Join matrix into a list of dictionaries."""
    # argnames should be the same between the two matrices
    assert first_matrix[0] == second_matrix[0]

    # a testing matrix is an array of 4 elements: argnames, argvalues, False, ids
    # Joining two matrices is a simple operation: [argnames, join argvalues, False, join ids]

    argnames = first_matrix[0]

    # We will join the argvalues
    argvalues = [*first_matrix[1], *second_matrix[1]]

    # We will join the ids
    ids = first_matrix[3] + second_matrix[3]

    return [argnames, argvalues, False, ids]


DEVICE_MATRIX_SIMPLE = [
    ("device_name", "device_area_name", "device_floor_name", "device_labels"),
    [
        (DEVICE_NAME, DEVICE_AREA_NAME, DEVICE_FLOOR_NAME, DEVICE_LABELS),
        (DEVICE_NAME, None, None, DEVICE_NO_LABELS),
    ],
    False,
    [
        "Device with name, area, floor, and labels",
        "Device with name",
    ],
]

DEVICE_MATRIX_EXTRA = [
    ("device_name", "device_area_name", "device_floor_name", "device_labels"),
    [
        (DEVICE_NAME, None, None, DEVICE_LABELS),
        (DEVICE_NAME, DEVICE_AREA_NAME, None, DEVICE_NO_LABELS),
    ],
    False,
    [
        "Device with name, area and labels",
        "Device with name, area",
    ],
]

DEVICE_MATRIX_COMPREHENSIVE = join_testing_matrix(DEVICE_MATRIX_SIMPLE, DEVICE_MATRIX_EXTRA)

ENTITY_MATRIX_SIMPLE = [
    ("entity_area_name", "entity_floor_name", "entity_labels"),
    [
        (ENTITY_AREA_NAME, ENTITY_FLOOR_NAME, ENTITY_LABELS),
        (None, None, ENTITY_NO_LABELS),
    ],
    False,
    [
        "Entity with area, floor, and labels",
        "Entity with no area, floor, or labels",
    ],
]

ENTITY_MATRIX_EXTRA = [
    ("entity_area_name", "entity_floor_name", "entity_labels"),
    [
        (None, None, ENTITY_LABELS),
        (ENTITY_AREA_NAME, None, ENTITY_LABELS),
    ],
    False,
    [
        "Entity with labels",
        "Entity with area and labels",
    ],
]

ENTITY_MATRIX_COMPREHENSIVE = join_testing_matrix(ENTITY_MATRIX_SIMPLE, ENTITY_MATRIX_EXTRA)

ENTITY_STATE_MATRIX_SIMPLE = [
    (
        "entity_state_value",
        "entity_state_change_type",
        "entity_attributes",
    ),
    [
        (ENTITY_STATE_STRING, StateChangeType.STATE, ENTITY_ATTRIBUTES),
        (ENTITY_STATE_FLOAT, StateChangeType.STATE, {}),
    ],
    False,
    [
        "Update string state; with attributes",
        "Update float state; without attributes",
    ],
]

ENTITY_STATE_MATRIX_EXTRA = [
    (
        "entity_state_value",
        "entity_state_change_type",
        "entity_attributes",
    ),
    [
        (ENTITY_STATE_INT, StateChangeType.ATTRIBUTE, ENTITY_ATTRIBUTES_COMPREHENSIVE),
        (ENTITY_STATE_BOOLEAN, StateChangeType.NO_CHANGE, ENTITY_ATTRIBUTES_INVALID),
        (ENTITY_STATE_DATETIME, StateChangeType.NO_CHANGE, ENTITY_ATTRIBUTES_WITH_INVALID),
    ],
    False,
    [
        "With int state and comprehensive compliant attributes",
        "With boolean state and non-compliant attributes",
        "With datetime state and both compliant and non-compliant attributes",
    ],
]

ENTITY_STATE_MATRIX_COMPREHENSIVE = join_testing_matrix(ENTITY_STATE_MATRIX_SIMPLE, ENTITY_STATE_MATRIX_EXTRA)

MOCK_LOCATION_SERVER_LAT = 99.0
MOCK_LOCATION_SERVER_LON = -99.0

MOCK_LOCATION_DEVICE: dict[str, float] = {
    "lat": 44.0,
    "lon": 44.0,
}

MANAGER_STATIC_FIELDS = {
    "agent.version": "1.0.0",
    "host.architecture": "x86",
    "host.os.name": "Linux",
    "host.hostname": "my_es_host",
    "tags": ["tag1", "tag2"],
    "host.location": {
        "lat": MOCK_LOCATION_SERVER_LAT,
        "lon": MOCK_LOCATION_SERVER_LON,
    },
}

MOCK_NOON_APRIL_12TH_2023 = datetime(year=2023, month=4, day=12, hour=12, minute=0, second=0, tzinfo=UTC)

BULK_ERROR_RESPONSE_BODY = {
    "errors": True,
    "took": 0,
    "items": [
        {
            "create": {
                "_index": ".ds-metrics-homeassistant.counter-default-2025.01.12-000001",
                "_id": "90mKWJQB7GOvwEliFLmd",
                "status": 400,
                "error": {
                    "type": "document_parsing_exception",
                    "reason": "[1:1223] failed to parse: data stream timestamp field [@timestamp] is missing",
                    "caused_by": {
                        "type": "illegal_argument_exception",
                        "reason": "data stream timestamp field [@timestamp] is missing",
                    },
                },
            }
        }
    ],
}

BULK_SUCCESS_RESPONSE_BODY = {
    "errors": False,
    "took": 2004,
    "items": [
        {
            "create": {
                "_index": ".ds-metrics-homeassistant.counter-default-2025.01.12-000001",
                "_id": "oEmJWJQB7GOvwEliMbKW",
                "_version": 1,
                "result": "created",
                "_shards": {"total": 2, "successful": 1, "failed": 0},
                "_seq_no": 0,
                "_primary_term": 1,
                "status": 201,
            }
        }
    ],
}

XPACK_USAGE_SERVERLESS_RESPONSE_BODY = {
    "error": {
        "root_cause": [
            {
                "type": "api_not_available_exception",
                "reason": "Request for uri [/_xpack/usage?pretty=true] with method [GET] exists but is not available when running in serverless mode",
            }
        ],
        "type": "api_not_available_exception",
        "reason": "Request for uri [/_xpack/usage?pretty=true] with method [GET] exists but is not available when running in serverless mode",
    },
    "status": 410,
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

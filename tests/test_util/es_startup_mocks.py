"""ES Startup Mocks."""

from elasticsearch.const import DATASTREAM_DATASET_PREFIX, DATASTREAM_TYPE
from homeassistant.const import CONF_URL, CONTENT_TYPE_JSON
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.elasticsearch.config_flow import (
    DEFAULT_ALIAS,
    DEFAULT_ILM_POLICY_NAME,
    DEFAULT_INDEX_FORMAT,
)
from tests.const import (
    CLUSTER_HEALTH_RESPONSE_BODY,
    CLUSTER_INFO_7DOT11_RESPONSE_BODY,
    CLUSTER_INFO_7DOT17_RESPONSE_BODY,
    CLUSTER_INFO_8DOT0_RESPONSE_BODY,
    CLUSTER_INFO_8DOT8_RESPONSE_BODY,
    CLUSTER_INFO_8DOT11_RESPONSE_BODY,
    CLUSTER_INFO_RESPONSE_BODY,
    CLUSTER_INFO_SERVERLESS_RESPONSE_BODY,
    CLUSTER_INFO_UNSUPPORTED_RESPONSE_BODY,
    MOCK_COMPLEX_LEGACY_CONFIG,
)


# This is officially out of hand.
# We need a different mechanism for configuring the mock cluster for all of the different test scenarios.
def mock_es_initialization(
    aioclient_mock: AiohttpClientMocker,
    url=MOCK_COMPLEX_LEGACY_CONFIG.get(CONF_URL),
    mock_template_setup=True,
    mock_modern_template_setup=True,
    mock_modern_template_update=False,
    mock_modern_template_error=False,
    mock_template_update=False,
    mock_template_error=False,
    mock_index_creation=True,
    mock_health_check=True,
    mock_ilm_setup=True,
    mock_mapping_dynamic_strict=False,
    mock_mapping_dynamic_false=False,
    mock_serverless_version=False,
    mock_unsupported_version=False,
    mock_authentication_error=False,
    mock_legacy_index_authorization_error=False,
    mock_modern_datastream_authorization_error=False,
    mock_connection_error=False,
    mock_v88_cluster=False,
    mock_v80_cluster=False,
    mock_v711_cluster=False,
    mock_v717_cluster=False,
    mock_v811_cluster=False,
    alias_name=DEFAULT_ALIAS,
    index_format=DEFAULT_INDEX_FORMAT,
    ilm_policy_name=DEFAULT_ILM_POLICY_NAME,
):
    """Mock for ES initialization flow."""

    if mock_serverless_version:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_SERVERLESS_RESPONSE_BODY)
    elif mock_unsupported_version:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_UNSUPPORTED_RESPONSE_BODY)
    elif mock_authentication_error:
        aioclient_mock.get(url, status=401, json={"error": "unauthorized"})
    elif mock_connection_error:
        aioclient_mock.get(url, status=500, json={"error": "idk"})
    elif mock_v811_cluster:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_8DOT11_RESPONSE_BODY)
    elif mock_v88_cluster:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_8DOT8_RESPONSE_BODY)
    elif mock_v80_cluster:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_8DOT0_RESPONSE_BODY)
    elif mock_v711_cluster:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_7DOT11_RESPONSE_BODY)
    elif mock_v717_cluster:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_7DOT17_RESPONSE_BODY)
    else:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_RESPONSE_BODY)

    aioclient_mock.post(url + "/_bulk", status=200, json={"items": []})

    if mock_legacy_index_authorization_error:
        aioclient_mock.post(
            url + "/_security/user/_has_privileges",
            status=200,
            json={
                "username": "test_user",
                "has_all_requested": False,
                "cluster": {
                    "manage_index_templates": True,
                    "manage_ilm": True,
                    "monitor": True,
                },
                "index": {
                    f"{index_format}*": {
                        "manage": True,
                        "index": False,
                        "create_index": True,
                        "create": True,
                    },
                    f"{alias_name}*": {
                        "manage": True,
                        "index": True,
                        "create_index": True,
                        "create": True,
                    },
                    "all-hass-events": {
                        "manage": True,
                        "index": True,
                        "create_index": True,
                        "create": True,
                    },
                },
            },
        )
    elif mock_modern_datastream_authorization_error:
        aioclient_mock.post(
            url + "/_security/user/_has_privileges",
            status=200,
            json={
                "username": "test_user",
                "has_all_requested": False,
                "cluster": {
                    "manage_index_templates": True,
                    "manage_ilm": True,
                    "monitor": True,
                },
                "index": {
                    "metrics-homeassistant.*": {
                        "manage": True,
                        "index": True,
                        "create_index": True,
                        "create": False,
                    },
                },
            },
        )
    else:
        aioclient_mock.post(
            url + "/_security/user/_has_privileges",
            status=200,
            json={
                "username": "test_user",
                "has_all_requested": True,
                "cluster": {
                    "manage_index_templates": True,
                    "manage_ilm": True,
                    "monitor": True,
                },
                "index": {
                    f"{index_format}*": {
                        "manage": True,
                        "index": True,
                        "create_index": True,
                        "create": True,
                    },
                    f"{alias_name}*": {
                        "manage": True,
                        "index": True,
                        "create_index": True,
                        "create": True,
                    },
                    "all-hass-events": {
                        "manage": True,
                        "index": True,
                        "create_index": True,
                        "create": True,
                    },
                    "metrics-homeassistant.*": {
                        "manage": True,
                        "index": True,
                        "create_index": True,
                        "create": True,
                    },
                },
            },
        )

    if mock_modern_template_setup:
        aioclient_mock.get(
            url + "/_index_template/metrics-homeassistant",
            status=404,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={"error": "template missing"},
        )
        aioclient_mock.put(
            url + "/_index_template/metrics-homeassistant",
            status=200,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={"hi": "need dummy content"},
        )
    if mock_template_setup:
        aioclient_mock.get(
            url + "/_template/hass-index-template-v4_2",
            status=404,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={"error": "template missing"},
        )
        aioclient_mock.put(
            url + "/_template/hass-index-template-v4_2",
            status=200,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={"hi": "need dummy content"},
        )

    if mock_modern_template_update:
        aioclient_mock.get(
            url + "/_index_template/metrics-homeassistant",
            status=200,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={"index_templates": [{"name": "metrics-homeassistant"}]},
        )
        aioclient_mock.put(
            url + "/_index_template/metrics-homeassistant",
            status=200,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={"hi": "need dummy content"},
        )
    if mock_modern_template_error:
        # Return no templates and fail to update
        aioclient_mock.get(
            url + "/_index_template/metrics-homeassistant",
            status=404,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={
                "error": {
                    "root_cause": [
                        {
                            "type": "resource_not_found_exception",
                            "reason": "index template matching [metrics-homeassistant] not found",
                        }
                    ],
                    "type": "resource_not_found_exception",
                    "reason": "index template matching [metrics-homeassistant] not found",
                },
                "status": 404,
            },
        )
        aioclient_mock.put(
            url + "/_index_template/metrics-homeassistant",
            status=500,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={"hi": "need dummy content"},
        )

    if mock_template_update:
        aioclient_mock.get(
            url + "/_template/hass-index-template-v4_2",
            status=200,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={"hass-index-template-v4_2": {}},
        )
        aioclient_mock.put(
            url + "/_template/hass-index-template-v4_2",
            status=200,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={"hi": "need dummy content"},
        )
    if mock_template_error:
        # Return no templates and fail to update
        aioclient_mock.get(
            url + "/_template/hass-index-template-v4_2",
            status=404,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={},
        )
        aioclient_mock.put(
            url + "/_template/hass-index-template-v4_2",
            status=500,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={"hi": "need dummy content"},
        )

    if mock_index_creation:
        aioclient_mock.get(
            url + f"/_alias/{alias_name}-v4_2",
            status=404,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={"error": "alias missing"},
        )
        aioclient_mock.get(
            url + "/_cluster/health",
            status=200,
            headers={"content-type": CONTENT_TYPE_JSON},
            json=CLUSTER_HEALTH_RESPONSE_BODY,
        )

    if mock_health_check:
        aioclient_mock.put(
            url + f"/{index_format}-v4_2-000001",
            status=200,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={"hi": "need dummy content"},
        )

    if mock_ilm_setup:
        aioclient_mock.get(
            url + f"/_ilm/policy/{ilm_policy_name}",
            status=404,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={"error": "policy missing"},
        )
        aioclient_mock.put(
            url + f"/_ilm/policy/{ilm_policy_name}",
            status=200,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={"hi": "need dummy content"},
        )
        aioclient_mock.get(
            url + "/_ilm/policy",
            status=200,
            headers={"content-type": CONTENT_TYPE_JSON},
            json=[{"hi": "need dummy content"}],
        )

    if mock_mapping_dynamic_strict:
        aioclient_mock.get(
            url
            + f"/{DATASTREAM_TYPE + "-" + DATASTREAM_DATASET_PREFIX + ".*" + "/_mapping"}",
            status=200,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={
                ".ds-metrics-homeassistant.switch-default-2024.04.05-000002": {
                    "mappings": {
                        "dynamic": "strict",
                    },
                }
            },
        )
        aioclient_mock.put(
            url
            + f"/{DATASTREAM_TYPE + "-" + DATASTREAM_DATASET_PREFIX + ".*" + "/_mapping"}",
            status=200,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={"hi": "need dummy content"},
        )
    if mock_mapping_dynamic_false:
        aioclient_mock.get(
            url
            + f"/{DATASTREAM_TYPE + "-" + DATASTREAM_DATASET_PREFIX + ".*" + "/_mapping"}",
            status=200,
            headers={"content-type": CONTENT_TYPE_JSON},
            json={
                ".ds-metrics-homeassistant.switch-default-2024.04.05-000002": {
                    "mappings": {
                        "dynamic": "false",
                    },
                }
            },
        )

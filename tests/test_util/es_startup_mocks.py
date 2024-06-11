# type: ignore  # noqa: PGH003
"""ES Startup Mocks."""

from homeassistant.const import CONTENT_TYPE_JSON
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from tests.const import (
    CLUSTER_INFO_7DOT11_RESPONSE_BODY,
    CLUSTER_INFO_7DOT17_RESPONSE_BODY,
    CLUSTER_INFO_8DOT0_RESPONSE_BODY,
    CLUSTER_INFO_8DOT8_RESPONSE_BODY,
    CLUSTER_INFO_8DOT11_RESPONSE_BODY,
    CLUSTER_INFO_RESPONSE_BODY,
    CLUSTER_INFO_SERVERLESS_RESPONSE_BODY,
    CLUSTER_INFO_UNSUPPORTED_RESPONSE_BODY,
    MOCK_ELASTICSEARCH_URL,
)


# This is officially out of hand.
# We need a different mechanism for configuring the mock cluster for all of the different test scenarios.
def mock_es_initialization(  # noqa: PLR0912
    aioclient_mock: AiohttpClientMocker,
    url: str = MOCK_ELASTICSEARCH_URL,
    mock_modern_template_setup: bool = True,
    mock_modern_template_update: bool = False,
    mock_modern_template_error: bool = False,
    mock_serverless_version: bool = False,
    mock_unsupported_version: bool = False,
    mock_authentication_error: bool = False,
    mock_modern_datastream_authorization_error: bool = False,
    mock_connection_error: bool = False,
    mock_v88_cluster: bool = False,
    mock_v80_cluster: bool = False,
    mock_v711_cluster: bool = False,
    mock_v717_cluster: bool = False,
    mock_v811_cluster: bool = False,
):
    """Mock for ES initialization flow."""

    if mock_serverless_version:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_SERVERLESS_RESPONSE_BODY)
        aioclient_mock.request(url=url, method="HEAD", status=200)
    elif mock_unsupported_version:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_UNSUPPORTED_RESPONSE_BODY)
        aioclient_mock.request(url=url, method="HEAD", status=200)
    elif mock_authentication_error:
        aioclient_mock.get(url, status=401, json={"error": "unauthorized"})
    elif mock_connection_error:
        aioclient_mock.get(url, status=500, json={"error": "idk"})
    elif mock_v811_cluster:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_8DOT11_RESPONSE_BODY)
        aioclient_mock.request(url=url, method="HEAD", status=200)
    elif mock_v88_cluster:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_8DOT8_RESPONSE_BODY)
        aioclient_mock.request(url=url, method="HEAD", status=200)
    elif mock_v80_cluster:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_8DOT0_RESPONSE_BODY)
        aioclient_mock.request(url=url, method="HEAD", status=200)
    elif mock_v711_cluster:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_7DOT11_RESPONSE_BODY)
        aioclient_mock.request(url=url, method="HEAD", status=200)
    elif mock_v717_cluster:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_7DOT17_RESPONSE_BODY)
        aioclient_mock.request(url=url, method="HEAD", status=200)
    else:
        aioclient_mock.get(url, status=200, json=CLUSTER_INFO_RESPONSE_BODY)

        aioclient_mock.post(url + "/_bulk", status=200, json={"items": []})

    if mock_modern_datastream_authorization_error:
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
                        },
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

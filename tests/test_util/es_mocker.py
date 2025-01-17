"""Elasticsearch API Call Mocker."""

from __future__ import annotations

from http import HTTPStatus
from ssl import SSLCertVerificationError
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from aiohttp import client_exceptions
from custom_components.elasticsearch.const import DATASTREAM_METRICS_INDEX_TEMPLATE_NAME

# import custom_components.elasticsearch  # noqa: F401
# import custom_components.elasticsearch  # noqa: F401
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,  # noqa: F401  # noqa: F401
)
from pytest_homeassistant_custom_component.plugins import (  # noqa: F401  # noqa: F401
    aioclient_mock,
    skip_stop_scripts,
    snapshot,
    verify_cleanup,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from tests import const as testconst

if TYPE_CHECKING:
    from typing import Any


def self_signed_tls_error():
    """Return a self-signed certificate error."""
    connection_key = MagicMock()
    connection_key.host = "mock_es_integration"
    connection_key.port = 9200
    connection_key.is_ssl = True

    certificate_error = SSLCertVerificationError()
    certificate_error.verify_code = 19
    certificate_error.verify_message = "'self-signed certificate in certificate chain'"
    certificate_error.library = "SSL"
    certificate_error.reason = "CERTIFICATE_VERIFY_FAILED"
    certificate_error.strerror = "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain (_ssl.c:1000)"
    certificate_error.errno = 1

    return client_exceptions.ClientConnectorCertificateError(
        connection_key=connection_key, certificate_error=certificate_error
    )


class es_mocker:
    """Mock builder for Elasticsearch integration tests."""

    mocker: AiohttpClientMocker
    base_url: str = testconst.CONFIG_ENTRY_DATA_URL

    def __init__(self, mocker):
        """Initialize the mock builder."""
        self.mocker = mocker

    def reset(self):
        """Reset the mock builder."""
        self.mocker.clear_requests()

        return self

    def get_calls(self, include_headers=False):
        """Return the calls."""
        # each mock_call is a tuple of method, url, body, and headers

        if not include_headers:
            return [(method, url, body) for method, url, body, headers in self.mocker.mock_calls]

        return self.mocker.mock_calls

    def clear(self):
        """Clear the requests."""
        self.mocker.mock_calls.clear()

        return self

    def with_server_error(self, status=None, exc=None):
        """Mock Elasticsearch being unreachable."""
        if status is None and exc is None:
            self.mocker.get(f"{self.base_url}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

        if exc is None:
            self.mocker.get(f"{self.base_url}", status=status)
        else:
            self.mocker.get(f"{self.base_url}", exc=exc)

        return self

    def without_authentication(self):
        """Mock the user not being authenticated."""
        self.mocker.get(
            f"{self.base_url}",
            status=401,
            json=testconst.CLUSTER_INFO_MISSING_CREDENTIALS_RESPONSE_BODY,
        )
        return self

    def with_server_timeout(self):
        """Mock Elasticsearch being unreachable."""
        self.mocker.get(f"{self.base_url}", exc=client_exceptions.ServerTimeoutError())
        return self

    def _add_fail_after(
        self, success: AiohttpClientMockResponse, failure: AiohttpClientMockResponse, fail_after
    ):
        if fail_after is None:
            self.mocker.request(
                url=success.url,
                method=success.method,
                status=success.status,
                content=success.response,
                headers=success.headers,
                exc=success.exc,
            )
            return self

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= fail_after:
                return failure

            return success

        self.mocker.request(success.method, f"{success.url}", side_effect=side_effect)

        return self

    def _as_elasticsearch_stateful(
        self, version_response: dict[str, Any], with_security: bool = True, fail_after=None
    ) -> es_mocker:
        """Mock Elasticsearch version."""

        self.base_url = (
            testconst.CONFIG_ENTRY_DATA_URL if with_security else testconst.CONFIG_ENTRY_DATA_URL_INSECURE
        )

        self._add_fail_after(
            success=AiohttpClientMockResponse(
                method="GET",
                url=self.base_url,
                headers={"x-elastic-product": "Elasticsearch"},
                json=version_response,
            ),
            failure=AiohttpClientMockResponse(
                method="GET",
                url=self.base_url,
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            ),
            fail_after=fail_after,
        )

        self.mocker.get(
            url=f"{self.base_url}/_xpack/usage",
            json={
                "security": {"available": True, "enabled": with_security},
            },
        )

        return self

    def as_elasticsearch_8_0(self, with_security: bool = True) -> es_mocker:
        """Mock Elasticsearch 8.0."""
        return self._as_elasticsearch_stateful(testconst.CLUSTER_INFO_8DOT0_RESPONSE_BODY, with_security)

    def as_elasticsearch_8_17(self, with_security: bool = True, fail_after=None) -> es_mocker:
        """Mock Elasticsearch 8.17."""
        return self._as_elasticsearch_stateful(
            testconst.CLUSTER_INFO_8DOT17_RESPONSE_BODY, with_security, fail_after=fail_after
        )

    def as_elasticsearch_8_14(self, with_security: bool = True):
        """Mock Elasticsearch 8.14."""

        return self._as_elasticsearch_stateful(testconst.CLUSTER_INFO_8DOT14_RESPONSE_BODY, with_security)

    def as_fake_elasticsearch(self) -> es_mocker:
        """Mock a fake elasticsearch node response."""

        self.mocker.get(
            f"{self.base_url}",
            status=200,
            # No x-elastic-product header
            json=testconst.CLUSTER_INFO_8DOT14_RESPONSE_BODY,
        )

        return self

    def as_elasticsearch_serverless(self) -> es_mocker:
        """Mock Elasticsearch version."""

        self.base_url = testconst.CONFIG_ENTRY_DATA_URL

        self.mocker.get(
            f"{self.base_url}",
            status=200,
            json=testconst.CLUSTER_INFO_SERVERLESS_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
        )

        self.mocker.get(
            url=f"{self.base_url}/_xpack/usage",
            status=410,
            json=testconst.XPACK_USAGE_SERVERLESS_RESPONSE_BODY,
        )

        return self

    def with_incorrect_permissions(self):
        """Mock the user being properly authenticated."""
        self.mocker.post(
            f"{self.base_url}/_security/user/_has_privileges",
            status=200,
            json={
                "has_all_requested": False,
            },
        )

        return self

    def with_correct_permissions(self):
        """Mock the user being properly authenticated."""

        self.mocker.post(
            f"{self.base_url}/_security/user/_has_privileges",
            status=200,
            json={
                "has_all_requested": True,
            },
        )

        return self

    def with_selfsigned_certificate(self):
        """Mock a self-signed certificate error."""

        self.mocker.get(f"{self.base_url}", exc=self_signed_tls_error())

        return self

    def with_index_template(self, version=2):
        """Mock the user being properly authenticated."""

        # Mock index template setup
        self.mocker.get(
            f"{self.base_url}/_index_template/{DATASTREAM_METRICS_INDEX_TEMPLATE_NAME}",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={
                "index_templates": [{"name": "datastream_metrics", "index_template": {"version": version}}]
            },
        )

        return self

    def without_index_template(self):
        """Mock the user being properly authenticated."""

        # Mock index template setup
        self.mocker.get(
            f"{self.base_url}/_index_template/{DATASTREAM_METRICS_INDEX_TEMPLATE_NAME}",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={},
        )

        self.mocker.put(
            f"{self.base_url}/_index_template/{DATASTREAM_METRICS_INDEX_TEMPLATE_NAME}",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={},
        )
        return self

    def with_datastreams(self):
        """Mock the user being properly authenticated."""

        self.mocker.get(
            f"{self.base_url}/_data_stream/metrics-homeassistant.*",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={
                "data_streams": [
                    {
                        "name": "metrics-homeassistant.sensor-default",
                    },
                    {
                        "name": "metrics-homeassistant.counter-default",
                    },
                ]
            },
        )

        self.mocker.put(
            f"{self.base_url}/_data_stream/metrics-homeassistant.counter-default/_rollover",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={
                "acknowledged": True,
                "shards_acknowledged": True,
                "old_index": ".ds-metrics-homeassistant.counter-default-2024.12.19-000001",
                "new_index": ".ds-metrics-homeassistant.counter-default-2025.01.10-000002",
                "rolled_over": True,
                "dry_run": False,
                "lazy": False,
                "conditions": {},
            },
        )
        self.mocker.put(
            f"{self.base_url}/_data_stream/metrics-homeassistant.sensor-default/_rollover",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json={
                "acknowledged": True,
                "shards_acknowledged": True,
                "old_index": ".ds-metrics-homeassistant.sensor-default-2024.12.19-000001",
                "new_index": ".ds-metrics-homeassistant.sensor-default-2025.01.10-000002",
                "rolled_over": True,
                "dry_run": False,
                "lazy": False,
                "conditions": {},
            },
        )

        return self

    def respond_to_bulk_with_item_level_error(self):
        """Mock a bulk response with an item-level error."""

        self.mocker.put(
            f"{self.base_url}/_bulk",
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
            json=testconst.BULK_ERROR_RESPONSE_BODY,
        )

        return self

    def respond_to_bulk(self, status=200, fail_after=None):
        """Mock the user being properly authenticated."""

        self._add_fail_after(
            success=AiohttpClientMockResponse(
                method="PUT",
                url=f"{self.base_url}/_bulk",
                headers={"x-elastic-product": "Elasticsearch"},
                json=testconst.BULK_SUCCESS_RESPONSE_BODY,
            ),
            failure=AiohttpClientMockResponse(
                method="PUT",
                url=f"{self.base_url}/_bulk",
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            ),
            fail_after=fail_after,
        )

        return self

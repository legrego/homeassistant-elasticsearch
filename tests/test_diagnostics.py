"""Tests for the Elasticsearch integration diagnostics."""

from unittest import mock

import pytest
from custom_components.elasticsearch.diagnostics import async_get_config_entry_diagnostics, redact_url
from custom_components.elasticsearch.es_integration import ElasticIntegration
from homeassistant.const import (
    CONF_API_KEY,
    CONF_PASSWORD,
    CONF_URL,
    CONF_USERNAME,
)


@pytest.mark.parametrize(
    "data",
    [
        {
            CONF_URL: "https://example.com",
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_password",
            CONF_API_KEY: "test_api_key",
        },
        {
            CONF_URL: "https://example.com",
            CONF_USERNAME: "test_user",
        },
        {
            CONF_URL: "https://example.com",
        },
        {
            CONF_URL: "https://test_user:test_password@example.com:9200",
        },
    ],
    ids=["URL and all auth params", "Only URL and username", "Only URL", "Credentials in URL"],
)
@pytest.mark.parametrize("options", [{}])
async def test_async_get_config_entry_diagnostics(hass, config_entry, data, options, snapshot):
    """Test async_get_config_entry_diagnostics function."""

    result = await async_get_config_entry_diagnostics(hass, config_entry)

    assert result == snapshot


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com:9200", "https://example.com:9200"),
        ("https://user:pass@example.com:9200", "https://**REDACTED**:**REDACTED**@example.com:9200"),
        ("https://user@example.com:9200/path", "https://**REDACTED**@example.com:9200/path"),
        ("http://[::1:9200", "**REDACTED**"),
    ],
)
def test_redact_url(url, expected):
    """Test that credentials embedded in a URL are redacted."""
    assert redact_url(url) == expected


@pytest.mark.parametrize("data", [{CONF_URL: "https://example.com"}])
async def test_diagnostics_include_runtime_state(hass, config_entry):
    """Test that a loaded entry reports the state of its connection and queue."""
    integration = mock.MagicMock(spec=ElasticIntegration)
    integration.diagnostics.return_value = {"queue_size": 3}
    config_entry.runtime_data = integration

    result = await async_get_config_entry_diagnostics(hass, config_entry)

    assert result["runtime"] == {"queue_size": 3}


async def test_integration_diagnostics(hass, config_entry):
    """Test the runtime state an integration reports."""
    integration = ElasticIntegration(hass, config_entry)
    integration._gateway = mock.MagicMock(cluster_version="9.2.1", build_flavor="default", connected=True)
    integration._pipeline_manager.queue.put_nowait(mock.MagicMock())

    assert integration.diagnostics() == {
        "cluster": {"version": "9.2.1", "build_flavor": "default"},
        "connected": True,
        "queue_size": 1,
        "query_sensors": {},
    }

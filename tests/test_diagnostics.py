"""Tests for the Elasticsearch integration diagnostics."""

import pytest
from custom_components.elasticsearch.diagnostics import async_get_config_entry_diagnostics
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
    ],
    ids=["URL and all auth params", "Only URL and username", "Only URL"],
)
@pytest.mark.parametrize("options", [{}])
async def test_async_get_config_entry_diagnostics(hass, config_entry, data, options, snapshot):
    """Test async_get_config_entry_diagnostics function."""

    result = await async_get_config_entry_diagnostics(hass, config_entry)

    assert result == snapshot

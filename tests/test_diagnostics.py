"""Tests for the Elasticsearch integration diagnostics."""

import pytest
from custom_components.elasticsearch.diagnostics import async_get_config_entry_diagnostics


@pytest.mark.parametrize(
    "data",
    [
        {
            "url": "https://example.com",
            "username": "test_user",
            "password": "test_password",
            "api_key": "test_api_key",
        },
        {
            "url": "https://example.com",
            "username": "test_user",
        },
        {
            "url": "https://example.com",
        },
    ],
    ids=["URL and all auth params", "Only URL and username", "Only URL"],
)
async def test_async_get_config_entry_diagnostics(
    hass,
    mock_config_entry,
    data,
    snapshot,
):
    """Test async_get_config_entry_diagnostics function."""

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert result == snapshot

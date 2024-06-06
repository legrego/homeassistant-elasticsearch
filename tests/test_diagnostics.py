"""Tests for the Elasticsearch integration diagnostics."""

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.json import JSONSnapshotExtension

from custom_components.elasticsearch.diagnostics import async_get_config_entry_diagnostics


@pytest.fixture(autouse=True)
def snapshot(snapshot: SnapshotAssertion):
    """Provide a pre-configured snapshot object."""

    return snapshot.with_defaults(extension_class=JSONSnapshotExtension)


async def test_async_get_config_entry_diagnostics(hass: HomeAssistant, snapshot: SnapshotAssertion):
    """Test async_get_config_entry_diagnostics function."""
    entry = MockConfigEntry(
        entry_id="test_entry",
        domain="elasticsearch",
        title="Test Entry",
        data={
            "url": "https://example.com",
            "username": "test_user",
            "password": "test_password",
            "api_key": "test_api_key",
        },
        options={},
    )

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result == snapshot

import asyncio
import functools as ft
import json
import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock, patch

import homeassistant.util.dt as date_util
from homeassistant import auth, config_entries
from homeassistant import core as ha
from homeassistant.auth import auth_store
from homeassistant.const import EVENT_HOMEASSISTANT_CLOSE
from homeassistant.helpers import storage
from homeassistant.util.unit_system import METRIC_SYSTEM

""" Functions here have been cobbled together from various sources, including: hacs, home-assistant """

TOKEN = "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
INSTANCES = []


class MockConfigEntry(config_entries.ConfigEntry):
    """Helper for creating config entries that adds some defaults."""

    def __init__(
        self,
        *,
        domain="test",
        data=None,
        version=1,
        entry_id=None,
        source=config_entries.SOURCE_USER,
        title="Mock Title",
        state=None,
        options={},
        system_options={},
        connection_class=config_entries.CONN_CLASS_UNKNOWN,
        unique_id=None,
    ):
        """Initialize a mock config entry."""
        kwargs = {
            "entry_id": entry_id or uuid.uuid4().hex,
            "domain": domain,
            "data": data or {},
            "system_options": system_options,
            "options": options,
            "version": version,
            "title": title,
            "connection_class": connection_class,
            "unique_id": unique_id,
        }
        if source is not None:
            kwargs["source"] = source
        if state is not None:
            kwargs["state"] = state
        super().__init__(**kwargs)

    def add_to_hass(self, hass):
        """Test helper to add entry to hass."""
        hass.config_entries._entries.append(self)

    def add_to_manager(self, manager):
        """Test helper to add entry to entry manager."""
        manager._entries.append(self)


# pylint: disable=protected-access
async def async_test_home_assistant(loop, tmpdir):
    """Return a Home Assistant object pointing at test config dir."""
    hass = ha.HomeAssistant()
    store = auth_store.AuthStore(hass)
    hass.auth = auth.AuthManager(hass, store, {}, {})
    ensure_auth_manager_loaded(hass.auth)
    INSTANCES.append(hass)

    orig_async_add_job = hass.async_add_job
    orig_async_add_executor_job = hass.async_add_executor_job
    orig_async_create_task = hass.async_create_task

    def async_add_job(target, *args):
        """Add job."""
        check_target = target
        while isinstance(check_target, ft.partial):
            check_target = check_target.func

        if isinstance(check_target, Mock) and not isinstance(target, AsyncMock):
            fut = asyncio.Future()
            fut.set_result(target(*args))
            return fut

        return orig_async_add_job(target, *args)

    def async_add_executor_job(target, *args):
        """Add executor job."""
        check_target = target
        while isinstance(check_target, ft.partial):
            check_target = check_target.func

        if isinstance(check_target, Mock):
            fut = asyncio.Future()
            fut.set_result(target(*args))
            return fut

        return orig_async_add_executor_job(target, *args)

    def async_create_task(coroutine):
        """Create task."""
        if isinstance(coroutine, Mock) and not isinstance(coroutine, AsyncMock):
            fut = asyncio.Future()
            fut.set_result(None)
            return fut

        return orig_async_create_task(coroutine)

    hass.async_add_job = async_add_job
    hass.async_add_executor_job = async_add_executor_job
    hass.async_create_task = async_create_task

    hass.config.location_name = "test home"
    hass.config.config_dir = tmpdir
    hass.config.latitude = 32.87336
    hass.config.longitude = -117.22743
    hass.config.elevation = 0
    hass.config.time_zone = date_util.get_time_zone("US/Pacific")
    hass.config.units = METRIC_SYSTEM
    hass.config.skip_pip = True
    hass.data = {"custom_components": {}}

    hass.config_entries = config_entries.ConfigEntries(hass, {})
    hass.config_entries._entries = []
    hass.config_entries._store._async_ensure_stop_listener = lambda: None

    hass.state = ha.CoreState.running

    # Mock async_start
    orig_start = hass.async_start

    async def mock_async_start():
        """Start the mocking."""
        # We only mock time during tests and we want to track tasks
        with patch("homeassistant.core._async_create_timer"), patch.object(
            hass, "async_stop_track_tasks"
        ):
            await orig_start()

    hass.async_start = mock_async_start

    @ha.callback
    def clear_instance(event):
        """Clear global instance."""
        INSTANCES.remove(hass)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_CLOSE, clear_instance)

    return hass


@ha.callback
def ensure_auth_manager_loaded(auth_mgr):
    """Ensure an auth manager is considered loaded."""
    store = auth_mgr._store
    if store._users is None:
        store._set_defaults()


@contextmanager
def mock_storage(data=None):
    """Mock storage.
    Data is a dict {'key': {'version': version, 'data': data}}
    Written data will be converted to JSON to ensure JSON parsing works.
    """
    if data is None:
        data = {}

    orig_load = storage.Store._async_load

    async def mock_async_load(store):
        """Mock version of load."""
        if store._data is None:
            # No data to load
            if store.key not in data:
                return None

            mock_data = data.get(store.key)

            if "data" not in mock_data or "version" not in mock_data:
                raise ValueError('Mock data needs "version" and "data"')

            store._data = mock_data

        # Route through original load so that we trigger migration
        loaded = await orig_load(store)
        return loaded

    def mock_write_data(store, path, data_to_write):
        """Mock version of write data."""
        # To ensure that the data can be serialized
        data[store.key] = json.loads(json.dumps(data_to_write, cls=store._encoder))

    async def mock_remove(store):
        """Remove data."""
        data.pop(store.key, None)

    with patch(
        "homeassistant.helpers.storage.Store._async_load",
        side_effect=mock_async_load,
        autospec=True,
    ), patch(
        "homeassistant.helpers.storage.Store._write_data",
        side_effect=mock_write_data,
        autospec=True,
    ), patch(
        "homeassistant.helpers.storage.Store.async_remove",
        side_effect=mock_remove,
        autospec=True,
    ):
        yield data

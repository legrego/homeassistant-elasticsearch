"""Global fixtures for elastic integration."""
# Fixtures allow you to replace functions with a Mock object. You can perform
# many options via the Mock to reflect a particular behavior from the original
# function that you want to see without going through the function's actual logic.
# Fixtures can either be passed into tests as parameters, or if autouse=True, they
# will automatically be used across all tests.
#
# Fixtures that are defined in conftest.py are available across all tests. You can also
# define fixtures within a particular test file to scope them locally.
#
# pytest_homeassistant_custom_component provides some fixtures that are provided by
# Home Assistant core. You can find those fixture definitions here:
# https://github.com/MatthewFlamm/pytest-homeassistant-custom-component/blob/master/pytest_homeassistant_custom_component/common.py
#
# See here for more info: https://docs.pytest.org/en/latest/fixture.html (note that
# pytest includes fixtures OOB which you can use as defined on this page)

from asyncio import get_running_loop
from contextlib import contextmanager
from datetime import datetime
from unittest import mock
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

pytest_plugins = "pytest_homeassistant_custom_component"


@contextmanager
def mock_es_aiohttp_client():
    """Context manager to mock aiohttp client."""
    mocker = AiohttpClientMocker()

    def create_session(*args, **kwargs):
        print(args)
        session = mocker.create_session(get_running_loop())

        return session

    with mock.patch(
        "elasticsearch7._async.http_aiohttp.aiohttp.ClientSession",
        side_effect=create_session,
    ):
        yield mocker


@pytest.fixture
def es_aioclient_mock():
    """Fixture to mock aioclient calls."""
    with mock_es_aiohttp_client() as mock_session:
        yield mock_session


# This fixture enables loading custom integrations in all tests.
# Remove to enable selective use of this fixture
@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Auto enable custom integrations."""
    yield


# This fixture is used to prevent HomeAssistant from attempting to create and dismiss persistent
# notifications. These calls would fail without this fixture since the persistent_notification
# integration is never loaded during a test.
@pytest.fixture(name="skip_notifications", autouse=True)
def skip_notifications_fixture():
    """Skip notification calls."""
    with (
        patch("homeassistant.components.persistent_notification.async_create"),
        patch("homeassistant.components.persistent_notification.async_dismiss"),
    ):
        yield


@pytest.fixture()
def mock_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock config entry and add it to hass."""
    entry = MockConfigEntry(title=None)
    entry.add_to_hass(hass)
    return entry


class MockEntityState(State):
    """Mock entity state."""

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        state: str,
        attributes: map | None = None,
        last_changed: datetime | None = None,
        last_updated: datetime | None = None,
        validate_entity_id: bool | None = False,
    ):
        """Initialize the mock entity state."""

        if last_changed is None:
            last_changed = datetime.now()

        if last_updated is None:
            last_updated = datetime.now()

        self.hass = hass

        super().__init__(
            entity_id=entity_id,
            state=state,
            attributes=attributes,
            last_changed=last_changed,
            last_updated=last_updated,
            validate_entity_id=validate_entity_id,
        )

    def as_dict(self):
        """Return a dict representation of the State.

        Async friendly.

        To be used for JSON serialization.
        Ensures: state == State.from_dict(state.as_dict())
        """
        last_changed_isoformat = self.last_changed.isoformat()
        if self.last_changed == self.last_updated:
            last_updated_isoformat = last_changed_isoformat
        else:
            last_updated_isoformat = self.last_updated.isoformat()
        return {
            "entity_id": self.entity_id,
            "state": self.state,
            "attributes": self.attributes,
            "last_changed": last_changed_isoformat,
            "last_updated": last_updated_isoformat,
        }

    def to_publish(self):
        """Return a dict to publish."""
        return {
            "entity_id": self.entity_id,
            "new_state": self.state,
            "attributes": self.attributes,
        }

    async def add_to_hass(self):
        """Add the state to Homeassistant."""
        self.hass.states.async_set(**(self.to_publish()))

        await self.hass.async_block_till_done()


def mock_entity_state(hass: HomeAssistant) -> MockEntityState:
    """Mock an entity state in the state machine."""

    state = MockEntityState()
    return state

"""Configure py.test."""
import asyncio

import pytest
from homeassistant.exceptions import ServiceNotFound
from homeassistant.runner import HassEventLoopPolicy
from tests.common import async_test_home_assistant
from tests.test_util.aiohttp import mock_aiohttp_client

UNIQUE_ID = "ABC123"

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio

asyncio.set_event_loop_policy(HassEventLoopPolicy(False))
# Disable fixtures overriding our beautiful policy
asyncio.set_event_loop_policy = lambda policy: None


@pytest.fixture
def aioclient_mock(hass):
    """Fixture to mock aioclient calls."""
    with mock_aiohttp_client(hass) as mock_session:
        yield mock_session


@pytest.fixture
def hass(event_loop, tmpdir):
    """Fixture to provide a test instance of Home Assistant."""

    def exc_handle(event_loop, context):
        """Handle exceptions by rethrowing them, which will fail the test."""
        # Most of these contexts will contain an exception, but not all.
        # The docs note the key as "optional"
        # See https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.call_exception_handler
        if "exception" in context:
            exceptions.append(context["exception"])
        else:
            exceptions.append(
                Exception(
                    "Received exception handler without exception, but with message: %s"
                    % context["message"]
                )
            )
        orig_exception_handler(event_loop, context)

    exceptions = []
    hass = event_loop.run_until_complete(async_test_home_assistant(event_loop, tmpdir))
    orig_exception_handler = event_loop.get_exception_handler()
    event_loop.set_exception_handler(exc_handle)

    yield hass

    event_loop.run_until_complete(hass.async_stop(force=True))
    for ex in exceptions:
        if isinstance(ex, (ServiceNotFound, FileExistsError)):
            continue
        raise ex

    # """Fixture to provide a test instance of Home Assistant."""

    # def exc_handle(loop, context):
    #     """Handle exceptions by rethrowing them, which will fail the test."""
    #     exceptions.append(context["exception"])
    #     orig_exception_handler(loop, context)

    # exceptions = []
    # hass_obj = event_loop.run_until_complete(
    #     async_test_home_assistant(event_loop, tmpdir)
    # )
    # orig_exception_handler = event_loop.get_exception_handler()
    # event_loop.set_exception_handler(exc_handle)

    # hass_obj.http = MagicMock()

    # yield hass_obj

    # event_loop.run_until_complete(hass_obj.async_stop(force=True))
    # for ex in exceptions:
    #     if isinstance(ex, (ServiceNotFound, FileExistsError)):
    #         continue
    #     raise ex

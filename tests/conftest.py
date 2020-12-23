"""Configure py.test."""
import asyncio
import pytest
from homeassistant.exceptions import ServiceNotFound
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.runner import HassEventLoopPolicy
from elasticsearch import Elasticsearch, AsyncElasticsearch

from unittest.mock import MagicMock, AsyncMock, patch
from tests.common import MockESConnection, async_test_home_assistant
from custom_components.elastic.es_gateway import ElasticsearchGateway

UNIQUE_ID = "ABC123"

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio

asyncio.set_event_loop_policy(HassEventLoopPolicy(False))
# Disable fixtures overriding our beautiful policy
asyncio.set_event_loop_policy = lambda policy: None


@pytest.fixture
def hass(event_loop, tmpdir):
    """Fixture to provide a test instance of Home Assistant."""

    def exc_handle(loop, context):
        """Handle exceptions by rethrowing them, which will fail the test."""
        exceptions.append(context["exception"])
        orig_exception_handler(loop, context)

    exceptions = []
    hass_obj = event_loop.run_until_complete(
        async_test_home_assistant(event_loop, tmpdir)
    )
    orig_exception_handler = event_loop.get_exception_handler()
    event_loop.set_exception_handler(exc_handle)

    hass_obj.http = MagicMock()

    yield hass_obj

    event_loop.run_until_complete(hass_obj.async_stop(force=True))
    for ex in exceptions:
        if isinstance(ex, (ServiceNotFound, FileExistsError)):
            continue
        raise ex

"""Tests for the es_publish_pipeline module."""

from datetime import UTC, datetime
from logging import Logger
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    CannotConnect,
    IndexingError,
)
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from custom_components.elasticsearch.es_publish_pipeline import (
    EventQueue,
    Pipeline,
    PipelineSettings,
    StateChangeType,
)
from elastic_transport import ApiResponseMeta
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Event, HomeAssistant, State
from homeassistant.helpers.entity_registry import RegistryEntry
from syrupy.assertion import SnapshotAssertion

from tests import const


@pytest.fixture(name="pipeline_settings")
def pipeline_settings_fixture():
    """Return a PipelineSettings instance."""
    return PipelineSettings(
        polling_frequency=60,
        publish_frequency=60,
        change_detection_type=[StateChangeType.STATE],
        tags=[],
        debug_attribute_filtering=True,
        include_targets=False,
        exclude_targets=False,
        included_areas=[],
        excluded_areas=[],
        included_labels=[],
        excluded_labels=[],
        included_devices=[],
        excluded_devices=[],
        included_entities=[],
        excluded_entities=[],
    )


def mock_api_response_meta(status_code=200):
    """Return a mock API response meta."""
    return ApiResponseMeta(
        status=status_code, headers=MagicMock(), http_version="1.1", duration=0.0, node=MagicMock()
    )


@pytest.fixture(name="mock_logger")
def mock_logger_fixture():
    """Return a mock logger instance."""
    return MagicMock(spec=Logger)


@pytest.fixture(name="mock_queue")
def mock_queue_fixture():
    """Return a mock queue instance."""
    return MagicMock(spec=EventQueue)


@pytest.fixture(name="queue")
def queue_fixture():
    """Return a mock queue instance."""
    return EventQueue()


@pytest.fixture(name="mock_gateway")
def mock_gateway_fixture():
    """Return a mock ElasticsearchGateway instance."""
    return MagicMock(spec=ElasticsearchGateway)


@pytest.fixture(name="mock_listener")
def mock_listener_fixture():
    """Return a mock Listener instance."""
    return AsyncMock(spec=Pipeline.Listener)


@pytest.fixture(name="listener")
def listener_fixture(hass, mock_queue, mock_filterer, mock_logger) -> Pipeline.Listener:
    """Return a Listener instance."""
    return Pipeline.Listener(hass=hass, filterer=mock_filterer, queue=mock_queue, log=mock_logger)


@pytest.fixture(name="mock_poller")
def mock_poller_fixture():
    """Return a mock Poller instance."""
    return AsyncMock(spec=Pipeline.Poller)


@pytest.fixture(name="poller")
async def poller_fixture(
    hass: HomeAssistant, pipeline_settings: PipelineSettings, mock_filterer, mock_queue, mock_logger
):
    """Return a Pipeline.Poller instance."""
    return Pipeline.Poller(
        hass=hass, settings=pipeline_settings, filterer=mock_filterer, queue=mock_queue, log=mock_logger
    )


@pytest.fixture(name="mock_filterer")
def mock_filterer_fixture():
    """Return a mock Filterer instance."""
    return AsyncMock(spec=Pipeline.Filterer)


@pytest.fixture(name="filterer")
def filterer_fixture(hass: HomeAssistant, pipeline_settings: PipelineSettings, mock_logger):
    """Return a Pipeline.Filterer instance."""
    return Pipeline.Filterer(hass=hass, settings=pipeline_settings, log=mock_logger)


@pytest.fixture(name="mock_formatter")
def mock_formatter_fixture():
    """Return a mock Formatter instance."""
    return AsyncMock(spec=Pipeline.Formatter)


@pytest.fixture(name="formatter")
def formatter_fixture(hass: HomeAssistant, pipeline_settings: PipelineSettings, mock_logger):
    """Return a Pipeline.Formatter instance."""
    return Pipeline.Formatter(hass=hass, settings=pipeline_settings, log=mock_logger)


@pytest.fixture(name="mock_publisher")
def mock_publisher_fixture():
    """Return a mock Publisher instance."""
    return AsyncMock(spec=Pipeline.Publisher)


@pytest.fixture(name="publisher")
def publisher_fixture(hass, mock_gateway, mock_manager, pipeline_settings, mock_logger):
    """Return a Publisher instance."""
    return Pipeline.Publisher(
        hass=hass, gateway=mock_gateway, manager=mock_manager, settings=pipeline_settings, log=mock_logger
    )


@pytest.fixture(name="manager")
async def manager_fixture(
    hass: HomeAssistant,
    pipeline_settings,
    mock_filterer,
    mock_listener,
    mock_poller,
    mock_publisher,
    mock_formatter,
    mock_gateway,
    mock_logger,
):
    """Return a Pipeline.Manager instance with mock components."""
    # patch the init methods for the listener, poller, formatter, and publisher to return mocks
    with (
        patch("custom_components.elasticsearch.es_publish_pipeline.Pipeline.Listener") as listener,
        patch("custom_components.elasticsearch.es_publish_pipeline.Pipeline.Poller") as poller,
        patch("custom_components.elasticsearch.es_publish_pipeline.Pipeline.Filterer") as filterer,
        patch("custom_components.elasticsearch.es_publish_pipeline.Pipeline.Formatter") as formatter,
        patch("custom_components.elasticsearch.es_publish_pipeline.Pipeline.Publisher") as publisher,
    ):
        listener.return_value = mock_listener
        poller.return_value = mock_poller
        filterer.return_value = mock_filterer
        formatter.return_value = mock_formatter
        publisher.return_value = mock_publisher

        manager = Pipeline.Manager(
            hass=hass, gateway=mock_gateway, settings=pipeline_settings, log=mock_logger
        )

    try:
        yield manager
    finally:
        manager.stop()


@pytest.fixture(name="mock_manager")
def mock_manager_fixture():
    """Return a mock Pipeline.Manager instance."""
    return MagicMock(spec=Pipeline.Manager)


class Test_Filterer:
    """Test the Pipeline.Filterer class."""

    async def test_filter_with_missing_entity(self, config_entry, entity_id, entity_state, filterer):
        """Test receiving an entity that we have not added to HomeAssistant by not including the entity fixture."""
        filterer._change_detection_type = [StateChangeType.STATE.value]

        assert filterer.passes_filter(entity_state, StateChangeType.STATE) is False

    @pytest.mark.parametrize(
        ("exclude_labels", "should_exclude_on_label"),
        [
            ([const.TEST_ENTITY_LABELS[0]], True),
            ([const.TEST_DEVICE_LABELS[0]], True),
            ([], False),
        ],
        ids=[
            "entity label excluded",
            "device label excluded",
            "entity and device label not excluded",
        ],
    )
    @pytest.mark.parametrize(
        ("exclude_areas", "should_exclude_on_area"),
        [([const.TEST_ENTITY_AREA_ID], True), ([], False)],
        ids=["area excluded", "area not excluded"],
    )
    @pytest.mark.parametrize(
        ("exclude_devices", "should_exclude_on_device"),
        [([const.TEST_DEVICE_ID], True), ([], False)],
        ids=["device excluded", "device not excluded"],
    )
    @pytest.mark.parametrize(
        ("exclude_entities", "should_exclude_on_entity"),
        [([const.TEST_ENTITY_ID_0], True), ([], False)],
        ids=["entity excluded", "entity not excluded"],
    )
    @pytest.mark.parametrize(
        "exclude_targets",
        [(True), (False)],
        ids=["exclusions enabled", "exclusions disabled"],
    )
    async def test_exclude_filter(
        self,
        config_entry,
        entity,
        entity_state,
        device,
        filterer,
        exclude_targets,
        exclude_entities,
        exclude_devices,
        exclude_areas,
        exclude_labels,
        should_exclude_on_entity,
        should_exclude_on_device,
        should_exclude_on_area,
        should_exclude_on_label,
    ):
        """Test filtering entities with various exclude targets."""
        filterer._change_detection_type = [StateChangeType.STATE.value]

        filterer._exclude_targets = exclude_targets
        filterer._excluded_entities = exclude_entities
        filterer._excluded_devices = exclude_devices
        filterer._excluded_areas = exclude_areas
        filterer._excluded_labels = exclude_labels

        if not exclude_targets:
            # If we are not excluding any targets, the filter should always pass
            assert filterer.passes_filter(entity_state, StateChangeType.STATE) is True
            return

        assert filterer.passes_filter(entity_state, StateChangeType.STATE) != (
            should_exclude_on_entity
            or should_exclude_on_device
            or should_exclude_on_area
            or should_exclude_on_label
        )

    @pytest.mark.parametrize(
        ("include_labels", "should_include_on_label"),
        [
            ([const.TEST_ENTITY_LABELS[0]], True),
            ([const.TEST_DEVICE_LABELS[0]], True),
            ([], False),
        ],
        ids=["entity label included", "device label included", "entity and device label not included"],
    )
    @pytest.mark.parametrize(
        ("include_areas", "should_include_on_area"),
        [([const.TEST_ENTITY_AREA_ID], True), ([], False)],
        ids=["area included", "area not included"],
    )
    @pytest.mark.parametrize(
        ("include_devices", "should_include_on_device"),
        [([const.TEST_DEVICE_ID], True), ([], False)],
        ids=["device included", "device not included"],
    )
    @pytest.mark.parametrize(
        ("include_entities", "should_include_on_entity"),
        [([const.TEST_ENTITY_ID_0], True), ([], False)],
        ids=["entity included", "entity not included"],
    )
    @pytest.mark.parametrize(
        "include_targets",
        [(True), (False)],
        ids=["inclusions enabled", "inclusions disabled"],
    )
    async def test_include_filter(
        self,
        config_entry,
        entity,
        entity_state,
        device,
        filterer,
        include_targets,
        include_entities,
        include_devices,
        include_areas,
        include_labels,
        should_include_on_entity,
        should_include_on_device,
        should_include_on_area,
        should_include_on_label,
    ):
        """Test filtering entities with various include targets."""
        filterer._change_detection_type = [StateChangeType.STATE.value]

        filterer._include_targets = include_targets
        filterer._included_entities = include_entities
        filterer._included_devices = include_devices
        filterer._included_areas = include_areas
        filterer._included_labels = include_labels

        if not include_targets:
            # If we are not including any targets, the filter should always pass
            assert filterer.passes_filter(entity_state, StateChangeType.STATE) is True
            return

        assert filterer.passes_filter(entity_state, StateChangeType.STATE) == (
            should_include_on_entity
            or should_include_on_device
            or should_include_on_area
            or should_include_on_label
        )

    @pytest.mark.parametrize(
        ("include_targets", "matches_include_targets", "passes_include"),
        [(True, True, True), (True, False, False), (False, False, True), (False, True, True)],
        ids=[
            "inclusion enabled; matches rules",
            "inclusion enabled; does not match rules",
            "inclusion disabled; everything matches",
            "inclusion disabled; rules ignored",
        ],
    )
    @pytest.mark.parametrize(
        ("exclude_targets", "matches_exclude_targets", "passes_exclude"),
        [(True, True, False), (True, False, True), (False, False, True), (False, True, True)],
        ids=[
            "exclusion enabled; matches rules",
            "exclusion enabled; does not match rules",
            "exclusion disabled; everything matches",
            "exclusion disabled; rules ignored",
        ],
    )
    async def test_include_exclude_filter(
        self,
        filterer,
        include_targets: bool,
        exclude_targets: bool,
        matches_exclude_targets: bool,
        matches_include_targets: bool,
        passes_include: bool,
        passes_exclude: bool,
    ):
        """Test filtering entities with various include and exclude targets."""
        filterer._passes_change_detection_type_filter = MagicMock(return_value=True)
        filterer._passes_entity_exists_filter = MagicMock(return_value=True)

        filterer._exclude_targets = exclude_targets
        filterer._include_targets = include_targets

        filterer._passes_exclude_targets = MagicMock(return_value=(not matches_exclude_targets))
        filterer._passes_include_targets = MagicMock(return_value=(matches_include_targets))

        should_pass = passes_include and passes_exclude

        assert filterer.passes_filter(State("light.living_room", "on"), StateChangeType.STATE) == should_pass

    async def test_change_detection_type_filter(self, filterer):
        """Test that a state changes are properly filtered according to the change detection type setting."""
        # Polling changes always pass the change detection filter
        filterer._change_detection_type = []
        assert filterer._passes_change_detection_type_filter(StateChangeType.NO_CHANGE) is True

        # Listener changes must match the change detection type
        filterer._change_detection_type = [StateChangeType.STATE.value]
        assert filterer._passes_change_detection_type_filter(StateChangeType.STATE) is True

        filterer._change_detection_type = [StateChangeType.ATTRIBUTE.value]
        assert filterer._passes_change_detection_type_filter(StateChangeType.ATTRIBUTE) is True

        filterer._change_detection_type = [StateChangeType.STATE.value, StateChangeType.ATTRIBUTE.value]
        assert filterer._passes_change_detection_type_filter(StateChangeType.STATE) is True

        filterer._change_detection_type = [StateChangeType.STATE.value]
        assert filterer._passes_change_detection_type_filter(StateChangeType.ATTRIBUTE) is False

        filterer._change_detection_type = [StateChangeType.ATTRIBUTE.value]
        assert filterer._passes_change_detection_type_filter(StateChangeType.STATE) is False


class Test_Manager:
    """Test the Pipeline.Manager class."""

    async def test_init(self, manager, pipeline_settings, snapshot: SnapshotAssertion):
        """Test the initialization of the manager."""

        assert manager._gateway is not None
        assert manager._hass is not None

        assert manager._listener is not None
        assert manager._poller is not None
        assert manager._filterer is not None
        assert manager._formatter is not None
        assert manager._publisher is not None

        assert manager._settings == pipeline_settings
        assert manager._static_fields == {}

    async def test_async_init(self, manager, config_entry, mock_loop_handler):
        """Test initialization of the manager and pipeline components."""
        manager._settings.tags = ["tag1", "tag2"]

        await manager.async_init(config_entry)

        assert manager._static_fields == {
            "agent.version": "1.0.0",
            "host.architecture": "x86",
            "host.os.name": "Linux",
            "host.hostname": "my_es_host",
            "tags": ["tag1", "tag2"],
            "host.location": {
                "lat": 1.0,
                "lon": -1.0,
            },
        }

        manager._listener.async_init.assert_awaited_once()
        manager._poller.async_init.assert_awaited_once_with(config_entry=config_entry)
        manager._publisher.async_init.assert_awaited_once_with(config_entry=config_entry)
        manager._formatter.async_init.assert_awaited_once_with(manager._static_fields)

    async def test_async_init_no_publish(self, manager, config_entry):
        """Test the initialization of the manager when publishing is disabled."""
        manager._settings.publish_frequency = 0

        await manager.async_init(config_entry)

        manager._listener.async_init.assert_not_called()
        manager._poller.async_init.assert_not_called()
        manager._publisher.async_init.assert_not_called()
        manager._formatter.async_init.assert_not_called()

        manager._logger.error.assert_called_once_with("No publish frequency set. Disabling publishing.")

    async def test_async_init_no_listening(self, manager, config_entry):
        """Test the initialization of the manager when we aren't asked to detect changes."""
        manager._settings.change_detection_type = []

        await manager.async_init(config_entry)

        manager._listener.async_init.assert_not_called()
        manager._poller.async_init.assert_awaited_once_with(config_entry=config_entry)
        manager._publisher.async_init.assert_awaited_once_with(config_entry=config_entry)
        manager._formatter.async_init.assert_awaited_once_with(manager._static_fields)

        manager._logger.warning.assert_called_once_with(
            "No change detection type set. Disabling change listener."
        )

    async def test_async_init_no_polling(self, manager, config_entry):
        """Test the initialization of the manager when we don't need to do entity polling."""
        manager._settings.polling_frequency = 0

        await manager.async_init(config_entry)

        manager._listener.async_init.assert_called_once()
        manager._poller.async_init.assert_not_called()
        manager._publisher.async_init.assert_awaited_once_with(config_entry=config_entry)
        manager._formatter.async_init.assert_awaited_once_with(manager._static_fields)
        manager._logger.warning.assert_called_once_with("No polling frequency set. Disabling polling.")

    async def test_sip_queue(self, manager):
        """Test the sip_queue method of the Pipeline.Manager class."""

        # Build a bus event to put onto the queue
        reason = StateChangeType.STATE
        old_state = State("light.light_1", "off")
        new_state = State("light.light_1", "on")
        event = Event(
            "state_changed",
            {
                "entity_id": "light.light_1",
                "old_state": old_state,
                "new_state": new_state,
                "attributes": {"brightness": 255},
            },
        )

        # Add the sample event to the queue
        manager._queue.put_nowait((event.time_fired, new_state, reason))

        # Sip queue and append to result using async list comprehension
        result = []
        [result.append(doc) async for doc in manager.sip_queue()]

        # Assert that the formatter was called
        manager._formatter.format.assert_called_once_with(event.time_fired, new_state, reason)

    async def test_sip_queue_and_format(self, manager, formatter, snapshot):
        """Test the sip_queue method of the Pipeline.Manager class."""

        # Swap out the formatter with a real formatter instance
        manager._formatter = formatter
        manager._formatter.format = MagicMock(wraps=manager._formatter.format)
        # We dont want to fully setup the entity for this test so we'll skip pulling in extended details
        manager._formatter._state_to_extended_details = MagicMock(return_value={})

        # Build a bus event to put onto the queue
        reason = StateChangeType.STATE
        old_state = State("light.light_1", "off")
        new_state = State("light.light_1", "on")
        event = Event(
            "state_changed",
            {
                "entity_id": "light.light_1",
                "old_state": old_state,
                "new_state": new_state,
                "attributes": {"brightness": 255},
            },
        )

        # Add the sample event to the queue
        manager._queue.put_nowait((event.time_fired, new_state, reason))

        # Sip queue and append to result using async list comprehension
        result = []
        [result.append(doc) async for doc in manager.sip_queue()]

        # Assert that the formatter was called
        manager._formatter.format.assert_called_once_with(event.time_fired, new_state, reason)

        # Assert that the result is as expected
        assert result == snapshot

    async def test_stop(self, manager):
        """Ensure that stopping the manager stops active listeners."""
        manager.stop()
        manager._listener.stop.assert_called_once()


class Test_Poller:
    """Test the Pipeline.Poller class."""

    class Test_Unit_Tests:
        """Run the unit tests of the Poller class."""

        async def test_init(self, poller: Pipeline.Poller):
            """Test the initialization of the Poller."""

            assert poller._hass is not None
            assert poller._queue is not None

        async def test_async_init(self, poller: Pipeline.Poller, config_entry):
            """Test the async initialization of the Poller."""
            with (
                patch("custom_components.elasticsearch.es_publish_pipeline.LoopHandler") as loop_handler,
            ):
                # Ensure we don't start a coroutine that never finishes
                loop_handler_instance = loop_handler.return_value
                loop_handler_instance.start = AsyncMock()
                loop_handler_instance.wait_for_first_run = AsyncMock()

                poller.poll = MagicMock()

                await poller.async_init(config_entry=config_entry)

                loop_handler.assert_called_once_with(
                    name="es_state_poll_loop",
                    func=poller.poll,
                    frequency=poller._settings.polling_frequency,
                    log=poller._logger,
                )

                loop_handler_instance.start.assert_called_once()

    class Test_Integration_Tests:
        """Run the integration tests of the Poller class."""

        @pytest.mark.parametrize(
            "states",
            [
                [],
                [State("light.living_room", "on")],
                [State("light.living_room", "on"), State("switch.living_room", "off")],
            ],
            ids=["No states", "One state", "Multiple states"],
        )
        async def test_poll(
            self,
            queue,
            poller: Pipeline.Poller,
            states: list[State],
            freeze_time: FrozenDateTimeFactory,
            snapshot: SnapshotAssertion,
        ):
            """Test polling for different quantities of states."""
            freeze_time.tick()  # use the fixture so it doesnt show type errors

            # Replace the mock queue with a real queue
            poller._queue = queue

            with patch.object(poller._hass, "states") as states_mock:
                states_mock.async_all = MagicMock(return_value=states)

                await poller.poll()

                states_mock.async_all.assert_called_once()

                if len(states) > 0:
                    assert not poller._queue.empty()

                queued_states: list[dict] = []

                while not poller._queue.empty():
                    timestamp, state, change_type = await poller._queue.get()
                    queued_states.append(
                        {
                            "timestamp": timestamp,
                            "state": state.state,
                            "entity_id": state.entity_id,
                            "change type": change_type.value,
                        },
                    )

                assert poller._queue.empty()

                assert len(queued_states) == len(states)

                assert queued_states == snapshot


class Test_Listener:
    """Test the Pipeline.Listener class."""

    @pytest.fixture(autouse=True, name="_mock_hass_bus")
    def _mock_hass_bus_fixture(self, hass):
        """Return a mock Hass Bus instance."""
        with (
            patch.object(hass, "bus"),
            patch.object(hass.bus, "async_listen"),
        ):
            yield

    async def test_init(self, hass, listener, mock_queue, mock_filterer):
        """Test the initialization of the Listener."""

        assert listener._hass == hass
        assert listener._queue == mock_queue
        assert listener._filterer == mock_filterer
        assert listener._cancel_listener is None

    async def test_listener_async_init(self, hass, listener):
        """Test the async initialization of the Listener."""
        await listener.async_init()

        hass.bus.async_listen.assert_called_once_with(
            "state_changed",
            listener._handle_event,
        )

    @pytest.mark.parametrize(
        ("event_type", "old_state", "new_state", "change_type"),
        [
            ("state_reported", None, "on", StateChangeType.STATE),
            ("state_changed", "off", "on", StateChangeType.STATE),
            ("state_changed", "off", "off", StateChangeType.ATTRIBUTE),
            ("state_changed", "off", None, None),
        ],
        ids=[
            "Initial state for entity",
            "State change for entity",
            "Attribute change for entity",
            "State removed for entity",
        ],
    )
    async def test_listener_handle_state(self, hass, listener, event_type, old_state, new_state, change_type):
        """Test handling a state_changed event."""
        event = Event(
            event_type,
            {
                "entity_id": "light.light_1",
                "old_state": State("light.light_1", old_state) if old_state else None,
                "new_state": State("light.light_1", new_state) if new_state else None,
                "attributes": {"brightness": 255},
            },
        )

        await listener._handle_event(event)

        if change_type is None:
            listener._queue.put_nowait.assert_not_called()
            return

        # Ensure listener events are filtered
        listener._filterer.passes_filter.assert_called_once_with(
            event.data["new_state"],
            change_type,
        )

        # Ensure the event was queued
        listener._queue.put_nowait.assert_called_once_with(
            (
                event.time_fired,
                event.data["new_state"],
                change_type,
            ),
        )


class Test_Publisher:
    """Test the Pipeline.Publisher class."""

    @pytest.fixture(name="mock_document")
    def mock_document_fixture(self):
        """Return a mock entity document without ES action metadata."""
        return {
            "data_stream.type": "metrics",
            "data_stream.dataset": "homeassistant.light",
            "data_stream.namespace": "default",
            "event": {
                "action": "State change",
            },
            "hass.entity": {
                "attributes": {"brightness": 255},
                "domain": "light",
                "id": "light.living_room",
                "value": "on",
                "valueas": {"boolean": True},
                "object.id": "living_room",
            },
        }

    def test_init(self, publisher, mock_gateway, mock_manager, pipeline_settings, mock_logger):
        """Test the initialization of the Publisher."""
        assert publisher._gateway == mock_gateway
        assert publisher._manager == mock_manager
        assert publisher._settings == pipeline_settings
        assert publisher._logger == mock_logger

    async def test_format_datastream_name(self, publisher):
        """Test formatting a datastream name."""
        datastream_type = "metrics"
        dataset = "homeassistant.light"
        namespace = "default"

        datastream_name = publisher._format_datastream_name(datastream_type, dataset, namespace)
        assert datastream_name == "metrics-homeassistant.light-default"

        # Now test the LRU Cache
        publisher._format_datastream_name.cache_clear()

        datastream_name = publisher._format_datastream_name(datastream_type, dataset, namespace)
        assert datastream_name == "metrics-homeassistant.light-default"

        assert publisher._format_datastream_name.cache_info().misses == 1

        datastream_name = publisher._format_datastream_name(datastream_type, dataset, namespace)
        assert datastream_name == "metrics-homeassistant.light-default"

        assert publisher._format_datastream_name.cache_info().hits == 1

    async def test_add_action_and_meta_data(self, publisher, mock_document):
        """Test converting document to an elasticsearch bulk action."""

        async def yield_doc():
            yield mock_document

        async for action in publisher._add_action_and_meta_data(iterable=yield_doc()):
            assert action == {
                "_op_type": "create",
                "_index": "metrics-homeassistant.light-default",
                "_source": mock_document,
            }

    class Test_Publishing:
        """Run the integration tests for publishing."""

        @pytest.fixture(autouse=True)
        def populate_documents(self, publisher, mock_document):
            """Populate the documents for publishing tests."""
            iterable = [mock_document, mock_document, mock_document]

            publisher._add_action_and_meta_data = MagicMock(side_effect=[iterable])

            return iterable

        async def test_publish(self, publisher, populate_documents):
            """Ensure publish translates to an ES Bulk action."""
            await publisher.publish()

            # Assert that the bulk method of the gateway was called with the correct arguments
            publisher._gateway.bulk.assert_called_once_with(
                actions=populate_documents,
            )

            assert publisher._manager.reload_config_entry.call_count == 0
            assert publisher._gateway.check_connection.call_count == 1

        @pytest.mark.parametrize(
            ("method", "side_effect", "message", "bulk_call_count", "reload_call_count"),
            [
                ("check_connection", [False], None, 0, 0),
                ("check_connection", AuthenticationRequired(), None, 0, 1),
                ("bulk", IndexingError(), "Indexing error in publishing loop.", 1, 0),
                ("bulk", CannotConnect(), "Connection error in publishing loop.", 1, 0),
                ("bulk", Exception(), "Unknown error while publishing documents.", 1, 0),
            ],
            ids=[
                "Check connection fails; skip bulk",
                "Check connection returns Authentication required; reload integration",
                "Bulk raises indexing error; log and continue",
                "Bulk raises CannotConnect; log and continue",
                "Bulk raises unknown error; log and continue",
            ],
        )
        async def test_publish_error_handling(
            self, publisher, method, side_effect, message, bulk_call_count, reload_call_count
        ):
            """Ensure we handle various errors gracefully."""
            with patch.object(publisher._gateway, method, side_effect=side_effect):
                await publisher.publish()

                publisher._logger.error.assert_called_once_with(message) if message else None

                assert publisher._gateway.bulk.call_count == bulk_call_count
                assert publisher._manager.reload_config_entry.call_count == reload_call_count

        async def test_publish_check_connection_fail(self, publisher):
            """Ensure that we avoid calling bulk if connection checking fails."""
            with patch.object(publisher._gateway, "check_connection", return_value=False):
                await publisher.publish()
                publisher._gateway.bulk.assert_not_called()

        async def test_publish_bulk_connection_error(self, publisher):
            """Ensure that we gracefully handle connection errors from the ES Bulk request."""
            with patch.object(publisher._gateway, "bulk", side_effect=CannotConnect):
                await publisher.publish()
                publisher._logger.error.assert_called_once_with("Connection error in publishing loop.")

        async def test_publish_unknown_error(self, publisher):
            """Ensure we gracefully handle unknown errors."""
            with patch.object(publisher._gateway, "bulk", side_effect=Exception):
                await publisher.publish()
                publisher._logger.error.assert_called_once_with("Unknown error while publishing documents.")

        async def test_publish_indexing_issue(self, publisher):
            """Ensure we gracefully handle indexing errors."""
            with patch.object(publisher._gateway, "bulk", side_effect=IndexingError):
                await publisher.publish()
                publisher._logger.error.assert_called_once_with("Indexing error in publishing loop.")

        async def test_publish_authentication_issue(self, publisher):
            """Ensure we attempt a reload of the config entry if we receive an AuthenticationRequired error."""
            with patch.object(publisher._gateway, "check_connection", side_effect=AuthenticationRequired):
                await publisher.publish()
                publisher._manager.reload_config_entry.assert_called_once()


class Test_Formatter:
    """Test the Pipeline.Formatter class."""

    class Test_Unit_Tests:
        """Run the unit tests of the Formatter class."""

        async def test_init(self, formatter):
            """Test the initialization of the Formatter."""
            assert formatter._extended_entity_details is not None
            assert formatter._static_fields == {}

        async def test_async_init(self, formatter):
            """Test the async initialization of the Formatter."""
            static_fields = {
                "agent.version": "1.0.0",
                "host.architecture": "x86",
                "host.os.name": "Linux",
                "host.hostname": "my_es_host",
            }

            await formatter.async_init(
                static_fields=static_fields,
            )

            assert formatter._static_fields == static_fields

        async def test_state_to_attributes(self, formatter):
            """Test converting a state to attributes."""
            state = State("light.living_room", "on", {"brightness": 255, "color_temp": 4000})
            attributes = formatter._state_to_attributes(state)
            assert attributes == {"brightness": 255, "color_temp": 4000}

        async def test_state_to_attributes_skip(self, formatter):
            """Test converting a state to attributes."""

            class CustomAttributeClass:
                def __init__(self) -> None:
                    self.field = "This class should be skipped, as it cannot be serialized."

            state = State(
                "light.living_room",
                "on",
                {
                    "brightness": 255,
                    "color_temp": 4000,
                    "friendly_name": "tomato",  # Skip, exists elsewhere
                    "not allowed": CustomAttributeClass(),  # Skip, type not allowed
                },
            )

            attributes = formatter._state_to_attributes(state)
            assert attributes == {"brightness": 255, "color_temp": 4000}

        async def test_state_to_attributes_duplicate_sanitize(self, formatter):
            """Test converting a state to attributes."""
            # Patch the logger and make sure we print a debug message

            with patch.object(formatter._logger, "warning") as warning:
                state = State(
                    "light.living_room",
                    "on",
                    {"brightness": 255, "color_temp": 4000, "color_temp!": 4000},
                )
                attributes = formatter._state_to_attributes(state)
                assert attributes == {"brightness": 255, "color_temp": 4000}
                warning.assert_called_once()

        async def test_state_to_attributes_objects(self, formatter, snapshot: SnapshotAssertion):
            """Test converting a state to attributes."""
            # Test attributes that are dicts, sets, and lists
            orig_attributes = {
                "brightness": 255,
                "color_temp": 4000,
                "colors": {"red"},  # Set
                "lights": ["lamp", "ceiling"],  # List
                "child": {"name": "Alice"},  # Dict
                "children": [{"name": "Alice"}],  # List of dicts
            }
            state = State("light.living_room", "on", orig_attributes)
            transformed_attributes = formatter._state_to_attributes(state)

            assert snapshot == {
                "orig_attributes": orig_attributes,
                "transformed_attributes": transformed_attributes,
            }

        async def test_state_to_coerced_value_string(self, formatter):
            """Test converting a state to a coerced value."""
            state = State("light.living_room", "tomato")
            coerced_value = formatter._state_to_coerced_value(state)
            assert coerced_value == {"string": "tomato"}

        async def test_state_to_coerced_value_boolean(self, formatter):
            """Test converting a state to a coerced value."""
            state = State("binary_sensor.motion", "on")
            coerced_value = formatter._state_to_coerced_value(state)
            assert coerced_value == {"boolean": True}

            state = State("binary_sensor.motion", "off")
            coerced_value = formatter._state_to_coerced_value(state)
            assert coerced_value == {"boolean": False}

        async def test_state_to_coerced_value_float(self, formatter):
            """Test converting a state to a coerced value."""
            state = State("sensor.temperature", "25.5")
            coerced_value = formatter._state_to_coerced_value(state)
            assert coerced_value == {"float": 25.5}

        async def test_state_to_coerced_value_float_fail(self, formatter):
            """Test converting a state to a coerced value."""
            # set state to infinity
            state = State("sensor.temperature", str(float("inf")))
            coerced_value = formatter._state_to_coerced_value(state)
            assert coerced_value == {"string": "inf"}

            # set state to nan
            state = State("sensor.temperature", str(float("nan")))
            coerced_value = formatter._state_to_coerced_value(state)
            assert coerced_value == {"string": "nan"}

        async def test_state_to_coerced_value_datetime(self, formatter):
            """Test converting a state to a coerced value."""
            state = State("sensor.last_updated", "2023-04-12T12:00:00Z")
            coerced_value = formatter._state_to_coerced_value(state)
            assert coerced_value == {
                "datetime": "2023-04-12T12:00:00+00:00",
                "date": "2023-04-12",
                "time": "12:00:00",
            }

        async def test_domain_to_datastream(self, formatter):
            """Test converting a state to a datastream."""
            datastream = formatter.domain_to_datastream(const.TEST_ENTITY_DOMAIN)
            assert datastream == {
                "data_stream.type": "metrics",
                "data_stream.dataset": f"homeassistant.{const.TEST_ENTITY_DOMAIN}",
                "data_stream.namespace": "default",
            }

    class Test_Integration_Tests:
        """Run the integration tests of the Formatter class."""

        async def test_state_to_extended_details(
            self,
            formatter,
            entity: RegistryEntry,
            entity_object_id,
            entity_area_name,
            entity_floor_name,
            entity_labels,
            device_name,
            device_area_name,
            device_floor_name,
            device_labels,
            snapshot,
        ):
            """Test converting a state to entity details."""
            state = State(
                entity_id=entity.entity_id,
                state="on",
                attributes={
                    "brightness": 255,
                    "latitude": 1.0,
                    "longitude": 1.0,
                },
            )

            entity_details = formatter._state_to_extended_details(state)

            assert entity_details["hass.entity.area.name"] == entity_area_name
            assert entity_details["hass.entity.area.floor.name"] == entity_floor_name
            assert entity_details["hass.entity.device.labels"] == device_labels
            assert entity_details["hass.entity.device.name"] == device_name
            assert entity_details["hass.entity.device.class"] == entity.original_device_class
            assert entity_details["hass.entity.labels"] == entity_labels
            assert entity_details["hass.entity.platform"] == entity.platform

            assert entity_details["hass.entity.location.lat"] == 1.0
            assert entity_details["hass.entity.location.lon"] == 1.0

            assert entity_details == snapshot

        async def test_state_to_extended_details_exception(
            self,
            formatter,
            snapshot,
        ):
            """Test converting a state to entity details."""
            state = State(entity_id="tomato.pancakes", state="on", attributes={"brightness": 255})

            with pytest.raises(ValueError):
                formatter._state_to_extended_details(state)

        @pytest.mark.parametrize(
            const.TEST_DEVICE_COMBINATION_FIELD_NAMES,
            const.TEST_DEVICE_COMBINATIONS,
            ids=const.TEST_DEVICE_COMBINATION_IDS,
        )
        @pytest.mark.parametrize(
            const.TEST_ENTITY_COMBINATION_FIELD_NAMES,
            const.TEST_ENTITY_COMBINATIONS,
            ids=const.TEST_ENTITY_COMBINATION_IDS,
        )
        @pytest.mark.parametrize(
            const.TEST_ENTITY_STATE_ATTRIBUTE_COMBINATION_FIELD_NAMES,
            const.TEST_ENTITY_STATE_ATTRIBUTE_COMBINATIONS,
            ids=const.TEST_ENTITY_STATE_ATTRIBUTE_COMBINATION_IDS,
        )
        async def test_format(
            self,
            formatter,
            entity,
            entity_object_id,
            entity_area_name,
            entity_floor_name,
            entity_domain: str,
            entity_labels,
            device_name,
            device_area_name,
            device_floor_name,
            device_labels,
            attributes: dict,
            freeze_time: FrozenDateTimeFactory,
            snapshot,
        ):
            """Test converting a state to entity details."""
            time = datetime.now(tz=UTC)
            state = State(entity_id=entity.entity_id, state="on", attributes=attributes)
            reason = StateChangeType.STATE

            document = formatter.format(time, state, reason)

            assert document["@timestamp"] == time.isoformat()

            assert document["data_stream.dataset"] == f"homeassistant.{entity.domain}"
            assert document["data_stream.type"] == "metrics"
            assert document["data_stream.namespace"] == "default"

            assert document["event.action"] == "State change"
            assert document["event.kind"] == "event"
            assert document["event.type"] == "change"

            assert document["hass.entity.friendly_name"] is not None
            assert document["hass.entity.domain"] == entity.domain
            assert document["hass.entity.id"] is not None
            assert document["hass.entity.object.id"] == entity_object_id
            assert document["hass.entity.value"] == "on"
            assert document["hass.entity.valueas"] == {"boolean": True}

            assert document["data_stream.namespace"] == "default"

            assert document == snapshot

        @pytest.mark.parametrize(
            "reason_type",
            [
                StateChangeType.STATE,
                StateChangeType.ATTRIBUTE,
                StateChangeType.NO_CHANGE,
            ],
            ids=[
                "state",
                "attribute",
                "no_change",
            ],
        )
        async def test_format_reason_types(
            self,
            formatter,
            entity,
            reason_type: StateChangeType,
            freeze_time: FrozenDateTimeFactory,
            snapshot,
        ):
            """Test converting a state to entity details."""
            time = datetime.now(tz=UTC)
            state = State(entity_id=entity.entity_id, state="on", attributes={"brightness": 255})
            reason = reason_type

            document = formatter.format(time, state, reason)

            assert document["event.action"] == reason_type.to_publish_reason()
            assert document["event.kind"] == "event"
            if reason_type == StateChangeType.NO_CHANGE:
                assert document["event.type"] == "info"
            else:
                assert document["event.type"] == "change"

            assert document == snapshot

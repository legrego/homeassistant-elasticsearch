"""Tests for the es_publish_pipeline module."""

from datetime import UTC, datetime
from queue import Queue
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Event, HomeAssistant, State
from homeassistant.util import dt as dt_util
from syrupy.assertion import SnapshotAssertion

from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from custom_components.elasticsearch.es_publish_pipeline import (
    EventQueue,
    Pipeline,
    PipelineSettings,
    StateChangeType,
)
from tests import const
from tests.const import MOCK_NOON_APRIL_12TH_2023


@pytest.fixture
def settings():
    """Return a PipelineSettings instance."""
    return PipelineSettings(
        included_entities=[],
        excluded_entities=[],
        included_domains=[],
        excluded_domains=[],
        change_detection_type=[],
        publish_frequency=60,
        polling_frequency=60,
    )


@pytest.fixture
def filterer(settings: PipelineSettings):
    """Return a Pipeline.Filterer instance."""

    return Pipeline.Filterer(settings=settings)


@pytest.fixture
def freeze_time(freezer: FrozenDateTimeFactory):
    """Freeze time so we can properly assert on payload contents."""

    frozen_time = dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023)
    if frozen_time is None:
        msg = "Invalid date string"
        raise ValueError(msg)

    freezer.move_to(frozen_time)

    return freezer


class Test_Filterer:
    """Test the Pipeline.Filterer class."""

    class Test_Integration_Tests:
        """Run the integration tests of the Filterer class."""

        def test_passes_filter_with_allowed_change_type_and_included_entity(self, filterer):
            """Test that a state change with an allowed change type and included entity passes the filter."""
            state = State("light.living_room", "on")
            filterer._change_detection_type = [StateChangeType.STATE.name]
            filterer._included_entities = ["light.living_room"]
            assert filterer.passes_filter(state, StateChangeType.STATE) is True

        def test_passes_filter_with_allowed_change_type_and_excluded_entity(self, filterer):
            """Test that a state change with an allowed change type and excluded entity does not pass the filter."""
            state = State("light.living_room", "on")
            filterer._change_detection_type = [StateChangeType.STATE.name]
            filterer._excluded_entities = ["light.living_room"]
            assert filterer.passes_filter(state, StateChangeType.STATE) is False

        def test_passes_filter_with_disallowed_change_type(self, filterer):
            """Test that a state change with an allowed change type and excluded entity does not pass the filter."""
            state = State("light.living_room", "on")
            filterer._change_detection_type = [StateChangeType.NO_CHANGE.name]
            filterer._excluded_entities = ["light.living_room"]
            assert filterer.passes_filter(state, StateChangeType.STATE) is False

    class Test_Unit_Tests:
        """Run the unit tests of the Filterer class."""

        def test_passes_entity_domain_filters_included_entity(self, filterer):
            """Test that a state change for an included entity passes the filter."""
            state = State("light.living_room", "on")
            filterer._included_entities = ["light.living_room"]
            assert filterer._passes_entity_domain_filters(state.entity_id, state.domain) is True

        def test_passes_entity_domain_filters_not_included_entity(self, filterer):
            """Test that a state change for an entity that doesnt match any filters."""
            state = State("switch.living_room", "on")
            filterer._included_entities = ["light.living_room"]
            assert filterer._passes_entity_domain_filters(state.entity_id, state.domain) is False

        def test_passes_entity_domain_filters_excluded_entity(self, filterer):
            """Test that a state change for an excluded entity does not pass the filter."""
            state = State("light.living_room", "on")
            filterer._excluded_entities = ["light.living_room"]
            assert filterer._passes_entity_domain_filters(state.entity_id, state.domain) is False

        def test_passes_entity_domain_filters_included_domain(self, filterer):
            """Test that a state change for an included domain passes the filter."""
            state = State("light.living_room", "on")
            filterer._included_domains = ["light"]
            assert filterer._passes_entity_domain_filters(state.entity_id, state.domain) is True

        def test_passes_entity_domain_filters_excluded_domain(self, filterer):
            """Test that a state change for an excluded domain does not pass the filter."""
            state = State("light.living_room", "on")
            filterer._excluded_domains = ["light"]
            assert filterer._passes_entity_domain_filters(state.entity_id, state.domain) is False

        def test_passes_entity_domain_filters_no_included_entities_or_domains(self, filterer):
            """Test that a state change passes the filter when no included entities or domains are specified."""
            state = State("light.living_room", "on")
            assert filterer._passes_entity_domain_filters(state.entity_id, state.domain) is True

        def test_passes_entity_domain_filters_no_included_entities_or_domains_with_excluded_entity(
            self,
            filterer,
        ):
            """Test that a state change does not pass the filter when no included entities or domains are specified and the entity is excluded."""
            state = State("light.living_room", "on")
            filterer._excluded_entities = ["light.living_room"]
            assert filterer._passes_entity_domain_filters(state.entity_id, state.domain) is False

        def test_passes_entity_domain_filters_no_included_entities_or_domains_with_excluded_domain(
            self,
            filterer,
        ):
            """Test that a state change does not pass the filter when no included entities or domains are specified and the domain is excluded."""
            state = State("light.living_room", "on")
            filterer._excluded_domains = ["light"]
            assert filterer._passes_entity_domain_filters(state.entity_id, state.domain) is False

        def test_passes_change_detection_type_filter_true(self, filterer):
            """Test that a state change with an allowed change type passes the filter."""
            filterer._change_detection_type = [StateChangeType.STATE.name]
            assert filterer._passes_change_detection_type_filter(StateChangeType.STATE) is True

            filterer._change_detection_type = [StateChangeType.NO_CHANGE.name]
            assert filterer._passes_change_detection_type_filter(StateChangeType.NO_CHANGE) is True

        def test_passes_change_detection_type_filter_false(self, filterer):
            """Test that a state change with an allowed change type passes the filter."""
            filterer._change_detection_type = [StateChangeType.ATTRIBUTE.name]
            assert filterer._passes_change_detection_type_filter(StateChangeType.STATE) is False


class Test_Manager:
    """Test the Pipeline.Manager class."""

    @pytest.fixture
    def manager(self, hass: HomeAssistant):
        """Return a Pipeline.Manager instance."""
        gateway = mock.Mock()
        settings = PipelineSettings(
            included_entities=[],
            excluded_entities=[],
            included_domains=[],
            excluded_domains=[],
            change_detection_type=[],
            publish_frequency=60,
            polling_frequency=60,
        )
        return Pipeline.Manager(hass=hass, gateway=gateway, settings=settings)

    class Test_Unit_Tests:
        """Run the unit tests of the Manager class."""

        def test_init(self, manager, snapshot: SnapshotAssertion):
            """Test the initialization of the manager."""

            assert manager._filterer is not None
            assert manager._formatter is not None
            assert manager._gateway is not None
            assert manager._hass is not None
            assert manager._listener is not None
            assert manager._poller is not None
            assert manager._publisher is not None

            assert {
                "settings": manager._settings.to_dict(),
                "static_fields": manager._static_fields,
            } == snapshot

        async def test_async_init(self, manager):
            """Test the async initialization of the manager."""
            config_entry = mock.Mock()
            manager._settings.change_detection_type = ["STATE"]

            config_entry.async_create_background_task = mock.Mock()

            manager._listener = mock.Mock()
            manager._listener.async_init = mock.AsyncMock()
            manager._poller = mock.Mock()
            manager._poller.async_init = mock.AsyncMock()
            manager._formatter = mock.Mock()
            manager._formatter.async_init = mock.AsyncMock()
            manager._publisher = mock.Mock()
            manager._publisher.async_init = mock.AsyncMock()

            with (
                patch("custom_components.elasticsearch.es_publish_pipeline.SystemInfo") as system_info,
                patch("custom_components.elasticsearch.es_publish_pipeline.LoopHandler") as loop_handler,
            ):
                system_info_instance = system_info.return_value
                system_info_instance.async_get_system_info = mock.AsyncMock(
                    return_value=mock.Mock(
                        version="1.0.0",
                        arch="x86",
                        os_name="Linux",
                        hostname="localhost",
                    ),
                )

                # Ensure we don't start a coroutine that never finishes
                loop_handler_instance = loop_handler.return_value
                loop_handler_instance.start = mock.Mock()

                await manager.async_init(config_entry)

                system_info_instance.async_get_system_info.assert_awaited_once()
                assert manager._static_fields == {
                    "agent.version": "1.0.0",
                    "host.architecture": "x86",
                    "host.os.name": "Linux",
                    "host.hostname": "localhost",
                }

                manager._listener.async_init.assert_awaited_once()
                manager._poller.async_init.assert_awaited_once()
                manager._formatter.async_init.assert_awaited_once_with(manager._static_fields)
                manager._publisher.async_init.assert_awaited_once()

                config_entry.async_create_background_task.assert_called_once()

                manager.stop()

        async def test_async_init_no_publish(self, manager, mock_config_entry):
            """Test the async initialization of the manager."""

            mock_config_entry.options = {}
            manager._listener = mock.Mock()
            manager._listener.async_init = mock.AsyncMock()
            manager._poller = mock.Mock()
            manager._poller.async_init = mock.AsyncMock()
            manager._formatter = mock.Mock()
            manager._formatter.async_init = mock.AsyncMock()
            manager._publisher = mock.Mock()
            manager._publisher.async_init = mock.AsyncMock()

            # No publish_frequency means the manager doesnt do anything
            manager._settings = mock.Mock()
            manager._settings.publish_frequency = None

            # Check for self._logger.warning("No publish frequency set. Disabling publishing.")
            manager._logger.warning = mock.Mock()

            await manager.async_init(mock_config_entry)

            manager._logger.warning.assert_called_once_with("No publish frequency set. Disabling publishing.")

            manager.stop()

        @pytest.mark.asyncio()
        async def test_sip_queue(self, manager, freeze_time: FrozenDateTimeFactory):
            """Test the _sip_queue method of the Pipeline.Manager class."""
            # Create some sample data
            freeze_time.tick()

            # Mock the filterer
            manager._filterer = MagicMock()
            manager._filterer.passes_filter.return_value = True

            # Mock the formatter

            timestamp = datetime.now(tz=UTC)
            state = State("light.living_room", "on")
            reason = StateChangeType.STATE

            manager._formatter = MagicMock()
            manager._formatter.format.return_value = {
                "timestamp": timestamp,
                "state": state,
                "reason": reason,
            }

            # Add the sample data to the queue
            manager._queue.put((timestamp, state, reason))

            # Call the _sip_queue method
            result = []
            # Sip queue and append to result using async list comprehension
            [result.append(doc) async for doc in manager._sip_queue()]

            # Assert that the filterer and formatter were called
            manager._filterer.passes_filter.assert_called_once_with(state, reason)
            manager._formatter.format.assert_called_once_with(timestamp, state, reason)

            # Assert that the result contains the formatted data
            assert result == [{"timestamp": timestamp, "state": state, "reason": reason}]

        @pytest.mark.asyncio()
        async def test_sip_queue_filtered(self, manager, freezer: FrozenDateTimeFactory):
            """Test the _sip_queue method of the Pipeline.Manager class."""
            # Create some sample data
            freezer.tick()

            # Mock the filterer
            manager._filterer = MagicMock()
            manager._filterer.passes_filter.return_value = False

            # Mock the formatter

            timestamp = datetime.now(tz=UTC)
            state = State("light.living_room", "on")
            reason = StateChangeType.STATE

            manager._formatter = MagicMock()
            manager._formatter.format.return_value = {
                "timestamp": timestamp,
                "state": state,
                "reason": reason,
            }

            # Add the sample data to the queue
            manager._queue.put((timestamp, state, reason))

            # Call the _sip_queue method
            result = []
            # Sip queue and append to result using async list comprehension
            [result.append(doc) async for doc in manager._sip_queue()]

            # Assert that the filterer and formatter were called
            manager._filterer.passes_filter.assert_called_once_with(state, reason)
            manager._formatter.format.assert_not_called()

            # Assert that the result contains the formatted data
            assert result == []

        @pytest.mark.asyncio()
        async def test_publish(self, hass, manager):
            """Test the _publish method of the Pipeline.Manager class."""
            # Create a mock sip_queue generator

            included_state = State("light.living_room", "on")
            excluded_state = State("sensor.temperature", "25.0")
            with (
                patch.object(
                    manager,
                    "_sip_queue",
                    side_effect=[
                        {
                            "timestamp": "2023-01-01T00:00:00Z",
                            "state": included_state,
                            "reason": "STATE_CHANGE",
                        },
                        {
                            "timestamp": "2023-01-01T00:01:00Z",
                            "state": excluded_state,
                            "reason": "STATE_CHANGE",
                        },
                    ],
                ),
                patch.object(manager._publisher, "publish") as publisher_publish,
                patch.object(manager._filterer, "passes_filter", side_effect=[True, False]),
            ):
                await manager._publish()

                publisher_publish.assert_called_once_with(
                    iterable={
                        "timestamp": "2023-01-01T00:00:00Z",
                        "state": included_state,
                        "reason": "STATE_CHANGE",
                    },
                )

        def test_stop(self, manager):
            """Test stopping the manager."""

            with (
                patch.object(manager._listener, "stop") as listener_stop,
                patch.object(manager._poller, "stop") as poller_stop,
                patch.object(manager._publisher, "stop") as publisher_stop,
            ):
                manager.stop()

                listener_stop.assert_called_once()
                poller_stop.assert_called_once()
                publisher_stop.assert_called_once()

        def test_del(self, manager):
            """Test cleaning up the manager."""
            with patch.object(manager, "stop") as manager_stop:
                manager.stop()

                manager_stop.assert_called_once()


class Test_Poller:
    """Test the Pipeline.Poller class."""

    @pytest.fixture
    async def poller(self, hass: HomeAssistant):
        """Return a Pipeline.Poller instance."""
        queue: EventQueue = Queue[tuple[datetime, State, StateChangeType]]()
        settings = MagicMock()
        poller = Pipeline.Poller(hass, queue, settings)
        yield poller

        poller.stop()

    class Test_Unit_Tests:
        """Run the unit tests of the Poller class."""

        def test_init(self, poller: Pipeline.Poller):
            """Test the initialization of the Poller."""
            assert poller._hass is not None
            assert poller._queue is not None
            assert poller._cancel_poller is None

        @pytest.mark.asyncio()
        async def test_async_init(self, poller: Pipeline.Poller):
            """Test the async initialization of the Poller."""

            config_entry = mock.Mock()
            with (
                patch("custom_components.elasticsearch.es_publish_pipeline.LoopHandler") as loop_handler,
                patch.object(config_entry, "async_create_background_task") as create_background_task,
            ):
                # Ensure we don't start a coroutine that never finishes
                loop_handler_instance = loop_handler.return_value
                loop_handler_instance.start = mock.Mock()

                poller.poll = MagicMock()

                await poller.async_init(config_entry=config_entry)

                loop_handler.assert_called_once_with(
                    name="es_state_poll_loop",
                    func=poller.poll,
                    frequency=poller._settings.polling_frequency,
                    log=poller._logger,
                )

                loop_handler_instance.start.assert_called_once()
                create_background_task.assert_called_once()

        async def test_stop(self, poller: Pipeline.Poller):
            """Test stopping the poller."""

            with patch.object(poller, "_cancel_poller") as cancel_poller:
                poller.stop()
                cancel_poller.cancel.assert_called_once()

        def test_cleanup(self, poller: Pipeline.Poller):
            """Test cleaning up the poller."""

            with patch.object(poller, "stop") as stop:
                poller.__del__()
                stop.assert_called_once()

    class Test_Integration_Tests:
        """Run the integration tests of the Poller class."""

        @pytest.mark.asyncio()
        @pytest.mark.parametrize(
            "states",
            [
                [],
                [State("light.living_room", "on")],
                [State("light.living_room", "on"), State("switch.living_room", "off")],
            ],
        )
        async def test_poll(
            self,
            poller: Pipeline.Poller,
            states: list[State],
            freeze_time: FrozenDateTimeFactory,
            snapshot: SnapshotAssertion,
        ):
            """Test polling for different quantities of states."""

            freeze_time.tick()  # use the fixture so it doesnt show type errors

            with patch.object(poller._hass, "states") as states_mock:
                states_mock.async_all = MagicMock(return_value=states)

                await poller.poll()

                states_mock.async_all.assert_called_once()

                if len(states) > 0:
                    assert not poller._queue.empty()

                queued_states: list[dict] = []

                while not poller._queue.empty():
                    timestamp, state, change_type = poller._queue.get()
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

    @pytest.fixture
    def queue(self) -> EventQueue:
        """Return a Listener instance."""
        queue: EventQueue = Queue[tuple[datetime, State, StateChangeType]]()
        return queue

    @pytest.fixture
    def listener(self, hass, queue) -> Pipeline.Listener:
        """Return a Listener instance."""
        return Pipeline.Listener(hass=hass, queue=queue)

    @pytest.fixture
    def event(self) -> Event:
        """Return a mock event data dictionary."""

        return Event(
            "state_changed",
            {
                "entity_id": "light.light_1",
                "old_state": State("light.light_1", "off"),
                "new_state": State("light.light_1", "on"),
            },
        )

    class Test_Unit_Tests:
        """Run the unit tests of the Listener class."""

        @pytest.mark.asyncio()
        async def test_listener_init(self, hass, queue):
            """Test the initialization of the Listener."""
            listener = Pipeline.Listener(hass=hass, queue=queue)

            assert listener._hass == hass
            assert listener._queue == queue
            assert listener._cancel_listener is None

        @pytest.mark.asyncio()
        async def test_listener_async_init(self, hass, listener):
            """Test the async initialization of the Listener."""
            with (
                patch.object(listener._hass, "bus"),
                patch.object(listener._hass.bus, "async_listen") as async_listen,
            ):
                await listener.async_init()

                async_listen.assert_called_once_with(
                    "state_changed",
                    listener._handle_event,
                )

        @pytest.mark.asyncio()
        async def test_listener_handle_event(self, hass, listener, event):
            """Test handling a state_changed event."""
            listener._queue.put = MagicMock()

            await listener._handle_event(event)

            listener._queue.put.assert_called_once_with(
                (event.time_fired, event.data["new_state"], StateChangeType.STATE),
            )

        @pytest.mark.asyncio()
        async def test_listener_handle_event_empty_new_state(self, hass, listener, event):
            """Test handling a state_changed event."""
            listener._queue.put = MagicMock()

            event.data["new_state"] = None

            await listener._handle_event(event)

            listener._queue.put.assert_not_called()

        def test_listener_stop(self, listener):
            """Test stopping the Listener."""

            with patch.object(listener, "_cancel_listener") as cancel_listener:
                listener.stop()

                cancel_listener.assert_called_once()

        def test_listener_cleanup(self, listener):
            """Test cleaning up the Listener."""
            with patch.object(listener, "_cancel_listener") as cancel_listener:
                listener.__del__()

                cancel_listener.assert_called_once()


class Test_Publisher:
    """Test the Pipeline.Publisher class."""

    @pytest.fixture
    def mock_gateway(self):
        """Return a mock ElasticsearchGateway instance."""
        return MagicMock(spec=ElasticsearchGateway)

    @pytest.fixture
    def mock_settings(self):
        """Return a mock PipelineSettings instance."""
        return MagicMock(spec=PipelineSettings)

    @pytest.fixture
    def publisher(self, hass, mock_gateway, mock_settings):
        """Return a Publisher instance."""
        publisher = Pipeline.Publisher(hass=hass, gateway=mock_gateway, settings=mock_settings)

        yield publisher

        publisher.stop()

    class Test_Unit_Tests:
        """Run the unit tests of the Publisher class."""

        def test_format_datastream_name(self, publisher):
            """Test formatting a datastream name."""
            datastream_type = "metrics"
            dataset = "homeassistant.light"
            namespace = "default"

            # Ensure our LRU cache is empty
            assert publisher._format_datastream_name.cache_info().hits == 0

            datastream_name = publisher._format_datastream_name(datastream_type, dataset, namespace)

            assert datastream_name == "metrics-homeassistant.light-default"

            # Ensure the datastream name is now in the lru cache from the decorator
            assert publisher._format_datastream_name.cache_info().misses == 1

            datastream_name = publisher._format_datastream_name(datastream_type, dataset, namespace)

            assert datastream_name == "metrics-homeassistant.light-default"

            assert publisher._format_datastream_name.cache_info().hits == 1

        @pytest.mark.asyncio()
        async def test_add_action_and_meta_data(self, publisher):
            """Test converting document to elasticsearch action."""

            doc: dict = {
                "datastream": {
                    "type": "metrics",
                    "dataset": "homeassistant.light",
                    "namespace": "default",
                },
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

            async def yield_doc():
                yield doc

            async for action in publisher._add_action_and_meta_data(yield_doc()):
                assert action == {
                    "_op_type": "create",
                    "_index": "metrics-homeassistant.light-default",
                    "_source": doc,
                }

            assert action is not None

        @pytest.mark.asyncio()
        async def test_publish(self, publisher, mock_gateway):
            """Test publishing a document."""

            # Mock the iterable
            iterable = [MagicMock(), MagicMock(), MagicMock()]

            publisher._add_action_and_meta_data = MagicMock(side_effect=iterable)
            # Call the publish method
            await publisher.publish(iterable)

            # Assert that the bulk method of the gateway was called with the correct arguments
            mock_gateway.bulk.assert_called_once_with(
                actions=iterable[0],
            )

        async def test_cleanup(self, publisher, mock_gateway):
            """Test cleaning up the Publisher."""
            with patch.object(publisher, "stop") as stop:
                publisher.__del__()
                stop.assert_called_once()


class Test_Formatter:
    """Test the Pipeline.Formatter class."""

    @pytest.fixture
    def formatter(self, hass: HomeAssistant) -> Pipeline.Formatter:
        """Return a Formatter instance."""
        return Pipeline.Formatter(hass)

    class Test_Unit_Tests:
        """Run the unit tests of the Formatter class."""

        def test_init(self, formatter):
            """Test the initialization of the Formatter."""
            assert formatter._extended_entity_details is not None
            assert formatter._static_fields == {}

        @pytest.mark.asyncio()
        async def test_async_init(self, formatter):
            """Test the async initialization of the Formatter."""

            static_fields = {
                "agent.version": "1.0.0",
                "host.architecture": "x86",
                "host.os.name": "Linux",
                "host.hostname": "localhost",
            }

            await formatter.async_init(
                static_fields=static_fields,
            )

            assert formatter._static_fields == static_fields

        def test_state_to_attributes(self, formatter):
            """Test converting a state to attributes."""
            state = State("light.living_room", "on", {"brightness": 255, "color_temp": 4000})
            attributes = formatter._state_to_attributes(state)
            assert attributes == {"brightness": 255, "color_temp": 4000}

        def test_state_to_attributes_skip(self, formatter):
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

        def test_state_to_attributes_duplicate_sanitize(self, formatter):
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

        def test_state_to_attributes_objects(self, formatter, snapshot: SnapshotAssertion):
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

            assert {
                "orig_attributes": orig_attributes,
                "transformed_attributes": transformed_attributes,
            } == snapshot

        def test_state_to_coerced_value_string(self, formatter):
            """Test converting a state to a coerced value."""
            state = State("light.living_room", "tomato")
            coerced_value = formatter.state_to_coerced_value(state)
            assert coerced_value == {"string": "tomato"}

        def test_state_to_coerced_value_boolean(self, formatter):
            """Test converting a state to a coerced value."""
            state = State("binary_sensor.motion", "on")
            coerced_value = formatter.state_to_coerced_value(state)
            assert coerced_value == {"boolean": True}

            state = State("binary_sensor.motion", "off")
            coerced_value = formatter.state_to_coerced_value(state)
            assert coerced_value == {"boolean": False}

        def test_state_to_coerced_value_float(self, formatter):
            """Test converting a state to a coerced value."""
            state = State("sensor.temperature", "25.5")
            coerced_value = formatter.state_to_coerced_value(state)
            assert coerced_value == {"float": 25.5}

        def test_state_to_coerced_value_float_fail(self, formatter):
            """Test converting a state to a coerced value."""
            # set state to infinity
            state = State("sensor.temperature", str(float("inf")))
            coerced_value = formatter.state_to_coerced_value(state)
            assert coerced_value == {"string": "inf"}

            # set state to nan
            state = State("sensor.temperature", str(float("nan")))
            coerced_value = formatter.state_to_coerced_value(state)
            assert coerced_value == {"string": "nan"}

        def test_state_to_coerced_value_datetime(self, formatter):
            """Test converting a state to a coerced value."""
            state = State("sensor.last_updated", "2023-04-12T12:00:00Z")
            coerced_value = formatter.state_to_coerced_value(state)
            assert coerced_value == {
                "datetime": "2023-04-12T12:00:00+00:00",
                "date": "2023-04-12",
                "time": "12:00:00",
            }

        def test_domain_to_datastream(self, formatter):
            """Test converting a state to a datastream."""
            datastream = formatter.domain_to_datastream(const.TEST_ENTITY_DOMAIN)
            assert datastream == {
                "datastream.type": "metrics",
                "datastream.dataset": f"homeassistant.{const.TEST_ENTITY_DOMAIN}",
                "datastream.namespace": "default",
            }

    class Test_Integration_Tests:
        """Run the integration tests of the Formatter class."""

        def test_state_to_extended_details(
            self,
            formatter,
            entity,
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

            state = State(entity_id=entity.entity_id, state="on", attributes={"brightness": 255})

            entity_details = formatter._state_to_extended_details(state)

            assert entity_details["hass.entity.area.name"] == entity_area_name
            assert entity_details["hass.entity.area.floor.name"] == entity_floor_name
            assert entity_details["hass.entity.device.labels"] == device_labels
            assert entity_details["hass.entity.device.name"] == device_name
            assert entity_details["hass.entity.labels"] == entity_labels
            assert entity_details["hass.entity.platform"] == entity.platform

            assert entity_details == snapshot

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
        def test_format(
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
            freeze_time: FrozenDateTimeFactory,
            snapshot,
        ):
            """Test converting a state to entity details."""

            time = datetime.now(tz=UTC)
            state = State(entity_id=entity.entity_id, state="on", attributes={"brightness": 255})
            reason = StateChangeType.STATE

            document = formatter.format(time, state, reason)

            assert document["@timestamp"] == time.isoformat()

            assert document["datastream.dataset"] == f"homeassistant.{entity.domain}"
            assert document["datastream.type"] == "metrics"
            assert document["datastream.namespace"] == "default"

            assert document["event.action"] == "State change"
            assert document["event.kind"] == "event"
            assert document["event.type"] == "change"

            assert document["hass.entity.friendly_name"] is not None
            assert document["hass.entity.domain"] == entity.domain
            assert document["hass.entity.id"] is not None
            assert document["hass.entity.object.id"] == entity_object_id
            assert document["hass.entity.value"] == "on"
            assert document["hass.entity.valueas"] == {"boolean": True}

            assert document["datastream.namespace"] == "default"

            assert document == snapshot

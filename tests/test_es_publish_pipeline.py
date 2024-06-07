"""Tests for the es_publish_pipeline module."""

from datetime import datetime
from queue import Queue
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.json import JSONSnapshotExtension

from custom_components.elasticsearch.es_publish_pipeline import (
    EventQueue,
    Pipeline,
    PipelineSettings,
    StateChangeType,
)
from tests.const import MOCK_NOON_APRIL_12TH_2023


@pytest.fixture(autouse=True)
def snapshot(snapshot: SnapshotAssertion):
    """Provide a pre-configured snapshot object."""

    return snapshot.with_defaults(extension_class=JSONSnapshotExtension)


@pytest.fixture
def settings():
    """Return a PipelineSettings instance."""
    return PipelineSettings(
        included_entities=[],
        excluded_entities=[],
        included_domains=[],
        excluded_domains=[],
        allowed_change_types=[],
        publish_frequency=60,
        polling_enabled=True,
        polling_frequency=60,
    )


@pytest.fixture
def filterer(settings: PipelineSettings):
    """Return a Pipeline.Filterer instance."""

    return Pipeline.Filterer(settings=settings)


class Test_Filterer:
    """Test the Pipeline.Filterer class."""

    def test_passes_entity_domain_filters_included_entity(self, filterer):
        """Test that a state change for an included entity passes the filter."""
        state = State("light.living_room", "on")
        filterer._included_entities = ["light.living_room"]
        assert filterer._passes_entity_domain_filters(state.entity_id, state.domain) is True

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

    def test_passes_change_type_filter_true(self, filterer):
        """Test that a state change with an allowed change type passes the filter."""
        filterer._allowed_change_types = [StateChangeType.STATE]
        assert filterer._passes_change_type_filter(StateChangeType.STATE) is True

    def test_passes_change_type_filter_false(self, filterer):
        """Test that a state change with an allowed change type passes the filter."""
        filterer._allowed_change_types = [StateChangeType.ATTRIBUTE]
        assert filterer._passes_change_type_filter(StateChangeType.STATE) is False

    def test_passes_filter_with_allowed_change_type_and_included_entity(self, filterer):
        """Test that a state change with an allowed change type and included entity passes the filter."""
        state = State("light.living_room", "on")
        filterer._allowed_change_types = [StateChangeType.STATE]
        filterer._included_entities = ["light.living_room"]
        assert filterer.passes_filter(state, StateChangeType.STATE) is True

    def test_passes_filter_with_allowed_change_type_and_excluded_entity(self, filterer):
        """Test that a state change with an allowed change type and excluded entity does not pass the filter."""
        state = State("light.living_room", "on")
        filterer._allowed_change_types = [StateChangeType.STATE]
        filterer._excluded_entities = ["light.living_room"]
        assert filterer.passes_filter(state, StateChangeType.STATE) is False


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
            allowed_change_types=[],
            publish_frequency=60,
            polling_enabled=True,
            polling_frequency=60,
        )
        return Pipeline.Manager(hass=hass, gateway=gateway, settings=settings)

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
        config_entry.async_create_background_task = mock.Mock()

        manager._listener = mock.Mock()
        manager._listener.async_init = mock.AsyncMock()
        manager._poller = mock.Mock()
        manager._poller.async_init = mock.AsyncMock()
        manager._formatter = mock.Mock()
        manager._formatter.async_init = mock.AsyncMock()
        manager._publisher = mock.Mock()
        manager._publisher.async_init = mock.AsyncMock()

        with patch("custom_components.elasticsearch.es_publish_pipeline.SystemInfo") as system_info:
            system_info_instance = system_info.return_value
            system_info_instance.async_get_system_info = mock.AsyncMock(
                return_value=mock.Mock(
                    version="1.0.0",
                    arch="x86",
                    os_name="Linux",
                    hostname="localhost",
                ),
            )

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

    # async def test_gather_and_publish(self, hass: HomeAssistant, settings: PipelineSettings):
    #     """Test gathering and publishing."""

    #     gateway = mock.Mock()
    #     manager = Pipeline.Manager(hass=hass, gateway=gateway, settings=settings)

    #     # Assign the mock dependencies to the manager
    #     manager._poller = MagicMock()
    #     manager._poller.poll = mock.AsyncMock()
    #     manager._filterer = MagicMock()
    #     manager._formatter = MagicMock()
    #     manager._publisher = MagicMock()
    #     manager._publisher.publish = mock.AsyncMock()

    #     # Create mock state changes
    #     state1 = State("light.living_room", "on")
    #     state2 = State("sensor.temperature", "25.0")
    #     state3 = State("switch.bedroom", "off")

    #     document1 = {"timestamp": datetime.now(tz=UTC), "state": "on"}
    #     document2 = {"timestamp": datetime.now(tz=UTC), "state": 25.0}
    #     document3 = {"timestamp": datetime.now(tz=UTC), "state": "off"}

    #     manager._queue.put((document1["timestamp"], state1, StateChangeType.STATE))
    #     manager._queue.put((document2["timestamp"], state2, StateChangeType.STATE))
    #     manager._queue.put((document3["timestamp"], state3, StateChangeType.STATE))

    #     # Configure the mock filterer to pass all state changes
    #     manager._filterer.passes_filter.side_effect = [True, True, True]

    #     # Configure the mock formatter to return the mock documents
    #     manager._formatter.format.side_effect = [document1, document2, document3]

    #     # Run the _gather_and_publish method
    #     await manager._gather_and_publish()

    #     # Assert that the poller was called
    #     manager._poller.poll.assert_called_once()

    #     # Assert that the filterer was called for each state change
    #     assert manager._filterer.passes_filter.call_count == 3

    #     # Assert that the formatter was called for each state change
    #     assert manager._formatter.format.call_count == 3

    #     # Assert that the publisher was called with the mock documents
    #     manager._publisher.publish.assert_called_once_with([document1, document2, document3])


class Test_Poller:
    """Test the Pipeline.Poller class."""

    @pytest.fixture
    def poller(self, hass: HomeAssistant) -> Pipeline.Poller:
        """Return a Pipeline.Poller instance."""
        queue: EventQueue = Queue[tuple[datetime, State, StateChangeType]]()
        settings = MagicMock()
        return Pipeline.Poller(hass, queue, settings)

    @pytest.fixture
    def freeze_time(self, freezer: FrozenDateTimeFactory):
        """Freeze time so we can properly assert on payload contents."""

        frozen_time = dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023)
        if frozen_time is None:
            msg = "Invalid date string"
            raise ValueError(msg)

        freezer.move_to(frozen_time)

        return freezer

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

    def test_stop(self, poller):
        """Test stopping the poller."""

        with patch.object(poller, "_cancel_poller") as cancel_poller:
            poller.stop()
            cancel_poller.cancel.assert_called_once()

    def test_cleanup(self, poller):
        """Test cleaning up the poller."""

        with patch.object(poller, "stop") as stop:
            poller.__del__()
            stop.assert_called_once()

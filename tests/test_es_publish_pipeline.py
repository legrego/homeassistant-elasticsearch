"""Tests for the es_publish_pipeline module."""

from datetime import UTC, datetime
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant, State

from custom_components.elasticsearch.es_publish_pipeline import Pipeline, PipelineSettings, StateChangeType


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
        )
        return Pipeline.Manager(hass=hass, gateway=gateway, settings=settings)

    def test_init(self, manager):
        """Test the initialization of the manager."""
        assert manager._logger is not None
        assert manager._hass is not None
        assert manager._gateway is not None
        assert manager._publish_frequency == 60
        assert manager._cancel_manager is None
        assert manager._static_fields == {}
        assert manager._queue is not None
        assert manager._listener is not None
        assert manager._poller is not None
        assert manager._filterer is not None
        assert manager._formatter is not None
        assert manager._publisher is not None

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
        manager._cancel_manager = mock.Mock()
        manager._listener = mock.Mock()
        manager.stop()

        manager._cancel_manager.cancel.assert_called_once()
        manager._listener.stop.assert_called_once()

    def test_del(self, manager):
        """Test cleaning up the manager."""
        manager._cancel_manager = mock.Mock()
        manager._listener = mock.Mock()
        manager.__del__()

        manager._cancel_manager.cancel.assert_called_once()
        manager._listener.stop.assert_called_once()

    async def test_gather_and_publish(self, hass: HomeAssistant, settings: PipelineSettings):
        """Test gathering and publishing."""

        gateway = mock.Mock()
        manager = Pipeline.Manager(hass=hass, gateway=gateway, settings=settings)

        # Assign the mock dependencies to the manager
        manager._poller = MagicMock()
        manager._poller.poll = mock.AsyncMock()
        manager._filterer = MagicMock()
        manager._formatter = MagicMock()
        manager._publisher = MagicMock()
        manager._publisher.publish = mock.AsyncMock()

        # Create mock state changes
        state1 = State("light.living_room", "on")
        state2 = State("sensor.temperature", "25.0")
        state3 = State("switch.bedroom", "off")

        document1 = {"timestamp": datetime.now(tz=UTC), "state": "on"}
        document2 = {"timestamp": datetime.now(tz=UTC), "state": 25.0}
        document3 = {"timestamp": datetime.now(tz=UTC), "state": "off"}

        manager._queue.put((document1["timestamp"], state1, StateChangeType.STATE))
        manager._queue.put((document2["timestamp"], state2, StateChangeType.STATE))
        manager._queue.put((document3["timestamp"], state3, StateChangeType.STATE))

        # Configure the mock filterer to pass all state changes
        manager._filterer.passes_filter.side_effect = [True, True, True]

        # Configure the mock formatter to return the mock documents
        manager._formatter.format.side_effect = [document1, document2, document3]

        # Run the _gather_and_publish method
        await manager._gather_and_publish()

        # Assert that the poller was called
        manager._poller.poll.assert_called_once()

        # Assert that the filterer was called for each state change
        assert manager._filterer.passes_filter.call_count == 3

        # Assert that the formatter was called for each state change
        assert manager._formatter.format.call_count == 3

        # Assert that the publisher was called with the mock documents
        manager._publisher.publish.assert_called_once_with([document1, document2, document3])

"""Tests for the logger module."""

import logging
from unittest.mock import MagicMock

import pytest
from custom_components.elasticsearch.logger import (
    async_log_enter_exit_debug,
    async_log_enter_exit_info,
)

DECORATORS = [
    pytest.param(async_log_enter_exit_info, logging.INFO, id="info"),
    pytest.param(async_log_enter_exit_debug, logging.DEBUG, id="debug"),
]


class TestAsyncLogEnterExit:
    """Test the async enter and exit logging decorators."""

    @pytest.mark.parametrize(("decorator", "level"), DECORATORS)
    async def test_logs_return_after_coroutine_completes(self, decorator, level):
        """Test that the return is logged once the wrapped coroutine has finished."""
        events: list[str] = []

        class Example:
            _logger = MagicMock()

            @decorator
            async def run(self) -> str:
                events.append("body")
                return "result"

        Example._logger.log.side_effect = lambda _level, msg, *_args: events.append(msg)

        assert await Example().run() == "result"

        assert events == ["Entering %s : %s", "body", "Returning from %s : %s"]
        assert all(call.args[0] == level for call in Example._logger.log.call_args_list)

    @pytest.mark.parametrize(("decorator", "level"), DECORATORS)
    async def test_logs_error_when_coroutine_raises(self, decorator, level):
        """Test that an exception from the wrapped coroutine is logged and re-raised."""

        class Example:
            _logger = MagicMock()

            @decorator
            async def run(self) -> None:
                raise ValueError

        with pytest.raises(ValueError):
            await Example().run()

        messages = [call.args[1] for call in Example._logger.log.call_args_list]

        assert messages == ["Entering %s : %s", "Error in %s : %s"]
        assert all(call.args[0] == level for call in Example._logger.log.call_args_list)

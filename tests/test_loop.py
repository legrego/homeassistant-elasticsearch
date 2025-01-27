"""Tests for the loop module."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from custom_components.elasticsearch.logger import LOGGER as BASE_LOGGER
from custom_components.elasticsearch.loop import LoopHandler


class Test_Initialization:
    """Test initialization of the LoopHandler class."""

    async def test_init(self):
        """Test initializing the loop handler."""

        # Create a mock function
        mock_func = MagicMock()

        # Create a LoopHandler instance with a frequency of 1 second
        loop_handler = LoopHandler(mock_func, "test_loop", 1)

        # Assert that the function, name, frequency, and log are set correctly
        assert loop_handler._func == mock_func
        assert loop_handler._name == "test_loop"
        assert loop_handler._frequency == 1
        assert loop_handler._running is False
        assert loop_handler._should_stop is False
        assert loop_handler._run_count == 0
        assert loop_handler._log == BASE_LOGGER
        assert loop_handler._next_run_time <= time.monotonic()
        assert loop_handler._next_run_time >= time.monotonic() - 2


class Test_Loop_Handler:
    """Test the LoopHandler class with syncronous functions."""

    def test_loop_handler_start(self):
        """Test starting the loop handler."""

        # Create a mock function
        mock_func = AsyncMock()

        # Create a LoopHandler instance with a frequency of 1 second
        loop_handler = LoopHandler(mock_func, "test_loop", 1)
        loop_handler._should_keep_running = MagicMock(side_effect=[True, False])

        # Start the loop handler
        asyncio.run(loop_handler.start())

        # Assert that the mock function was called at least once
        assert mock_func.call_count >= 1
        assert loop_handler._should_keep_running.call_count >= 2

    def test_loop_handler_start_exception(self):
        """Test starting the loop handler."""

        # Create a mock function that throws an exception
        mock_func = MagicMock(side_effect=Exception("Test exception"))

        # Create a LoopHandler instance with a frequency of 1 second
        loop_handler = LoopHandler(mock_func, "test_loop", 1)
        loop_handler._should_keep_running = MagicMock(side_effect=[True, False])

        # Start the loop handler
        with pytest.raises(Exception):  # noqa: B017
            asyncio.run(loop_handler.start())

        # Assert that the mock function was called at least once
        assert mock_func.call_count >= 1
        assert loop_handler._should_keep_running.call_count == 1

    async def test_loop_handler_stop(self):
        """Test starting the loop handler."""

        # Create a mock function
        mock_func = AsyncMock()
        mock_func.return_value = None
        # Create a LoopHandler instance with a frequency of 1 second
        loop_handler = LoopHandler(mock_func, "test_loop", 1)

        # Start the loop handler in the background, make sure it runs for a short duration
        # then stop it, wait for a short duration, and assert that the loop handler has stopped
        loop_task = asyncio.ensure_future(loop_handler.start(), loop=asyncio.get_event_loop())
        await asyncio.sleep(2)

        assert loop_handler._running is True

        # Stop the loop handler
        loop_handler.stop()

        assert loop_handler._running is False
        assert loop_handler._should_keep_running() is False
        assert loop_handler._should_stop_running() is True
        assert loop_handler._should_stop is True

        # Wait for the loop handler to stop
        await asyncio.sleep(1)

        assert loop_task.done()

    async def test_loop_handler_time_to_run(self):
        """Test the _time_to_run method of LoopHandler."""
        mock_func = MagicMock()
        loop_handler = LoopHandler(mock_func, "test_loop", 1)

        # Set the next run time to be in the future
        loop_handler._next_run_time = time.monotonic() + 100

        assert loop_handler._time_to_run() is False

        # Set the next run time to be in the past
        loop_handler._next_run_time = 0

        assert loop_handler._time_to_run() is True

    async def test_loop_handler_time_until_next_run(self):
        """Test the _time_until_next_run method of LoopHandler."""
        mock_func = MagicMock()
        loop_handler = LoopHandler(mock_func, "test_loop", 1)

        # Set the next run time to be in the future
        loop_handler._next_run_time = time.monotonic() + 100

        assert loop_handler._time_until_next_run() <= 100
        assert loop_handler._time_until_next_run() > 90

        # Set the next run time to be in the past
        loop_handler._next_run_time = 0

        assert loop_handler._time_until_next_run() == 0

    async def test_loop_handler_schedule_next_run(self):
        """Test the _schedule_next_run method of LoopHandler."""
        mock_func = MagicMock()
        loop_handler = LoopHandler(mock_func, "test_loop", 1)

        # Set the next run time to be in the past
        loop_handler._next_run_time = 0

        loop_handler._schedule_next_run()

        assert loop_handler._next_run_time > 0

    async def test_loop_handler_wait_for_next_run(self):
        """Test the _wait_for_next_run method of LoopHandler."""

        mock_func = MagicMock()
        loop_handler = LoopHandler(mock_func, "test_loop", 1)

        # Set the next run time to be in the past
        loop_handler._next_run_time = time.monotonic() + 1

        assert loop_handler._time_to_run() is False

        await loop_handler._wait_for_next_run()

        assert loop_handler._time_to_run() is True

    async def test_loop_handler_wait_for_next_run_should_stop(self):
        """Test the _wait_for_next_run method of LoopHandler."""

        mock_func = MagicMock()
        loop_handler = LoopHandler(mock_func, "test_loop", 1)

        # Set the next run time to be in the future
        loop_handler._next_run_time = time.monotonic() + 30
        loop_handler._should_stop_running = MagicMock(return_value=True)

        # wait for the next run time should throw a runtimeerror using pytest raises
        with pytest.raises(RuntimeError):
            await loop_handler._wait_for_next_run()

    async def test_loop_handler_wait_for_next_run_should_spin(self):
        """Test the _wait_for_next_run method of LoopHandler."""

        mock_func = AsyncMock()
        loop_handler = LoopHandler(mock_func, "test_loop", 1)

        # Set the next run time to be in the future
        loop_handler._next_run_time = time.monotonic() + 1
        loop_handler._spin = AsyncMock()
        loop_handler._should_stop_running = MagicMock(side_effect=[False, True])

        # will throw a runtimeerror using pytest raises
        with pytest.raises(RuntimeError):
            await loop_handler._wait_for_next_run()

        assert loop_handler._spin.call_count >= 1

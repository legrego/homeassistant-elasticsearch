"""Implements a loop handler."""

import asyncio
import time
import typing
from datetime import UTC, datetime, timedelta
from logging import Logger

from .logger import LOGGER as BASE_LOGGER


class LoopHandler:
    """Handle a loop for a given function."""

    def __init__(self, func: typing.Callable, name: str, frequency: int, log: Logger = BASE_LOGGER) -> None:
        """Initialize the loop handler."""
        self._func: typing.Callable = func

        self._name = name

        self._frequency: int = frequency
        self._running: bool = False
        self._should_stop: bool = False
        self._run_count: int = 0

        self._log: Logger = log
        self._next_run_time: float = time.monotonic()

    def _time_to_run(self) -> bool:
        """Determine if now is a good time to poll for state changes."""
        return self._next_run_time <= time.monotonic()

    def _time_until_next_run(self) -> int:
        """Return the time until the next run."""

        # If the next run time is in the past, return 0
        # Otherwise, return the time until the next run, round up to the nearest second
        return max(0, int(self._next_run_time - time.monotonic()))

    async def _wait_for_next_run(self) -> None:
        """Wait for the next poll time."""
        while not self._time_to_run():
            if self._should_stop_running():
                msg = "Stopping the loop handler."
                raise RuntimeError(msg)
            await self._spin()
            continue

    def _schedule_next_run(self) -> None:
        self._next_run_time = time.monotonic() + self._frequency
        self._log.debug(
            "Next run of loop: %s scheduled for roughly %s (UTC) -- %ss from now",
            self._name,
            datetime.now(tz=UTC) + timedelta(0, self._frequency),
            self._frequency,
        )

    def _should_keep_running(self) -> bool:
        """Determine if the runner should keep running."""
        return self._running and not self._should_stop

    def _should_stop_running(self) -> bool:
        """Determine if the runner should stop."""
        return self._should_stop

    async def _spin(self, duration: int = 1) -> None:
        """Spin the event loop."""
        await asyncio.sleep(duration)

    def stop(self) -> None:
        """Stop the loop."""
        self._should_stop = True
        self._running = False

    async def start(self) -> None:
        """Start the loop."""
        self._running = True

        while self._should_keep_running():
            await self._wait_for_next_run()
            self._schedule_next_run()

            self._run_count += 1
            try:
                await self._func()
            except Exception:
                self._log.exception("Error in loop handler: %s", self._name)
                self.stop()
                raise

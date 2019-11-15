"""Utilities for debugging."""

import aiomas

import arrow

import asyncio


class DebuggingClock(aiomas.ExternalClock):
    """Simple external clock for debugging."""

    def __init__(self, start, stop, speed_up):
        """Init clock with *start* and *stop* datetimes and *speed_up* factor.

        *start* and *stop* must be datetime strings compatible with arrow.
        *speed_up* must be a positive, non-zero integer or float.
        """
        super().__init__(start)
        self._stop = arrow.get(stop).to('utc')
        # speed_up must be positive, non-zero
        assert speed_up > 0.0
        self._speed_up = speed_up

    async def run(self):
        """Let time pass *speed_up* times as fast as real-time."""
        finished = False
        while not finished:
            try:
                await asyncio.sleep(1 / self._speed_up)
                self.set_time(self.time() + 60)
                finished = self.utcnow() > self._stop
            except asyncio.CancelledError:
                print('Stopping debugging clock...')
                finished = True

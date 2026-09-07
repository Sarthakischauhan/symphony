"""Harness terminal exceptions."""


class HarnessCancelled(RuntimeError):
    """Raised when the ``asyncio.Task`` running ``CoreHarness.run`` is cancelled."""


class HarnessLimitExceeded(RuntimeError):
    """Raised when a configured run limit is exceeded."""

    def __init__(self, limit: str, value: float, maximum: float, message: str) -> None:
        super().__init__(message)
        self.limit = limit
        self.value = value
        self.maximum = maximum

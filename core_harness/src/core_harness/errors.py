"""Harness terminal exceptions."""


class HarnessCancelled(RuntimeError):
    """Raised when an inbound cancel command stops the harness run."""


class HarnessLimitExceeded(RuntimeError):
    """Raised when a configured run limit is exceeded."""

    def __init__(self, limit: str, value: float, maximum: float, message: str) -> None:
        super().__init__(message)
        self.limit = limit
        self.value = value
        self.maximum = maximum

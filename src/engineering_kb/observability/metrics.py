"""Optional metrics-export port for infrastructure adapters."""

from typing import Protocol


class MetricsRecorder(Protocol):
    def increment(self, name: str, *, value: int = 1) -> None: ...

    def observe(self, name: str, value: float) -> None: ...

from __future__ import annotations

from typing import Final, Protocol


class Progress(Protocol):
    """Receives the steps of a long running operation so a frontend can show them."""

    def start(self, message: str) -> None: ...

    def done(self, message: str | None = None) -> None: ...

    def info(self, message: str) -> None: ...

    def warn(self, message: str) -> None: ...


class NullProgress:
    """Progress sink that discards everything. The default for every core call."""

    def start(self, message: str) -> None:
        return None

    def done(self, message: str | None = None) -> None:
        return None

    def info(self, message: str) -> None:
        return None

    def warn(self, message: str) -> None:
        return None


NO_PROGRESS: Final = NullProgress()
"""The shared default `progress` argument of every core call."""

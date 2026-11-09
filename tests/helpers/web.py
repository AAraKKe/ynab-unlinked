import asyncio
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from nicegui import ui
from nicegui.testing import User as NiceGUIUser
from nicegui.testing.general import nicegui_reset_globals
from pytest_mock import MockerFixture

TOKEN = "test-session-token"
PORT = 8765
"""The port the test app pretends to listen on: its guard only accepts this Host."""
BASE_URL = f"http://127.0.0.1:{PORT}"


@contextmanager
def fresh_nicegui() -> Iterator[None]:
    """NiceGUI's global reset, minus its habit of unloading our modules.

    On exit the reset drops from `sys.modules` every module that registered a page (here
    `ynab_unlinked.web.views.onboarding`) and all its parents, `ynab_unlinked` included. Later
    imports would then load a second copy of the package, and patches applied to one copy would
    miss code bound to the other.
    """
    ours = {
        name: module
        for name, module in sys.modules.items()
        if name == "ynab_unlinked" or name.startswith("ynab_unlinked.")
    }
    try:
        with nicegui_reset_globals():
            yield
    finally:
        sys.modules.update(ours)


WAIT_SECONDS = 10
"""How long `User.should_see` / `should_not_see` and `eventually` wait before failing.

Long on purpose: they return as soon as the page is right, so a passing test never pays it. A
shorter wait is a guess at how long a handler run off the loop takes, and a busy CI runner
makes that guess wrong.
"""


POLL_SECONDS = 0.005
"""How often the helpers below look again. Handlers run off the loop finish in a few ms."""


async def _poll(check: Callable[[], bool], seconds: float) -> None:
    """Return once `check` passes or about `seconds` went by.

    Counts sleeps instead of reading a clock: `today` freezes `time.monotonic`.
    """
    for _ in range(round(seconds / POLL_SECONDS)):
        if check():
            return
        await asyncio.sleep(POLL_SECONDS)


async def eventually(check: Callable[[], bool]) -> None:
    """Wait for a background handler (a click that reads the store or saves) to finish."""
    await _poll(check, WAIT_SECONDS)
    assert check()


class User(NiceGUIUser):
    """NiceGUI's simulated user, looking at the page every 5 ms for up to `WAIT_SECONDS`.

    NiceGUI checks `retries` times, 100 ms apart (50 ms for `should_not_see`): the wait before
    failing is then a guess of how long the page takes, which flakes on a slow runner. Here
    `retries` is accepted for NiceGUI's signature but every check waits the same, long time.
    """

    async def should_see(
        self,
        target: str | type[ui.element] | None = None,
        *,
        kind: type[ui.element] | None = None,
        marker: str | list[str] | None = None,
        content: str | list[str] | None = None,
        retries: int = 3,
    ) -> None:
        await _poll(lambda: self._sees(target, kind, marker, content), WAIT_SECONDS)
        # One last look that passes, or fails with NiceGUI's own message
        await super().should_see(target, kind=kind, marker=marker, content=content, retries=1)  # type: ignore[call-overload]

    async def should_not_see(
        self,
        target: str | type[ui.element] | None = None,
        *,
        kind: type[ui.element] | None = None,
        marker: str | list[str] | None = None,
        content: str | list[str] | None = None,
        retries: int = 3,
    ) -> None:
        await _poll(lambda: not self._sees(target, kind, marker, content), WAIT_SECONDS)
        await super().should_not_see(  # type: ignore[call-overload]
            target, kind=kind, marker=marker, content=content, retries=1
        )


def record_threads(mocker: MockerFixture, owner: type, method: str) -> list[str]:
    """Patch `owner.method` to note the name of each thread it runs on, then call through.

    For the blocking calls the app must keep off the event loop: a name equal to
    `threading.main_thread().name` means a call froze every open page.
    """
    original = getattr(owner, method)
    threads: list[str] = []

    def record(*args: Any, **kwargs: Any) -> Any:
        threads.append(threading.current_thread().name)
        return original(*args, **kwargs)

    mocker.patch.object(owner, method, record)
    return threads

import asyncio
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

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


async def eventually(check: Callable[[], bool]) -> None:
    """Wait for a background handler (a click that reads the store or saves) to finish."""
    for _ in range(100):
        if check():
            return
        await asyncio.sleep(0.02)
    assert check()


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


def off_the_event_loop(threads: list[str], calls: int | None = None) -> bool:
    """Whether `calls` calls (at least one by default) ran, none of them on the main thread."""
    ran = len(threads) == calls if calls is not None else bool(threads)
    return ran and threading.main_thread().name not in threads

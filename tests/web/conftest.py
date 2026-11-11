import asyncio
import gc
import os
from collections.abc import AsyncIterator

import httpx
import pytest
from nicegui import core, run, ui
from nicegui.testing.general import prepare_simulation

from tests.helpers.web import BASE_URL, PORT, TOKEN, User, fresh_nicegui
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.__about__ import __version__
from ynab_unlinked.web import app as web_app
from ynab_unlinked.web import state as web_state
from ynab_unlinked.web import update as web_update
from ynab_unlinked.web.security import cookie_name
from ynab_unlinked.web.state import state

SLOW_IO = float(os.environ.get("YUL_TEST_SLOW_IO", "0"))
"""Seconds every `run.io_bound` call waits first (`YUL_TEST_SLOW_IO=0.3 uv run pytest tests/web`).

A CI runner can take that long to run a handler off the loop. A test that only passes without it
reads the page before the work it waits for has finished.
"""


@pytest.fixture(autouse=True)
def slow_io(monkeypatch: pytest.MonkeyPatch) -> None:
    if not SLOW_IO:
        return
    io_bound = run.io_bound

    async def slowly(callback, *args, **kwargs):  # type: ignore[no-untyped-def]
        await asyncio.sleep(SLOW_IO)
        return await io_bound(callback, *args, **kwargs)

    monkeypatch.setattr(run, "io_bound", slowly)


@pytest.fixture(autouse=True)
def no_newer_yul(monkeypatch: pytest.MonkeyPatch) -> None:
    """PyPI is never asked: every test starts on a fresh `Updates` that finds the running yul
    to be the latest. A test about an update patches `web_update.latest_version` again."""
    monkeypatch.setattr(web_update, "_updates", None)
    monkeypatch.setattr(web_update, "latest_version", lambda: __version__)


@pytest.fixture
async def guest(
    config: str, ynab_api: YnabClientStub, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[User]:
    """A browser on the app built exactly as `yul app` builds it, before it has the token.

    Like NiceGUI's own `user` fixture, but the app is built by `web.app.build` after the
    config fixtures ran, so the guard, the pages and the state match a real run.
    """
    # A fresh AppState per test: a sync a previous test left running (views sync a stale
    # store on open) must not leak its error or its task into this one.
    monkeypatch.setattr(web_state, "_state", None)
    # NiceGUI's reset runs a full `gc.collect()` before and after every test, walking the whole
    # heap: every library, plus the render caches Textual keeps from the reconcile TUI tests.
    # What is alive now is not this test's garbage, so freezing it keeps those collections to
    # what the test creates. They took a third of the suite's time.
    gc.freeze()
    with fresh_nicegui():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            prepare_simulation()
            state().reload()
            ui.run(web_app.build(TOKEN, PORT), storage_secret="test storage secret")
            async with core.app.router.lifespan_context(core.app):
                transport = httpx.ASGITransport(core.app)
                async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
                    yield User(client)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)


@pytest.fixture
async def user(guest: User) -> User:
    """A browser that already traded the session token for the cookie."""
    guest.http_client.cookies.set(cookie_name(PORT), TOKEN)
    return guest

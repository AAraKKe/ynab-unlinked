import os
from collections.abc import AsyncIterator

import httpx
import pytest
from nicegui import core, ui
from nicegui.testing.general import prepare_simulation
from nicegui.testing.user import User

from tests.helpers.web import BASE_URL, PORT, TOKEN, fresh_nicegui
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.web import app as web_app
from ynab_unlinked.web import state as web_state
from ynab_unlinked.web.security import cookie_name
from ynab_unlinked.web.state import state


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
    monkeypatch.setattr(web_state, "_STATE", None)
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

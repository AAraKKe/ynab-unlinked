"""Build and start the NiceGUI app behind `yul app`."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from nicegui import app, ui
from nicegui.storage import Storage

from ynab_unlinked.web import frame, shell, storage_dir, theme
from ynab_unlinked.web.security import (
    HOST,
    TOKEN_PARAM,
    TokenGuard,
    entry_url,
    free_port,
    new_token,
)
from ynab_unlinked.web.state import state

STATIC_DIR = Path(__file__).parent / "static"

FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#6366f1"/><stop offset="1" stop-color="#22d3ee"/>'
    "</linearGradient></defs>"
    '<rect width="32" height="32" rx="10" fill="url(#g)"/>'
    '<text x="16" y="21" font-family="system-ui,sans-serif" font-size="13" font-weight="800" '
    'text-anchor="middle" fill="#fff">yul</text></svg>'
)


def build(token: str, port: int) -> Callable[[], Any]:
    """Register the guard, the assets, the pages and the views. Returns the root page.

    `port` is the one the server listens on: the guard only accepts requests addressed to it.
    """
    # Imported here so their @shell.view registrations run whenever the app is built
    from ynab_unlinked.web import views
    from ynab_unlinked.web.views.onboarding.view import page as onboarding_page

    views.register()
    app.add_middleware(TokenGuard, token=token, port=port)
    app.add_static_files(theme.STATIC_ROUTE, STATIC_DIR)
    theme.install()
    ui.button.default_props("no-caps")
    ui.page(shell.ONBOARDING_PATH, title="yul · setup")(onboarding_page)
    return frame.root


def _private_dir(path: Path) -> None:
    """Create `path` for the user only, and narrow one an older yul left readable."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    with suppress(OSError):
        path.chmod(0o700)


def _storage_secret(directory: Path) -> str:
    """Signs the browser session that keys the stored preferences. Kept across runs.

    The file is created readable by the user only (where the system has such modes): it is
    never readable by others, not even for a moment.
    """
    path = directory / "secret"
    if path.is_file():
        with suppress(OSError):
            path.chmod(0o600)
        return path.read_text().strip()
    secret = secrets.token_urlsafe(32)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags, 0o600), "w") as file:
        file.write(secret)
    return secret


def run(
    port: int | None = None,
    open_browser: bool = True,
    announce: Callable[[str], None] | None = None,
) -> None:
    """Serve the app on 127.0.0.1 until interrupted, opening the browser once it is up."""
    token = new_token()
    port = port or free_port()

    directory = storage_dir()
    # The data folder (holding the budget copy too) and the preferences are for the user only
    _private_dir(directory.parent)
    _private_dir(directory)
    # NiceGUI defaults to a .nicegui folder in the working directory
    Storage.path = directory

    state().load()
    # NiceGUI types the handler as a bare `Callable`
    app.on_startup(state().sync_in_background)  # pyright: ignore[reportUnknownMemberType]
    root = build(token, port)

    if announce is not None:
        announce(f"yul is running at {entry_url(port, token)}")
        announce("Press Ctrl+C to stop it.")

    # NiceGUI types the root builder as a bare `Callable`
    ui.run(  # pyright: ignore[reportUnknownMemberType]
        root,
        host=HOST,
        port=port,
        title="yul",
        favicon=FAVICON,
        dark=True,
        reload=False,
        show=f"/?{TOKEN_PARAM}={token}" if open_browser else False,
        storage_secret=_storage_secret(directory),
        show_welcome_message=False,
        uvicorn_logging_level="warning",
    )

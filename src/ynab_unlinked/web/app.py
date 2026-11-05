"""Build and start the NiceGUI app behind `yul app`."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from nicegui import app, ui
from nicegui.storage import Storage

from ynab_unlinked.web import shell, storage_dir, theme
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


def build(token: str) -> Callable[[], Any]:
    """Register the guard, the assets, the pages and the views. Returns the root page."""
    # Imported here so their @shell.view registrations run whenever the app is built
    from ynab_unlinked.web import views
    from ynab_unlinked.web.views import onboarding

    views.register()
    app.add_middleware(TokenGuard, token=token)
    app.add_static_files(theme.STATIC_ROUTE, STATIC_DIR)
    theme.install()
    ui.button.default_props("no-caps")
    ui.page(shell.ONBOARDING_PATH, title="yul · setup")(onboarding.page)
    return shell.root


def _storage_secret(directory: Path) -> str:
    """Signs the browser session that keys the stored preferences. Kept across runs."""
    path = directory / "secret"
    if path.is_file():
        return path.read_text().strip()
    secret = secrets.token_urlsafe(32)
    path.write_text(secret)
    path.chmod(0o600)
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
    directory.mkdir(parents=True, exist_ok=True)
    # NiceGUI defaults to a .nicegui folder in the working directory
    Storage.path = directory

    state().load()
    app.on_startup(state().sync_in_background)
    root = build(token)

    if announce is not None:
        announce(f"yul is running at {entry_url(port, token)}")
        announce("Press Ctrl+C to stop it.")

    ui.run(
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

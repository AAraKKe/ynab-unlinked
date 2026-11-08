"""Typed access to NiceGUI's storages.

NiceGUI types a tab's storage and a user's storage as bare `dict`s. yul only stores its own
objects under `yul.*` keys, and readers check what they get back, so `object` values are
the honest type.
"""

from __future__ import annotations

from typing import cast

from nicegui import app, context
from nicegui.client import Client


def tab_storage(client: Client | None = None) -> dict[str, object]:
    """The storage of one browser tab (`client`, the current one by default)."""
    return cast(dict[str, object], (client or context.client).storage)


def user_storage() -> dict[str, object]:
    """The storage of the browser's user, kept across tabs and runs."""
    return cast(dict[str, object], app.storage.user)

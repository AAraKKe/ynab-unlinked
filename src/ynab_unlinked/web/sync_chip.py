"""The sync chip of the top bar and the words of a sync, shared with Settings."""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from nicegui import ui

from ynab_unlinked.store import SyncResult
from ynab_unlinked.web.components import set_class, spinner
from ynab_unlinked.web.state import state
from ynab_unlinked.web.wording import plural, ynab_error_message

if TYPE_CHECKING:
    from ynab_unlinked.web.shell import ToastKind


def sync_label(last: dt.datetime | None, now: dt.datetime) -> str:
    """ "synced 2 min ago" for the sync chip."""
    if last is None:
        return "not synced yet"
    seconds = max(0, int((now - last).total_seconds()))
    if seconds < 60:
        return "synced just now"
    if seconds < 3600:
        return f"synced {seconds // 60} min ago"
    if seconds < 86400:
        return f"synced {seconds // 3600} h ago"
    return f"synced {plural(seconds // 86400, 'day')} ago"


def sync_message(result: SyncResult) -> str:
    """The toast after a sync: "6 changes pulled from YNAB"."""
    count = result.transactions_changed
    if result.full:
        return f"{plural(count, 'transaction')} loaded from YNAB"
    return f"{plural(count, 'change')} pulled from YNAB"


def sync_chip(
    notify: Callable[[str, ToastKind], None], refresh_view: Callable[[], None]
) -> Callable[[], Awaitable[None]]:
    """The top bar chip: when the budget copy last synced, and a click syncs it now.

    `notify` and `refresh_view` are the shell's, passed in so this module does not import it.
    Returns the sync it runs on a click, for the command palette.
    """
    with ui.element("div").classes("yul-chip click").mark("sync-chip") as chip:
        busy = spinner()
        dot = ui.element("span").classes("yul-dot")
        text = ui.label().classes("yul-sync-text")

    def refresh() -> None:
        current = state()
        busy.set_visibility(current.syncing)
        dot.set_visibility(not current.syncing)
        set_class(dot, "warn", bool(current.sync_error))
        if current.syncing:
            text.set_text("syncing…")
        elif current.sync_error:
            text.set_text("sync failed · retry")
        else:
            text.set_text(sync_label(current.last_sync, dt.datetime.now(dt.UTC)))
        chip.props["title"] = current.sync_error or "Sync with YNAB now"

    async def sync_now() -> None:
        current = state()
        if current.syncing:
            return
        task = current.sync()
        refresh()
        busy.set_visibility(True)
        dot.set_visibility(False)
        text.set_text("syncing…")
        try:
            result = await task
        except Exception as error:
            notify(f"Sync failed. {ynab_error_message(error)}", "error")
        else:
            notify(sync_message(result), "ok")
            if result.full or result.transactions_changed:
                refresh_view()
        refresh()

    chip.on("click", sync_now)
    refresh()
    ui.timer(5.0, refresh)
    return sync_now

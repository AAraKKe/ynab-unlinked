"""What the sticky footer of Reconcile shows: the selection, the lock under way, the lock done."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import ui

from ynab_unlinked.web import shell
from ynab_unlinked.web.components import button, check, spinner
from ynab_unlinked.web.wording import plural


def selection(
    count: int,
    accounts: int,
    *,
    skipped: bool,
    on_select_all: Callable[[bool], Any],
    on_lock_all: Callable[[], Any],
) -> None:
    """What is selected, Select all or Deselect all, and Lock all."""
    with ui.element("div").classes("yul-grow yul-foot-stat"):
        ui.label(f"Lock {plural(count, 'transaction')} in {plural(accounts, 'account')}").classes(
            "main"
        ).mark("rec-summary")
        if skipped:
            ui.label("uncleared stay untouched").classes("yul-muted")
    if count:
        button("Deselect all", kind="ghost", on_click=lambda: on_select_all(False)).mark(
            "deselect-all"
        )
    else:
        button("Select all", kind="ghost", on_click=lambda: on_select_all(True)).mark("select-all")
    lock_all = button("Lock all", kind="primary", on_click=on_lock_all)
    lock_all.mark("lock-all")
    lock_all.set_enabled(count > 0)


def done(locked: int, remaining: int, *, on_lock_more: Callable[[], Any]) -> None:
    """How many were locked, "Lock k more" while selected rows remain, and See net worth."""
    check()
    with ui.element("div").classes("yul-grow yul-foot-stat"):
        ui.label(f"{plural(locked, 'transaction')} locked").classes("main").mark("rec-done")
        ui.label("logged in activity").classes("yul-muted")
    if remaining:
        button(f"Lock {remaining} more", on_click=on_lock_more).mark("lock-more")
    button(
        "See net worth", kind="primary", on_click=lambda: ui.navigate.to(shell.NETWORTH_PATH)
    ).mark("see-networth")


def locking(count: int) -> None:
    """The lock under way."""
    spinner()
    ui.label(f"Locking {plural(count, 'transaction')} in YNAB…").classes("yul-grow")
    with ui.element("div").classes("yul-prog active"):
        ui.element("i")


__all__ = ["done", "locking", "selection"]

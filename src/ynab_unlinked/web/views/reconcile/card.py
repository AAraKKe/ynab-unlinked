"""The pieces of an account card that hold no selection: its header equation, a section
header of its rows and the bar that closes it. `view` draws the rest and keeps them current."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import ui

from ynab_unlinked.web.components import button, icon, pill, set_class
from ynab_unlinked.web.views.reconcile.data import show_label
from ynab_unlinked.web.views.reconcile.groups import AccountGroup


def equation(group: AccountGroup, money: Callable[[int], str]) -> None:
    """YNAB's own header: cleared balance + uncleared balance = working balance."""
    account = group.account
    with ui.element("div").classes("yul-rec-eq"):
        with ui.element("div").classes("yul-rec-term"):
            ui.label(money(account.cleared_balance)).classes("yul-rec-bal")
            with ui.element("div").classes("yul-rec-cap").mark(f"cleared-{account.id}"):
                ui.element("span").classes("yul-rec-dot good")
                ui.label("cleared balance ·")
                group.cleared_count = ui.label().classes("yul-rec-n")
                group.cleared_count.mark(f"cleared-count-{account.id}")
                ui.label("to reconcile")
        with ui.element("div").classes("yul-rec-term"):
            ui.label("+").classes("yul-rec-op")
            ui.label(money(account.uncleared_balance)).classes("yul-rec-fig")
            with ui.element("div").classes("yul-rec-cap").mark(f"uncleared-{account.id}"):
                ui.element("span").classes("yul-rec-dot warn")
                ui.label("uncleared ·")
                group.uncleared_count = ui.label().classes("yul-rec-n")
                group.uncleared_count.mark(f"uncleared-count-{account.id}")
        with ui.element("div").classes("yul-rec-term"):
            ui.label("=").classes("yul-rec-op")
            ui.label(money(account.balance)).classes("yul-rec-fig")
            with ui.element("div").classes("yul-rec-cap"):
                ui.label("working balance")


def section(title: str, dot: str, key: str) -> ui.label:
    """A section header of the rows; returns its note, which the view keeps current."""
    with ui.element("div").classes("yul-rec-sec").mark(f"section-{key}"):
        ui.element("span").classes(f"yul-rec-dot {dot}")
        ui.label(title).classes("name")
        return ui.label().classes("note").mark(f"note-{key}")


def bar(
    group: AccountGroup, *, on_toggle: Callable[[], Any], on_reconcile: Callable[[], Any]
) -> None:
    """The bottom of the card: Show / Hide transactions, and the account's Reconcile."""
    account_id = group.account.id
    group.bar = ui.element("div").classes("yul-rec-bar").mark(f"bar-{account_id}")
    with group.bar:
        toggle = button(kind="ghost", on_click=on_toggle)
        toggle.classes("yul-rec-toggle").mark(f"toggle-{account_id}")
        with toggle:
            group.toggle_label = ui.label()
            icon("chevron-down", 18)
        group.action = ui.element("div").classes("yul-rec-lockcell")
        with group.action:
            group.lock_button = button(on_click=on_reconcile)
            group.lock_button.mark(f"lock-{account_id}")
            with group.lock_button:
                group.lock_label = ui.label()
            group.done = pill("🔒 reconciled", "ok")
            group.done.set_visibility(False)
    paint_bar(group)


def paint_bar(group: AccountGroup) -> None:
    """Collapsed, the bar is one button: nothing is reconciled without seeing the rows."""
    assert group.bar is not None and group.toggle_label is not None
    assert group.action is not None
    set_class(group.bar, "open", group.open)
    group.toggle_label.set_text("Hide transactions" if group.open else show_label(len(group.rows)))
    group.action.set_visibility(group.open)

"""The Accounts card of Net worth: a row per counted account and the inline balance editor.

Every row has a pencil (always shown and accent coloured on "by hand" rows) that turns its
balance into an input with a check and a cross (DESIGN rule 5); the check creates the one
adjustment that takes the account to the typed balance. The table outlives the view's
re-renders, so an open editor and what was typed in it survive a sync.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable

from nicegui import run, ui

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import TrackedAccount
from ynab_unlinked.web import shell
from ynab_unlinked.web.buckets import NET_WORTH_ORDER, STYLES
from ynab_unlinked.web.components import (
    button,
    clickable,
    glass_card,
    pill,
    section_title,
    set_class,
    share_bar,
)
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.networth.data import (
    Snapshot,
    by_hand_pill,
    parse_balance,
    set_balance,
    signed,
    table_order,
)
from ynab_unlinked.web.wording import ynab_error_message


class AccountsTable:
    def __init__(
        self,
        root: ui.element,
        refresh: Callable[[], Awaitable[None]],
        open_drawer: Callable[[str], Awaitable[None]],
    ) -> None:
        self.root = root
        """Toasts are shown from here: the button that started them may be gone."""
        self.refresh = refresh
        self.open_drawer = open_drawer
        self.snapshot: Snapshot | None = None
        self.editing: str | None = None
        """The account whose balance is open for editing; one at a time."""
        self.draft = ""
        """What is typed in the open editor, kept across re-renders."""
        self.hint = ""
        self.hint_label: ui.label | None = None
        self.busy = False
        self.rows: dict[str, tuple[ui.element, Callable[[], None]]] = {}

    def reset(self, snapshot: Snapshot) -> None:
        """Before the view redraws: forget the rows, and the editor of an account now gone."""
        self.snapshot = snapshot
        self.rows = {}
        if self.editing is not None and all(a.id != self.editing for a in snapshot.tracked):
            self.editing = None

    # ---- drawing ---------------------------------------------------------------------------

    def draw(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        shares = {
            a.id: snapshot.worth.share(a.id)
            for a in snapshot.tracked
            if a.bucket is not Bucket.DEBT
        }
        widest = max([*shares.values(), 0.0])
        ordered = table_order(snapshot)

        with glass_card().classes("yul-nw-accounts").mark("accounts-card"):
            with ui.element("div").classes("yul-row yul-nw-accounts-head"):
                ui.label("Accounts").style("font-weight:600")
                ui.element("span").classes("yul-grow")
                ui.label("set an account's real balance with its pencil").classes(
                    "yul-faint"
                ).style("font-size:12px")

            for bucket in NET_WORTH_ORDER:
                accounts = [a for a in ordered if a.bucket is bucket]
                if not accounts:
                    continue
                style = STYLES[bucket]
                section_title(style.group_title, swatch=style.series).mark(f"group-{bucket.value}")
                with ui.element("div").classes("yul-stagger"):
                    for account in accounts:
                        self._row(snapshot, account, style.color, shares, widest)

    def _row(
        self,
        snapshot: Snapshot,
        account: TrackedAccount,
        color: str,
        shares: dict[str, float],
        widest: float,
    ) -> None:
        formatter = state().require_formatter()
        debt = account.bucket is Bucket.DEBT
        balance = snapshot.raw(account.id) if debt else snapshot.netted(account.id)
        row = ui.element("div").classes("yul-nw-arow").mark(f"row-{account.id}")

        def fill() -> None:
            editing = self.editing == account.id
            row.clear()
            set_class(row, "editing", editing)
            with row:
                with ui.element("div").classes("yul-nw-name-cell"):
                    name = ui.label(snapshot.name(account)).classes("yul-nw-name")
                    name.mark(f"name-{account.id}")
                    clickable(name, lambda: self.open_drawer(account.id))
                    if account.track_balance:
                        text, kind = by_hand_pill(
                            snapshot.last_set.get(account.id), dt.date.today()
                        )
                        pill(text, kind).mark(f"age-{account.id}")
                if editing:
                    self._editor(account)
                    return
                ui.label(formatter.format_amount_milli(balance)).classes("yul-nw-balance yul-num")
                with ui.element("div").classes("yul-nw-share"):
                    if debt:
                        netted = "netted" if snapshot.mapped(account.id) else "not netted"
                        ui.label(netted).classes("yul-nw-pct yul-faint").style("margin-left:auto")
                    else:
                        fraction = shares[account.id]
                        share_bar(fraction / widest if widest > 0 else 0, color)
                        ui.label(f"{fraction * 100:.1f}%").classes("yul-nw-pct yul-faint yul-num")
                edit = button(
                    icon_name="pencil",
                    kind="ghost",
                    small=True,
                    on_click=lambda: self.start_edit(account.id),
                ).classes("yul-nw-edit")
                if account.track_balance:
                    edit.classes("always")
                edit.props["title"] = "Set balance"
                edit.props["aria-label"] = f"Set the balance of {snapshot.name(account)}"
                edit.mark(f"edit-{account.id}")

        self.rows[account.id] = (row, fill)
        fill()

    def _editor(self, account: TrackedAccount) -> None:
        """The balance cell of the row being edited: input, check and cross."""
        with ui.element("div").classes("yul-nw-editor"):
            with ui.element("div").classes("yul-nw-editor-field"):
                field = (
                    ui.input(value=self.draft, on_change=lambda e: self._typed(str(e.value or "")))
                    .props(
                        'outlined dense autofocus inputmode=decimal input-style="text-align:right"'
                    )
                    .classes("yul-nw-input")
                    .mark(f"balance-input-{account.id}")
                )
                field.on("keydown.enter", lambda: self.accept(account.id))
                field.on("keydown.escape", self.cancel_edit)
                self.hint_label = (
                    ui.label(self.hint)
                    .classes("yul-bad yul-nw-hint")
                    .mark(f"balance-hint-{account.id}")
                )
                self.hint_label.set_visibility(bool(self.hint))
            accept = button(
                icon_name="check",
                kind="primary",
                small=True,
                on_click=lambda: self.accept(account.id),
            ).mark(f"accept-{account.id}")
            accept.props["title"] = "Set this balance"
            cancel = button(
                icon_name="x", kind="ghost", small=True, on_click=self.cancel_edit
            ).mark(f"cancel-{account.id}")
            cancel.props["title"] = "Cancel"

    # ---- balance updates -------------------------------------------------------------------

    def _refill(self, account_id: str | None) -> None:
        if account_id is None or account_id not in self.rows:
            return
        row, fill = self.rows[account_id]
        if not row.is_deleted:
            fill()

    def start_edit(self, account_id: str) -> None:
        """Open the editor on this row, closing any other, prefilled with the YNAB balance."""
        if self.snapshot is None or self.busy:
            return
        previous, self.editing = self.editing, account_id
        formatter = state().require_formatter()
        self.draft = formatter.format_amount_milli(self.snapshot.raw(account_id))
        self.hint = ""
        if previous != account_id:
            self._refill(previous)
        self._refill(account_id)

    def cancel_edit(self) -> None:
        if self.busy:
            return
        previous, self.editing = self.editing, None
        self.draft = self.hint = ""
        self._refill(previous)

    def _show_hint(self, text: str) -> None:
        self.hint = text
        if self.hint_label is not None and not self.hint_label.is_deleted:
            self.hint_label.set_text(text)
            self.hint_label.set_visibility(bool(text))

    def _typed(self, text: str) -> None:
        self.draft = text
        if self.hint:
            self._show_hint("")

    async def accept(self, account_id: str) -> None:
        """Create the adjustment that takes the account to the typed balance. No dialog."""
        snapshot = self.snapshot
        if snapshot is None or self.editing != account_id or self.busy:
            return
        config, client = state().require()
        wanted = parse_balance(self.draft, config.budget.currency_format)
        if wanted is None:
            self._show_hint("Not an amount")
            return
        current = snapshot.raw(account_id)
        if wanted == current:
            self.cancel_edit()
            # The check that started this is gone with the editor, so toast from the root
            with self.root:
                shell.notify("No change", "info")
            return

        formatter = state().require_formatter()
        account = next(a for a in snapshot.tracked if a.id == account_id)
        name = snapshot.name(account)
        budget_id = config.budget.id

        self.busy = True
        try:
            adjustments = await run.io_bound(
                set_balance, client, config, account_id, wanted, dt.date.today()
            )
        except Exception as error:
            with self.root:
                shell.notify(
                    f"The balance of {name} was not set. {ynab_error_message(error)}", "error"
                )
            return
        finally:
            self.busy = False
        if adjustments is None:
            return

        self.editing = None
        self.draft = self.hint = ""
        if not adjustments:
            # YNAB already had that balance: only the budget copy was behind
            state().invalidate()
            await self.refresh()
            with self.root:
                shell.notify("No change", "info")
            return

        adjustment = adjustments[0]
        new = formatter.format_amount_milli(adjustment.new_balance)
        difference = signed(formatter, adjustment.amount)
        await run.io_bound(
            state().store.log,
            budget_id,
            "adjustment",
            f"Balance of {name} set to {new} ({difference})",
            {
                "account_id": adjustment.account_id,
                "account_name": name,
                "old": adjustment.old_balance,
                "new": adjustment.new_balance,
                "amount": adjustment.amount,
            },
        )
        state().invalidate()
        await self.refresh()
        with self.root:
            shell.notify(f"{name} set to {new} ({difference})")

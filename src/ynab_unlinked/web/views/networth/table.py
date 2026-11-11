"""The Accounts card of Net worth: a row per counted account and the inline balance editors.

Every row has a pencil (always shown and accent coloured on "by hand" rows) that turns its
balance into an input with a check and a cross (DESIGN rule 5); the check creates the one
adjustment that takes the account to the typed balance. "Update balances" in the header turns
every by hand balance into a field at once, Tab moving from one to the next, and saves the
changed ones as one batch. The table outlives the view's re-renders, so an open editor and
what was typed in it survive a sync.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable

from nicegui import run, ui

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import TrackedAccount
from ynab_unlinked.core.balances import Adjustment
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
    Drafts,
    Snapshot,
    adjustment_entry,
    by_hand_pill,
    changed_count,
    diff_label,
    parse_balance,
    plain_amount,
    read_drafts,
    save_label,
    set_balance,
    set_balances,
    signed,
    table_order,
)
from ynab_unlinked.web.wording import plural, ynab_error_message


def select_on_focus(field: ui.input) -> None:
    """Select the field's text whenever it gets focus, so typing replaces the balance."""
    field.on("focus", js_handler="(e) => e.target.select()")


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
        self.card: ui.element | None = None
        self.bulk = False
        """The "Update balances" mode: every by hand balance is a field."""
        self.typed: dict[str, str] = {}
        """In that mode, the text of each field by account id, in table order."""
        self.focus_first = False
        self.fields: dict[str, ui.input] = {}
        self.diffs: dict[str, ui.label] = {}
        self.foot: ui.element | None = None

    def reset(self, snapshot: Snapshot) -> None:
        """Before the view redraws: forget the rows, and the editor of an account now gone."""
        self.snapshot = snapshot
        self.rows = {}
        if self.editing is not None and all(a.id != self.editing for a in snapshot.tracked):
            self.editing = None
        if self.bulk:
            # Keep what was typed; a by hand account that appeared starts at its balance
            self.typed = self._prefilled(snapshot, keep=self.typed)
            self.bulk = bool(self.typed)

    def _prefilled(self, snapshot: Snapshot, keep: dict[str, str]) -> dict[str, str]:
        config, _ = state().require()
        currency_format = config.budget.currency_format
        return {
            a.id: keep[a.id] if a.id in keep else plain_amount(snapshot.raw(a.id), currency_format)
            for a in table_order(snapshot)
            if a.track_balance
        }

    def _drafts(self) -> Drafts:
        assert self.snapshot is not None
        config, _ = state().require()
        current = {account_id: self.snapshot.raw(account_id) for account_id in self.typed}
        return read_drafts(self.typed, current, config.budget.currency_format)

    # ---- drawing ---------------------------------------------------------------------------

    def draw(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        self.card = glass_card().classes("yul-nw-accounts").mark("accounts-card")
        self._fill()

    def _fill(self) -> None:
        """Draw the card's contents: header, a group per bucket, the mode's footer."""
        snapshot, card = self.snapshot, self.card
        if snapshot is None or card is None or card.is_deleted:
            return
        shares = {
            a.id: snapshot.worth.share(a.id)
            for a in snapshot.tracked
            if a.bucket is not Bucket.DEBT
        }
        widest = max([*shares.values(), 0.0])
        ordered = table_order(snapshot)
        self.rows, self.fields, self.diffs, self.foot = {}, {}, {}, None
        card.clear()
        set_class(card, "bulk", self.bulk)

        with card:
            with ui.element("div").classes("yul-row yul-nw-accounts-head"):
                ui.label("Accounts").style("font-weight:600")
                ui.element("span").classes("yul-grow")
                if self.bulk:
                    button(
                        "Cancel", kind="ghost", small=True, icon_name="x", on_click=self.cancel_bulk
                    ).mark("cancel-balances")
                elif any(a.track_balance for a in ordered):
                    button(
                        "Update balances",
                        kind="ghost",
                        small=True,
                        icon_name="pencil",
                        on_click=self.start_bulk,
                    ).mark("update-balances")
                else:
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

            if self.bulk:
                self.foot = ui.element("div").classes("yul-nw-bulk-foot").mark("balances-foot")
                self._update_bulk()
        self.focus_first = False

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

        def share() -> None:
            with ui.element("div").classes("yul-nw-share"):
                if debt:
                    netted = "netted" if snapshot.mapped(account.id) else "not netted"
                    ui.label(netted).classes("yul-nw-pct yul-faint").style("margin-left:auto")
                else:
                    fraction = shares[account.id]
                    share_bar(fraction / widest if widest > 0 else 0, color)
                    ui.label(f"{fraction * 100:.1f}%").classes("yul-nw-pct yul-faint yul-num")

        def fill() -> None:
            editing = self.editing == account.id
            row.clear()
            set_class(row, "editing", editing)
            with row:
                with ui.element("div").classes("yul-nw-name-cell"):
                    name = ui.label(snapshot.name(account)).classes("yul-nw-name")
                    name.mark(f"name-{account.id}")
                    clickable(name, lambda: self.open_drawer(account.id))
                    if self.bulk:
                        # Tab goes from one balance field to the next, not through the names
                        name.props["tabindex"] = "-1"
                    if account.track_balance:
                        text, kind = by_hand_pill(
                            snapshot.last_set.get(account.id), dt.date.today()
                        )
                        pill(text, kind).mark(f"age-{account.id}")
                if self.bulk:
                    if account.id in self.typed:
                        self._bulk_field(account)
                    else:
                        ui.label(formatter.format_amount_milli(balance)).classes(
                            "yul-nw-balance yul-num"
                        )
                        ui.element("span")
                    share()
                    return
                if editing:
                    self._editor(account)
                    return
                ui.label(formatter.format_amount_milli(balance)).classes("yul-nw-balance yul-num")
                share()
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
                select_on_focus(field)
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

    def _bulk_field(self, account: TrackedAccount) -> None:
        """A by hand row's balance in the "Update balances" mode: its field, then its change."""
        account_id = account.id
        assert self.snapshot is not None
        field = (
            ui.input(
                value=self.typed[account_id],
                on_change=lambda e: self._bulk_typed(account_id, str(e.value or "")),
            )
            .props('outlined dense inputmode=decimal input-style="text-align:right"')
            .classes("yul-nw-input yul-nw-bulk-input")
            .mark(f"balance-{account_id}")
        )
        field.props["aria-label"] = f"Balance of {self.snapshot.name(account)}"
        if self.focus_first and account_id == next(iter(self.typed)):
            field.props["autofocus"] = True
        select_on_focus(field)
        field.on("keydown.enter", self.save_bulk)
        field.on("keydown.escape", self.cancel_bulk)
        self.fields[account_id] = field
        self.diffs[account_id] = ui.label().classes("yul-nw-diff").mark(f"delta-{account_id}")

    def _update_bulk(self) -> None:
        """Show each field's change, the count and the Save button for what is typed now."""
        if not self.bulk or self.snapshot is None:
            return
        formatter = state().require_formatter()
        drafts = self._drafts()
        for account_id, diff in drafts.diffs.items():
            text, kind = diff_label(formatter, diff)
            if (label := self.diffs.get(account_id)) is not None and not label.is_deleted:
                label.set_text(text)
                for name in ("good", "bad", "faint"):
                    set_class(label, f"yul-{name}", kind == name)
            if (field := self.fields.get(account_id)) is not None and not field.is_deleted:
                set_class(field, "invalid", diff is None)

        foot = self.foot
        if foot is None or foot.is_deleted:
            return
        foot.clear()
        with foot:
            with ui.element("div").classes("yul-nw-bulk-hint yul-faint"):
                ui.label(changed_count(drafts)).classes("yul-nw-bulk-count").mark("balances-count")
                ui.label("·")
                ui.label("Tab").classes("yul-nw-kbd")
                ui.label("next ·")
                ui.label("Enter").classes("yul-nw-kbd")
                ui.label("save all")
            save = button(save_label(drafts), kind="primary", on_click=self.save_bulk)
            save.mark("save-balances")
            save.set_enabled(drafts.can_save and not self.busy)
            if drafts.invalid:
                save.props["title"] = "Fix the balances that are not a number first"

    # ---- balance updates -------------------------------------------------------------------

    def _refill(self, account_id: str | None) -> None:
        if account_id is None or account_id not in self.rows:
            return
        row, fill = self.rows[account_id]
        if not row.is_deleted:
            fill()

    def start_edit(self, account_id: str) -> None:
        """Open the editor on this row, closing any other, prefilled with the YNAB balance."""
        if self.snapshot is None or self.busy or self.bulk:
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

    def _names(self) -> dict[str, str]:
        assert self.snapshot is not None
        return {a.id: self.snapshot.name(a) for a in self.snapshot.tracked}

    async def _log(self, adjustments: list[Adjustment], names: dict[str, str]) -> None:
        """One `adjustment` activity entry per adjustment, each written off the event loop."""
        config, _ = state().require()
        formatter = state().require_formatter()
        for adjustment in adjustments:
            message, details = adjustment_entry(formatter, adjustment, names[adjustment.account_id])
            await run.io_bound(state().store.log, config.budget.id, "adjustment", message, details)

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
        await self._log(adjustments, {account_id: name})
        state().invalidate()
        await self.refresh()
        with self.root:
            shell.notify(f"{name} set to {new} ({difference})")

    # ---- the "Update balances" mode --------------------------------------------------------

    def start_bulk(self) -> None:
        """Turn every by hand balance into a field, the first one focused, the pencils hidden."""
        if self.snapshot is None or self.busy or self.bulk:
            return
        self.editing = None
        self.draft = self.hint = ""
        self.typed = self._prefilled(self.snapshot, keep={})
        self.bulk = bool(self.typed)
        self.focus_first = True
        self._fill()

    def cancel_bulk(self) -> None:
        """Leave the mode and drop what was typed: nothing was written, so nothing to confirm."""
        if self.busy or not self.bulk:
            return
        self.bulk = False
        self.typed = {}
        self._fill()

    def _bulk_typed(self, account_id: str, text: str) -> None:
        if not self.bulk or account_id not in self.typed:
            return
        self.typed[account_id] = text
        self._update_bulk()

    async def save_bulk(self) -> None:
        """Create the adjustments of every changed field in one batch. The deltas shown in the
        rows are the confirmation (DESIGN rule 8), so no dialog."""
        if self.snapshot is None or not self.bulk or self.busy:
            return
        drafts = self._drafts()
        if not drafts.can_save:
            return
        config, client = state().require()
        names = self._names()

        self.busy = True
        self._update_bulk()
        try:
            adjustments = await run.io_bound(
                set_balances, client, config, drafts.wanted, dt.date.today()
            )
        except Exception as error:
            with self.root:
                shell.notify(f"The balances were not updated. {ynab_error_message(error)}", "error")
            return
        finally:
            self.busy = False
            self._update_bulk()

        self.bulk = False
        self.typed = {}
        if adjustments:
            await self._log(adjustments, names)
        state().invalidate()
        await self.refresh()
        with self.root:
            if adjustments:
                shell.notify(f"Updated {plural(len(adjustments), 'balance')}")
            else:
                # YNAB already had those balances: only the budget copy was behind
                shell.notify("No change", "info")

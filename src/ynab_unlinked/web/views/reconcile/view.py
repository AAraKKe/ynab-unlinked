"""Reconcile: compare each account's cleared balance with the bank and lock what it confirmed.

Everything on screen comes from the local store, synced first when it is older than ten
minutes. The only write to YNAB is `core.reconcile.reconcile`, behind one confirmation, in
`lock`. What is shown and written is worked out in `data`; this module keeps the selection
(`groups`) and draws it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from functools import partial

from nicegui import run, ui
from ynab import TransactionClearedStatus

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.store import StoredAccount, StoredTransaction
from ynab_unlinked.web import shell
from ynab_unlinked.web.components import (
    button,
    check,
    empty_state,
    glass_card,
    loading,
    pill,
    set_class,
)
from ynab_unlinked.web.components.controls import pill_group, switch
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.reconcile import footer
from ynab_unlinked.web.views.reconcile import lock as lock_step
from ynab_unlinked.web.views.reconcile.data import (
    ALL_TIME,
    SINCE,
    SYNC_MAX_AGE,
    UNCLEARED_SKIPPED,
    ReconcileData,
    gap_candidates,
    parse_bank_balance,
    pending_title,
    scope_start,
)
from ynab_unlinked.web.views.reconcile.groups import AccountGroup, Row
from ynab_unlinked.web.wording import plural, short_date, ynab_error_message


class ReconcileView:
    def __init__(self, config: LatestConfig, formatter: Formatter) -> None:
        self.budget_id = config.budget.id
        self.currency = config.budget.currency_format
        self.formatter = formatter
        self.since = scope_start(config.last_reconciliation_date)
        self.scope = SINCE if self.since is not None else ALL_TIME
        self.include_uncleared = False
        self.busy = False
        self.data = ReconcileData()
        self.groups: list[AccountGroup] = []
        self.locked_ids: set[str] = set()
        self.last_locked = 0
        self.today = dt.date.today()
        self.root: ui.element | None = None
        self.title: ui.label | None = None
        self.list: ui.element | None = None
        self.footer: ui.element | None = None

    # ---- data ----------------------------------------------------------------------------

    def money(self, milliunits: int) -> str:
        return self.formatter.format_amount_milli(milliunits)

    async def load(self) -> None:
        data = await run.io_bound(ReconcileData.read, state().store, self.budget_id)
        if data is not None:
            self.data = data

    async def ensure_fresh(self) -> bool:
        """Sync the store when it is older than ten minutes or something was written to YNAB
        since (an import, a lock, a balance update). False if it was never synced."""
        current = state()
        if await run.io_bound(current.fresh, SYNC_MAX_AGE):
            return True
        try:
            await current.sync()
        except Exception as error:
            shell.notify(f"Showing the last sync. {ynab_error_message(error)}", "warn")
        return current.last_sync is not None

    def open_transactions(self) -> list[tuple[StoredAccount, list[StoredTransaction]]]:
        """Unreconciled transactions of open accounts in the current scope, newest first."""
        since = self.since if self.scope == SINCE else None
        return self.data.open_transactions(since, self.locked_ids)

    # ---- page ----------------------------------------------------------------------------

    async def render(self) -> None:
        self.root = ui.element("div").mark("reconcile")
        with self.root, ui.element("div").classes("yul-row"):
            loading("Getting the latest from YNAB…")

        synced = await self.ensure_fresh()
        await self.load()
        if not synced and not self.data.accounts:
            self.root.clear()
            with self.root:
                empty_state(
                    "Could not load your accounts from YNAB yet.",
                    icon_name="refresh",
                    action_label="Try again",
                    on_action=lambda: ui.navigate.to(shell.RECONCILE_PATH),
                )
            return
        self.build()

    def build(self) -> None:
        """Header, account cards and footer for the current scope, or the empty state."""
        assert self.root is not None
        self.root.clear()
        with self.root:
            if not self.data.has_anything(self.locked_ids):
                self.all_reconciled()
                return
            self.header()
            self.list = ui.element("div")
            self.footer = ui.element("div").classes("yul-foot").mark("rec-footer")
        self.render_list()

    def all_reconciled(self) -> None:
        empty_state(
            "All accounts are reconciled",
            icon_name="reconcile",
            action_label="See net worth",
            on_action=lambda: ui.navigate.to(shell.NETWORTH_PATH),
        ).mark("all-reconciled")

    def header(self) -> None:
        with ui.element("div").classes("yul-rec-head"):
            with ui.element("div").classes("yul-grow"):
                self.title = ui.label().classes("yul-h2").mark("rec-title")
                ui.label(
                    "Type the balance your bank shows to check it matches before locking. "
                    "Nothing here changes a balance."
                ).classes("yul-lede")
            options = {ALL_TIME: "all time"}
            if self.since is not None:
                options = {SINCE: f"since {short_date(self.since, self.today)}", **options}
            pill_group(options, self.scope, self.change_scope, marker="scope")
            switch("include uncleared", self.include_uncleared, self.set_include_uncleared).mark(
                "include-uncleared"
            )

    async def change_scope(self, scope: str) -> None:
        if scope == self.scope:
            return
        self.scope = scope
        await self.load()
        self.render_list()

    def render_list(self) -> None:
        assert self.list is not None and self.footer is not None
        self.groups = [
            AccountGroup(
                account=account,
                rows=[
                    Row(
                        transaction=t,
                        selected=self.include_uncleared
                        or t.cleared is not TransactionClearedStatus.UNCLEARED,
                    )
                    for t in transactions
                ],
            )
            for account, transactions in self.open_transactions()
        ]
        self.list.clear()
        with self.list:
            if not self.groups:
                since = self.since or self.today
                empty_state(
                    f"Nothing to reconcile since {short_date(since, self.today)}",
                    icon_name="reconcile",
                    action_label="Show all time",
                    on_action=lambda: self.list_all_time(),
                ).mark("scope-empty")
            else:
                with ui.element("div").classes("yul-stagger"):
                    for group in self.groups:
                        self.card(group)
                for current, following in zip(self.groups, self.groups[1:], strict=False):
                    self.chain_focus(current, following)
        self.footer.set_visibility(bool(self.groups))
        self.last_locked = 0
        self.refresh()

    async def list_all_time(self) -> None:
        self.scope = ALL_TIME
        await self.load()
        self.build()

    # ---- account card --------------------------------------------------------------------

    def card(self, group: AccountGroup) -> None:
        account = group.account
        with glass_card(flush=True).classes("yul-rec-acct").mark(f"account-{account.id}"):
            with ui.element("div").classes("yul-rec-ah"):
                with ui.element("div"):
                    ui.label(account.name).classes("yul-label")
                    ui.label(self.money(account.cleared_balance)).classes("yul-rec-bal")
                    ui.label(
                        f"cleared · uncleared {self.money(account.uncleared_balance)}"
                        f" · total {self.money(account.balance)}"
                    ).classes("yul-faint yul-small")
                with ui.element("div").classes("yul-rec-bank"):
                    ui.label("Your bank says").classes("yul-label")
                    group.bank = (
                        ui.input(
                            placeholder="Type it to check",
                            on_change=lambda event, group=group: self.bank_changed(
                                group, str(event.value or "")
                            ),
                        )
                        .props("outlined dense autocomplete=off inputmode=decimal")
                        .mark(f"bank-{account.id}")
                    )
                    group.match = (
                        ui.element("div").classes("yul-rec-match").mark(f"match-{account.id}")
                    )
                with ui.element("div"):
                    ui.label("To lock").classes("yul-label")
                    group.count = ui.label().classes("yul-rec-bal").mark(f"count-{account.id}")
                    group.toggle = ui.label("show transactions ▾").classes("yul-rec-link")
                    group.toggle.mark(f"toggle-{account.id}")
                    group.toggle.on(
                        "click", lambda _, group=group: self.set_open(group, not group.open)
                    )
                with ui.element("div").classes("yul-rec-lockcell"):
                    group.lock_button = button(on_click=partial(self.lock, [group]))
                    group.lock_button.mark(f"lock-{account.id}")
                    with group.lock_button:
                        group.lock_label = ui.label()
                    group.done = pill("🔒 reconciled", "ok")
                    group.done.set_visibility(False)
            group.rows_box = ui.element("div").classes("yul-rec-rows")
            with group.rows_box:
                for row in group.rows:
                    self.row(row)
            group.rows_box.set_visibility(False)

    def chain_focus(self, current: AccountGroup, following: AccountGroup) -> None:
        """Enter in a bank balance moves on to the next account's."""
        assert current.bank is not None and following.bank is not None
        target = following.bank
        current.bank.on("keydown.enter", lambda: target.run_method("focus"))

    def set_open(self, group: AccountGroup, open_: bool) -> None:
        group.open = open_
        assert group.rows_box is not None and group.toggle is not None
        group.rows_box.set_visibility(open_)
        group.toggle.set_text("hide transactions ▴" if open_ else "show transactions ▾")

    def bank_changed(self, group: AccountGroup, text: str) -> None:
        assert group.match is not None
        self.highlight(group, set())
        group.match.clear()
        typed = parse_bank_balance(text, self.currency)
        if typed is None and text.strip():
            with group.match:
                ui.label("Not an amount").classes("yul-faint")
        if typed is None:
            group.matches = None
            group.difference = 0
            self.refresh()
            return

        group.difference = typed - group.account.cleared_balance
        group.matches = group.difference == 0
        with group.match:
            if group.matches:
                check()
                ui.label("Matches").classes("yul-good")
            else:
                ui.label(f"off by {self.money(group.difference)}").classes("yul-warn")
                ui.label("find the gap").classes("yul-rec-gap-link").mark(
                    f"gap-{group.account.id}"
                ).on("click", lambda _, group=group: self.find_gap(group))
        self.refresh()

    def find_gap(self, group: AccountGroup) -> None:
        candidates = gap_candidates([row.transaction for row in group.pending()], group.difference)
        self.set_open(group, True)
        self.highlight(group, candidates)
        amount = self.money(group.difference)
        if candidates:
            shell.notify(
                f"{plural(len(candidates), 'highlighted transaction')} could explain {amount}",
                "info",
            )
        else:
            shell.notify(f"No transaction or pair of them adds up to {amount}", "warn")

    @staticmethod
    def highlight(group: AccountGroup, ids: set[str]) -> None:
        for row in group.rows:
            if row.element is None:
                continue
            set_class(row.element, "gap", row.transaction.id in ids)

    # ---- rows ----------------------------------------------------------------------------

    def row(self, row: Row) -> None:
        t = row.transaction
        with ui.element("div").classes("yul-rec-row").mark(f"row-{t.id}") as element:
            row.box = ui.element("span").classes("yul-rec-cb")
            ui.label(short_date(t.date, self.today)).classes("yul-num yul-faint")
            ui.label(t.payee_name or t.memo or "No payee").classes("payee")
            amount = ui.label(self.money(t.amount)).classes("amt")
            if t.amount > 0:
                amount.classes("yul-good")
            row.status = ui.label().classes("st")
        row.element = element
        element.on("click", lambda _, row=row: self.toggle_row(row))
        self.paint_row(row)

    def paint_row(self, row: Row) -> None:
        assert row.element is not None and row.box is not None and row.status is not None
        selectable = not row.uncleared or self.include_uncleared
        set_class(row.box, "on", row.selected or row.locked)
        set_class(row.box, "off", not selectable and not row.locked)
        set_class(row.element, "unclear", row.uncleared and not row.locked)
        if row.locked:
            row.element.classes(add="locked", remove="gap")
            row.status.set_text("🔒 reconciled")
        elif row.uncleared:
            row.status.set_text("uncleared → 🔒" if row.selected else "uncleared")
        else:
            row.status.set_text("cleared → 🔒" if row.selected else "cleared")

    def toggle_row(self, row: Row) -> None:
        if row.locked or self.busy:
            return
        if row.uncleared and not self.include_uncleared:
            shell.notify(UNCLEARED_SKIPPED, "info")
            return
        row.selected = not row.selected
        self.paint_row(row)
        self.last_locked = 0
        self.refresh()

    def set_include_uncleared(self, on: bool) -> None:
        self.include_uncleared = on
        for group in self.groups:
            for row in group.pending():
                if row.uncleared:
                    row.selected = on
                    self.paint_row(row)
        self.last_locked = 0
        self.refresh()

    def set_all(self, selected: bool) -> None:
        for group in self.groups:
            for row in group.pending():
                if not row.uncleared or self.include_uncleared:
                    row.selected = selected
                    self.paint_row(row)
        self.last_locked = 0
        self.refresh()

    # ---- counts and footer ---------------------------------------------------------------

    def refresh(self) -> None:
        pending_rows = sum(len(group.pending()) for group in self.groups)
        pending_accounts = sum(1 for group in self.groups if group.pending())
        if self.title is not None:
            self.title.set_text(pending_title(pending_accounts, pending_rows, bool(self.groups)))

        for group in self.groups:
            to_lock = len(group.to_lock())
            left = bool(group.pending())
            assert group.count is not None and group.lock_button is not None
            assert group.lock_label is not None and group.done is not None
            group.count.set_text(str(to_lock))
            group.lock_label.set_text(f"Lock {plural(to_lock, 'transaction')}")
            group.lock_button.set_enabled(to_lock > 0 and not self.busy)
            group.lock_button.set_visibility(left)
            group.done.set_visibility(not left)
            set_class(group.lock_button, "primary", bool(group.matches))
        self.render_footer()

    def render_footer(self) -> None:
        if self.footer is None or self.busy:
            return
        selected = [group.to_lock() for group in self.groups]
        count = sum(len(rows) for rows in selected)
        accounts = sum(1 for rows in selected if rows)
        skipped = not self.include_uncleared and any(
            row.uncleared for group in self.groups for row in group.pending()
        )
        self.footer.clear()
        with self.footer:
            if self.last_locked:
                footer.done(self.last_locked, count, on_lock_more=lambda: self.lock(self.groups))
                return
            footer.selection(
                count,
                accounts,
                skipped=skipped,
                on_select_all=self.set_all,
                on_lock_all=lambda: self.lock(self.groups),
            )

    # ---- lock ----------------------------------------------------------------------------

    async def lock(self, groups: Sequence[AccountGroup]) -> None:
        await lock_step.lock(self, groups)


@shell.view(
    shell.RECONCILE_PATH,
    key="reconcile",
    title="Reconcile",
    subtitle="Lock what the bank confirmed",
    icon="reconcile",
    order=30,
)
async def reconcile_view() -> None:
    config, _ = state().require()
    await ReconcileView(config, state().require_formatter()).render()

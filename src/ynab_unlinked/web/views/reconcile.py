"""Reconcile: compare each account's cleared balance with the bank and lock what it confirmed.

Everything on screen comes from the local store, synced first when it is older than ten
minutes. The only write to YNAB is `core.reconcile.reconcile`, behind one confirmation.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from nicegui import run, ui
from ynab import TransactionClearedStatus, TransactionDetail

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.balances import parse_amount_to_milliunits
from ynab_unlinked.core.reconcile import next_reconciliation_date, reconcile
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.store import StoredAccount, StoredTransaction
from ynab_unlinked.web import shell
from ynab_unlinked.web.components import button, check, empty_state, glass_card, pill, spinner
from ynab_unlinked.web.components.reconcile_controls import add_css_once, pill_group, switch
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.onboarding import ynab_error_message

NETWORTH_PATH = "/networth"
SYNC_MAX_AGE = dt.timedelta(minutes=10)
SCOPE_BUFFER_DAYS = 7
"""How far before the last reconciliation the "since" scope starts, as `yul reconcile -b`."""

SINCE = "since"
ALL_TIME = "all"
UNCLEARED_SKIPPED = "Uncleared rows are skipped. Turn on “include uncleared” to lock them too."

CSS = """
.yul-rec-head { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 14px; }
.yul-rec-head .yul-lede { margin: 0; }
.yul-rec-acct { margin-bottom: 12px; }
.yul-rec-ah {
  display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) minmax(0, 1fr) auto;
  gap: 14px; padding: 16px 18px; align-items: center;
}
.yul-rec-bal {
  font-size: 22px; font-weight: 700; letter-spacing: -.02em; line-height: 1.25;
  font-variant-numeric: tabular-nums;
}
.yul-rec-bank .q-field { width: 160px; margin-top: 4px; }
.yul-rec-bank input { text-align: right; font-variant-numeric: tabular-nums; }
.yul-rec-match { font-size: 12.5px; display: flex; align-items: center; gap: 6px; min-height: 22px; flex-wrap: wrap; }
.yul-rec-link { cursor: pointer; font-size: 12px; color: var(--text-3); user-select: none; transition: color .15s; }
.yul-rec-link:hover { color: var(--text); }
.yul-rec-gap-link { color: var(--accent-2); cursor: pointer; }
body.body--light .yul-rec-gap-link { color: var(--accent-solid); }
.yul-rec-lockcell { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
.yul-rec-rows { border-top: 1px solid var(--border); padding: 6px 10px; animation: yul-enter .25s var(--ease) both; }
.yul-rec-row {
  display: grid; grid-template-columns: 22px 92px minmax(0, 1fr) 120px 110px; align-items: center;
  gap: 10px; padding: 6px 8px; border-radius: 8px; cursor: pointer; transition: background .15s, opacity .3s;
}
.yul-rec-row:hover { background: var(--surface-2); }
.yul-rec-row > .payee { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.yul-rec-row > .amt { text-align: right; font-variant-numeric: tabular-nums; }
.yul-rec-row > .st { font-size: 11.5px; text-align: right; color: var(--text-3); white-space: nowrap; }
.yul-rec-row.unclear { color: var(--text-3); }
.yul-rec-row.locked { opacity: .45; cursor: default; }
.yul-rec-row.locked:hover { background: none; }
.yul-rec-row.gap {
  background: color-mix(in oklab, var(--warn) 14%, transparent); box-shadow: inset 3px 0 0 var(--warn);
}
.yul-rec-cb {
  width: 16px; height: 16px; border-radius: 5px; border: 1.5px solid var(--text-3);
  display: inline-grid; place-items: center; flex: none; transition: all .15s;
}
.yul-rec-cb.on { background: var(--accent); border-color: transparent; }
.yul-rec-cb.on::after {
  content: ""; width: 8px; height: 5px; border-left: 2px solid #fff; border-bottom: 2px solid #fff;
  transform: rotate(-45deg) translate(1px, -1px);
}
.yul-rec-cb.off { opacity: .35; }
.yul-rec-foot {
  position: sticky; bottom: 12px; margin-top: 16px; display: flex; align-items: center; gap: 14px;
  padding: 12px 16px; border-radius: 14px; border: 1px solid var(--border-2); z-index: 4;
  background: color-mix(in oklab, var(--bg) 70%, transparent); backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px); box-shadow: 0 -10px 30px -20px rgba(0, 0, 0, .6);
}
.yul-rec-stat { display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
.yul-rec-stat > .main { font-weight: 600; }
.yul-rec-foot .yul-prog { max-width: 220px; }
.yul-rec-foot .yul-prog > i { width: 100%; }
@media (max-width: 900px) {
  .yul-rec-ah { grid-template-columns: 1fr 1fr; }
  .yul-rec-row { grid-template-columns: 22px 80px minmax(0, 1fr) 100px; }
  .yul-rec-row > .st { display: none; }
}
"""


def scope_start(last_reconciliation: dt.date | None) -> dt.date | None:
    """Where the "since" scope starts, or None when yul never reconciled this budget."""
    if last_reconciliation is None:
        return None
    return last_reconciliation - dt.timedelta(days=SCOPE_BUFFER_DAYS)


def gap_candidates(transactions: Sequence[StoredTransaction], difference: int) -> set[str]:
    """Ids of the transactions that would explain `difference` (bank minus cleared balance).

    An uncleared transaction the bank already took moves the cleared balance by its amount; a
    cleared one the bank has not seen yet accounts for minus its amount. Single transactions
    first; only when none matches, every pair whose effects add up to the difference.
    """
    if difference == 0:
        return set()
    effects = [
        (t.id, t.amount if t.cleared is TransactionClearedStatus.UNCLEARED else -t.amount)
        for t in transactions
    ]
    if singles := {id_ for id_, effect in effects if effect == difference}:
        return singles

    pairs: set[str] = set()
    seen: dict[int, list[str]] = {}
    for id_, effect in effects:
        for other in seen.get(difference - effect, []):
            pairs.update((id_, other))
        seen.setdefault(effect, []).append(id_)
    return pairs


def short_date(day: dt.date, today: dt.date) -> str:
    """ "30 Oct", with the year when it is not the current one."""
    if day.year == today.year:
        return f"{day.day} {day:%b}"
    return f"{day.day} {day:%b %Y}"


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def transaction_detail(transaction: StoredTransaction, account_name: str) -> TransactionDetail:
    """The SDK object `core.reconcile` patches, rebuilt from the stored row.

    `Client.update_transactions` only sends the id, the account and the cleared status; the
    rest fills the fields the SDK model requires.
    """
    return TransactionDetail(
        id=transaction.id,
        date=transaction.date,
        amount=transaction.amount,
        cleared=transaction.cleared,
        approved=transaction.approved,
        account_id=uuid.UUID(transaction.account_id),
        account_name=account_name,
        deleted=False,
        payee_name=transaction.payee_name,
        memo=transaction.memo,
        import_id=transaction.import_id,
        subtransactions=[],
    )


@dataclass(eq=False)
class Row:
    transaction: StoredTransaction
    selected: bool
    locked: bool = False
    element: ui.element | None = None
    box: ui.element | None = None
    status: ui.label | None = None

    @property
    def uncleared(self) -> bool:
        return self.transaction.cleared is TransactionClearedStatus.UNCLEARED

    @property
    def to_lock(self) -> bool:
        return self.selected and not self.locked


@dataclass(eq=False)
class AccountGroup:
    account: StoredAccount
    rows: list[Row]
    matches: bool | None = None
    """None until a bank balance is typed, then whether it equals the cleared balance."""
    difference: int = 0
    open: bool = False
    count: ui.label | None = None
    lock_button: ui.button | None = None
    lock_label: ui.label | None = None
    done: ui.element | None = None
    match: ui.element | None = None
    rows_box: ui.element | None = None
    toggle: ui.label | None = None
    bank: ui.input | None = None

    def to_lock(self) -> list[Row]:
        return [row for row in self.rows if row.to_lock]

    def pending(self) -> list[Row]:
        return [row for row in self.rows if not row.locked]


@dataclass
class _Data:
    accounts: list[StoredAccount] = field(default_factory=list[StoredAccount])
    unreconciled: list[StoredTransaction] = field(default_factory=list[StoredTransaction])


class ReconcileView:
    def __init__(self, config: LatestConfig, formatter: Formatter) -> None:
        self.budget_id = config.budget.id
        self.currency = config.budget.currency_format
        self.formatter = formatter
        self.since = scope_start(config.last_reconciliation_date)
        self.scope = SINCE if self.since is not None else ALL_TIME
        self.include_uncleared = False
        self.busy = False
        self.data = _Data()
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
        if (data := await run.io_bound(self._read_store)) is not None:
            self.data = data

    def _read_store(self) -> _Data:
        store = state().store
        return _Data(
            accounts=store.accounts(self.budget_id), unreconciled=store.unreconciled(self.budget_id)
        )

    async def ensure_fresh(self) -> bool:
        """Sync the store when it is older than ten minutes or something was written to YNAB
        since (an import, a lock, a balance update). False if it was never synced."""
        current = state()
        if current.fresh(SYNC_MAX_AGE):
            return True
        try:
            await current.sync()
        except Exception as error:
            shell.notify(f"Showing the last sync. {ynab_error_message(error)}", "warn")
        return current.last_sync is not None

    def open_transactions(self) -> list[tuple[StoredAccount, list[StoredTransaction]]]:
        """Unreconciled transactions of open accounts in the current scope, newest first."""
        since = self.since if self.scope == SINCE else None
        per_account: dict[str, list[StoredTransaction]] = {}
        for transaction in reversed(self.data.unreconciled):
            if transaction.id in self.locked_ids:
                continue
            if since is not None and transaction.date < since:
                continue
            per_account.setdefault(transaction.account_id, []).append(transaction)
        return [
            (account, per_account[account.id])
            for account in self.data.accounts
            if not account.closed and account.id in per_account
        ]

    def has_anything(self) -> bool:
        open_ids = {account.id for account in self.data.accounts if not account.closed}
        return any(
            t.account_id in open_ids and t.id not in self.locked_ids for t in self.data.unreconciled
        )

    # ---- page ----------------------------------------------------------------------------

    async def render(self) -> None:
        add_css_once("reconcile", CSS)
        self.root = ui.element("div").mark("reconcile")
        with self.root, ui.element("div").classes("yul-row yul-muted"):
            spinner()
            ui.label("Getting the latest from YNAB…")

        synced = await self.ensure_fresh()
        await self.load()
        if not synced and not self.data.accounts:
            self.root.clear()
            with self.root:
                empty_state(
                    "Could not load your accounts from YNAB yet.",
                    icon_name="refresh",
                    action_label="Try again",
                    on_action=lambda: ui.navigate.to("/reconcile"),
                )
            return
        self.build()

    def build(self) -> None:
        """Header, account cards and footer for the current scope, or the empty state."""
        assert self.root is not None
        self.root.clear()
        with self.root:
            if not self.has_anything():
                self.all_reconciled()
                return
            self.header()
            self.list = ui.element("div")
            self.footer = ui.element("div").classes("yul-rec-foot").mark("rec-footer")
        self.render_list()

    def all_reconciled(self) -> None:
        empty_state(
            "All accounts are reconciled",
            icon_name="reconcile",
            action_label="See net worth",
            on_action=lambda: ui.navigate.to(NETWORTH_PATH),
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
                    group.lock_button = button(on_click=lambda group=group: self.lock([group]))
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
        typed: int | None = None
        if text.strip():
            try:
                typed = parse_amount_to_milliunits(
                    text,
                    decimal_separator=self.currency.decimal_separator,
                    group_separator=self.currency.group_separator,
                )
            except ValueError:
                typed = None
            if typed is None:
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
            if row.transaction.id in ids:
                row.element.classes(add="gap")
            else:
                row.element.classes(remove="gap")

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
        for name, on in (
            ("on", row.selected or row.locked),
            ("off", not selectable and not row.locked),
        ):
            if on:
                row.box.classes(add=name)
            else:
                row.box.classes(remove=name)
        if row.uncleared and not row.locked:
            row.element.classes(add="unclear")
        else:
            row.element.classes(remove="unclear")
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
            if pending_rows:
                self.title.set_text(
                    f"{plural(pending_accounts, 'account')} · "
                    f"{plural(pending_rows, 'transaction')} not reconciled"
                )
            elif self.groups:
                self.title.set_text("Everything here is reconciled")
            else:
                self.title.set_text("Nothing to reconcile in this range")

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
            if group.matches:
                group.lock_button.classes(add="primary")
            else:
                group.lock_button.classes(remove="primary")
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
                self.done_footer(count)
                return
            with ui.element("div").classes("yul-grow yul-rec-stat"):
                ui.label(
                    f"Lock {plural(count, 'transaction')} in {plural(accounts, 'account')}"
                ).classes("main").mark("rec-summary")
                if skipped:
                    ui.label("uncleared stay untouched").classes("yul-muted")
            if count:
                button("Deselect all", kind="ghost", on_click=lambda: self.set_all(False)).mark(
                    "deselect-all"
                )
            else:
                button("Select all", kind="ghost", on_click=lambda: self.set_all(True)).mark(
                    "select-all"
                )
            lock_all = button("Lock all", kind="primary", on_click=lambda: self.lock(self.groups))
            lock_all.mark("lock-all")
            lock_all.set_enabled(count > 0)

    def done_footer(self, remaining: int) -> None:
        check()
        with ui.element("div").classes("yul-grow yul-rec-stat"):
            ui.label(f"{plural(self.last_locked, 'transaction')} locked").classes("main").mark(
                "rec-done"
            )
            ui.label("logged in activity").classes("yul-muted")
        if remaining:
            button(f"Lock {remaining} more", on_click=lambda: self.lock(self.groups)).mark(
                "lock-more"
            )
        button(
            "See net worth", kind="primary", on_click=lambda: ui.navigate.to(NETWORTH_PATH)
        ).mark("see-networth")

    def progress_footer(self, count: int) -> None:
        assert self.footer is not None
        self.footer.clear()
        with self.footer:
            spinner()
            ui.label(f"Locking {plural(count, 'transaction')} in YNAB…").classes("yul-grow")
            with ui.element("div").classes("yul-prog active"):
                ui.element("i")

    # ---- lock ----------------------------------------------------------------------------

    async def lock(self, groups: Sequence[AccountGroup]) -> None:
        if self.busy:
            return
        batches = [(group, rows) for group in groups if (rows := group.to_lock())]
        if not batches:
            return
        count = sum(len(rows) for _, rows in batches)
        lines = [
            f"{group.account.name} · {plural(len(rows), 'transaction')}" for group, rows in batches
        ]
        if uncleared := sum(row.uncleared for _, rows in batches for row in rows):
            lines.append(f"{uncleared} of them {'is' if uncleared == 1 else 'are'} still uncleared")
        confirmed = await shell.confirm(
            f"Lock {plural(count, 'transaction')} in {plural(len(batches), 'account')}?",
            [*lines, "They are marked reconciled in YNAB."],
            f"Lock {count}",
        )
        if not confirmed:
            return

        self.busy = True
        self.refresh()
        self.progress_footer(count)
        details = [
            transaction_detail(row.transaction, group.account.name)
            for group, rows in batches
            for row in rows
        ]
        try:
            config, client = state().require()
            latest = await run.io_bound(reconcile, client, config.budget.id, details)
        except Exception as error:
            self.busy = False
            shell.notify(f"Nothing was locked. {ynab_error_message(error)}", "error")
            self.refresh()
            return

        if latest is not None:
            next_date = next_reconciliation_date(latest)

            def change(config: LatestConfig) -> None:
                config.last_reconciliation_date = next_date

            state().update_config(change)
        state().store.log(
            config.budget.id,
            kind="reconcile",
            message=(
                f"Reconciled {plural(count, 'transaction')} in {plural(len(batches), 'account')}"
            ),
            details={
                "count": count,
                "accounts": [
                    {"id": group.account.id, "name": group.account.name, "count": len(rows)}
                    for group, rows in batches
                ],
            },
        )
        state().invalidate()

        for _, rows in batches:
            for row in rows:
                row.locked = True
                row.selected = False
                self.locked_ids.add(row.transaction.id)
                self.paint_row(row)
        self.busy = False
        self.last_locked = count
        self.refresh()
        shell.notify(f"{plural(count, 'transaction')} locked in YNAB")


@shell.view(
    "/reconcile",
    key="reconcile",
    title="Reconcile",
    subtitle="Lock what the bank confirmed",
    icon="reconcile",
    order=30,
)
async def reconcile_view() -> None:
    config, _ = state().require()
    formatter = state().formatter
    assert formatter is not None
    await ReconcileView(config, formatter).render()

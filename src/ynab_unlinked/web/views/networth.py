"""Net worth: the history chart, the four buckets, and the accounts with balance updates.

Everything is read from the local store and the config. Every open account counts unless
Settings leaves it out (`web.accounts.effective_accounts`). Every account row has a pencil
(always shown on "by hand" ones, `track_balance`) that turns its balance into an inline input
with a check and a cross; the check creates the one adjustment that takes the account to that
balance, which is the only write to YNAB. The view re-renders itself whenever a sync lands,
keeping an open editor and what was typed in it.
"""

from __future__ import annotations

import asyncio
import calendar
import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from nicegui import run, ui
from ynab import TransactionClearedStatus

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import LatestConfig, TrackedAccount
from ynab_unlinked.core.balances import (
    AccountBalance,
    Adjustment,
    DebtNetting,
    NetWorth,
    build_adjustments,
    create_adjustments,
    net_worth,
    parse_amount_to_milliunits,
)
from ynab_unlinked.core.history import TOTAL, Point, balance_series, net_worth_series
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.store import Store, StoredAccount, StoredTransaction
from ynab_unlinked.web import accounts as tracking
from ynab_unlinked.web import shell, theme
from ynab_unlinked.web.components import (
    PillKind,
    Segment,
    button,
    count_up,
    empty_state,
    glass_card,
    pill,
    segmented_bar,
    share_bar,
    stat_tile,
)
from ynab_unlinked.web.components.history_chart import (
    ChartSeries,
    history_chart,
    history_options,
    set_options,
)
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.onboarding import ynab_error_message

RANGES = ("1M", "3M", "6M", "YTD", "1Y", "All")
DEFAULT_RANGE = "6M"
GROUPINGS = {"total": "Total", "type": "By type", "account": "By account"}
MAX_PICKED = 6
DEFAULT_PICKED = 4
"""How many accounts "by account" shows before the user picks: the largest after netting."""
STALE_AFTER_DAYS = 30
DRAWER_TRANSACTIONS = 20

# Bucket, group title, CSS colour. Series colours by entity: the three positive buckets own
# series 1..3 everywhere in the view; debt has no series colour.
GROUPS: tuple[tuple[Bucket, str, str | None], ...] = (
    (Bucket.ASSETS, "Assets", "var(--series-1)"),
    (Bucket.SAVINGS, "Savings", "var(--series-2)"),
    (Bucket.CASH, "Cash · after debt", "var(--series-3)"),
    (Bucket.DEBT, "Debt", None),
)
_TYPE_SERIES = ((Bucket.ASSETS, "Assets"), (Bucket.SAVINGS, "Savings"), (Bucket.CASH, "Cash"))
_SERIES_SLOT = {Bucket.ASSETS: 0, Bucket.SAVINGS: 1, Bucket.CASH: 2}


# ---- pure helpers --------------------------------------------------------------------------


def _months_back(day: dt.date, months: int) -> dt.date:
    month_index = day.year * 12 + day.month - 1 - months
    year, month = divmod(month_index, 12)
    month += 1
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def range_start(key: str, today: dt.date, earliest: dt.date) -> dt.date:
    """First day of a range pill. Never before the first transaction, never after today."""
    match key:
        case "1M":
            start = _months_back(today, 1)
        case "3M":
            start = _months_back(today, 3)
        case "6M":
            start = _months_back(today, 6)
        case "YTD":
            start = dt.date(today.year, 1, 1)
        case "1Y":
            start = _months_back(today, 12)
        case _:
            start = earliest
    return min(max(start, earliest), today)


def last_set(transactions: Sequence[StoredTransaction], payee: str) -> dt.date | None:
    """When a by hand balance was last set: the latest adjustment, else the latest transaction."""
    if not transactions:
        return None
    adjustments = [t.date for t in transactions if t.payee_name == payee]
    return max(adjustments) if adjustments else max(t.date for t in transactions)


def age_text(days: int) -> str:
    if days <= 0:
        return "today"
    return "1 day ago" if days == 1 else f"{days} days ago"


def by_hand_pill(last: dt.date | None, today: dt.date) -> tuple[str, PillKind]:
    """ "by hand · 9 days ago", or "stale · 41 days ago" once older than 30 days."""
    if last is None:
        return "stale · never set", "warn"
    days = (today - last).days
    if days > STALE_AFTER_DAYS:
        return f"stale · {age_text(days)}", "warn"
    return f"by hand · {age_text(days)}", "acc"


def assign_slots(previous: dict[str, int], picked: Sequence[str]) -> dict[str, int]:
    """Colour slot of each picked account: kept while it stays picked, else the first free."""
    slots = {account_id: slot for account_id, slot in previous.items() if account_id in picked}
    for account_id in picked:
        if account_id not in slots:
            slots[account_id] = min(set(range(MAX_PICKED)) - set(slots.values()))
    return slots


def signed(formatter: Formatter, milliunits: int) -> str:
    text = formatter.format_amount_milli(milliunits)
    return f"+{text}" if milliunits > 0 else text


def short_date(day: dt.date, today: dt.date) -> str:
    return f"{day.day} {day:%b}" if day.year == today.year else f"{day.day} {day:%b %Y}"


# ---- data ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    """What the view shows, read from the store in one go."""

    tracked: tuple[TrackedAccount, ...]
    stored: dict[str, StoredAccount]
    nettings: tuple[DebtNetting, ...]
    worth: NetWorth
    earliest: dt.date
    last_set: dict[str, dt.date | None]
    """By hand accounts only."""

    def raw(self, account_id: str) -> int:
        stored = self.stored.get(account_id)
        return 0 if stored is None else stored.balance

    def name(self, account: TrackedAccount) -> str:
        stored = self.stored.get(account.id)
        return account.name if stored is None else stored.name

    def netted(self, account_id: str) -> int:
        return next(a.balance for a in self.worth.accounts if a.id == account_id)

    def mapped(self, debt_account_id: str) -> tuple[str, ...]:
        tracked = {a.id for a in self.tracked if a.bucket is not Bucket.DEBT}
        targets = next(
            (n.mapped_to for n in self.nettings if n.debt_account_id == debt_account_id), ()
        )
        return tuple(target for target in targets if target in tracked)


def load_snapshot(store: Store, config: LatestConfig, today: dt.date) -> Snapshot:
    budget_id = config.budget.id
    stored = {account.id: account for account in store.accounts(budget_id)}
    tracked = tuple(tracking.effective_accounts(config, stored.values()))
    nettings = tracking.effective_nettings(config)
    worth = net_worth(
        [
            AccountBalance(
                id=a.id,
                name=a.name,
                bucket=a.bucket,
                balance=stored[a.id].balance if a.id in stored else 0,
            )
            for a in tracked
        ],
        nettings,
    )
    amounts = store.daily_amounts(budget_id, [a.id for a in tracked]) if tracked else {}
    earliest = min((a.days[0][0] for a in amounts.values() if a.days), default=today)
    by_hand = {
        a.id: last_set(store.transactions(budget_id, account_id=a.id), config.adjustments.payee)
        for a in tracked
        if a.track_balance
    }
    return Snapshot(
        tracked=tracked,
        stored=stored,
        nettings=nettings,
        worth=worth,
        earliest=min(earliest, today),
        last_set=by_hand,
    )


def table_order(snapshot: Snapshot) -> list[TrackedAccount]:
    """The counted accounts as the Accounts table lists them: by bucket, largest first."""
    ordered: list[TrackedAccount] = []
    for bucket, _, _ in GROUPS:
        accounts = [a for a in snapshot.tracked if a.bucket is bucket]
        if bucket is Bucket.DEBT:
            accounts.sort(key=lambda a: snapshot.raw(a.id))
        else:
            accounts.sort(key=lambda a: snapshot.netted(a.id), reverse=True)
        ordered += accounts
    return ordered


# ---- the view ------------------------------------------------------------------------------


class NetWorthView:
    def __init__(self) -> None:
        self.range = DEFAULT_RANGE
        self.grouping = "total"
        self.picked: list[str] | None = None
        self.slots: dict[str, int] = {}
        self.editing: str | None = None
        """The account whose balance is open for editing; one at a time."""
        self.draft = ""
        """What is typed in the open editor, kept across re-renders."""
        self.hint = ""
        self.hint_label: ui.label | None = None
        self.busy = False
        self.snapshot: Snapshot | None = None
        self.history: dict[str, list[Point]] = {}
        self.dark = theme.is_dark()
        self.animated = False
        self.lock = asyncio.Lock()
        self.sync_key = self._sync_key()

        with ui.element("div").classes("yul-nw") as self.root:
            self.body = ui.element("div")
        self.chart: ui.echart | None = None
        self.delta: ui.element | None = None
        self.picker: ui.element | None = None
        self.chips: ui.element | None = None
        self.pills: dict[str, ui.element] = {}
        self.rows: dict[str, tuple[ui.element, Callable[[], None]]] = {}
        self.drawer: tuple[ui.echart, list[ChartSeries]] | None = None

    # ---- context ---------------------------------------------------------------------------

    @staticmethod
    def _sync_key() -> tuple[object, ...]:
        current = state()
        return (current.last_sync, current.syncing, current.sync_error)

    @property
    def palette(self) -> theme.Palette:
        return theme.DARK_PALETTE if self.dark else theme.LIGHT_PALETTE

    @staticmethod
    def _formatter() -> Formatter:
        formatter = state().formatter
        assert formatter is not None
        return formatter

    def _start(self) -> dt.date:
        assert self.snapshot is not None
        return range_start(self.range, dt.date.today(), self.snapshot.earliest)

    def _parse(self, text: str) -> int | None:
        config, _ = state().require()
        currency = config.budget.currency_format
        try:
            return parse_amount_to_milliunits(
                text,
                decimal_separator=currency.decimal_separator,
                group_separator=currency.group_separator,
            )
        except ValueError:
            return parse_amount_to_milliunits(text)

    # ---- lifecycle -------------------------------------------------------------------------

    async def render(self) -> None:
        with self.root:
            ui.timer(1.0, self.tick)
        await self.refresh()

    async def tick(self) -> None:
        """Re-render when a sync lands; restyle the charts when the theme changes."""
        key = self._sync_key()
        if key != self.sync_key:
            self.sync_key = key
            if not state().syncing:
                await self.refresh()
                return
        try:
            dark = theme.is_dark()
        except RuntimeError:  # no browser session in this context
            return
        if dark != self.dark:
            self.dark = dark
            self.restyle()

    async def _load_history(self, snapshot: Snapshot) -> dict[str, list[Point]] | None:
        config, _ = state().require()
        today = dt.date.today()
        return await run.io_bound(
            net_worth_series,
            state().store,
            config.budget.id,
            snapshot.tracked,
            snapshot.nettings,
            range_start(self.range, today, snapshot.earliest),
            today,
        )

    async def refresh(self) -> None:
        async with self.lock:
            config, _ = state().require()
            snapshot = await run.io_bound(load_snapshot, state().store, config, dt.date.today())
            if snapshot is None or self.root.is_deleted:  # the app is shutting down
                return
            self.snapshot = snapshot
            if snapshot.stored and snapshot.tracked:
                history = await self._load_history(snapshot)
                if history is None or self.root.is_deleted:
                    return
                self.history = history
            if self.picked is None and snapshot.tracked:
                self.picked = self._default_picked(snapshot)
            if self.picked is not None:
                ids = {a.id for a in snapshot.tracked}
                self.picked = [account_id for account_id in self.picked if account_id in ids]
                self.slots = assign_slots(self.slots, self.picked)

            if self.editing is not None and all(a.id != self.editing for a in snapshot.tracked):
                self.editing = None
            self.body.clear()
            self.rows = {}
            with self.body:
                if not snapshot.stored:
                    self._first_sync()
                elif not snapshot.tracked:
                    empty_state(
                        "Every account is left out of net worth. Count some in Settings.",
                        icon_name="networth",
                        action_label="Open Settings",
                        on_action=lambda: ui.navigate.to("/settings?tab=accounts"),
                    ).mark("no-tracked")
                else:
                    self._hero(snapshot)
                    self._buckets(snapshot)
                    self._accounts(snapshot)

    @staticmethod
    def _default_picked(snapshot: Snapshot) -> list[str]:
        positive = [a for a in snapshot.worth.accounts if a.bucket is not Bucket.DEBT]
        positive.sort(key=lambda a: a.balance, reverse=True)
        return [a.id for a in positive[:DEFAULT_PICKED]]

    def _first_sync(self) -> None:
        current = state()
        if current.sync_error and not current.syncing:
            empty_state(
                f"The first sync with YNAB failed: {current.sync_error}",
                icon_name="refresh",
                action_label="Try again",
                on_action=current.sync_in_background,
            ).mark("first-sync-failed")
            return
        empty_state("First sync running…", icon_name="refresh").mark("first-sync")
        current.sync_in_background()

    # ---- hero ------------------------------------------------------------------------------

    def _hero(self, snapshot: Snapshot) -> None:
        config, _ = state().require()
        formatter = self._formatter()
        with glass_card().classes("yul-nw-hero"):
            with ui.element("div").classes("yul-nw-head"):
                with ui.element("div"):
                    ui.label("Net worth").classes("yul-muted yul-small")
                    figure = ui.label(formatter.format_amount_milli(snapshot.worth.total))
                    figure.classes("yul-grad yul-nw-figure").mark("nw-figure")
                self.delta = ui.element("div").classes("yul-nw-delta").mark("nw-delta")
                ui.element("span").classes("yul-grow")
                with ui.element("div").classes("yul-pills").mark("ranges"):
                    self.pills = {}
                    for key in RANGES:
                        item = ui.label(key).mark(f"range-{key}")
                        item.props["role"] = "button"
                        item.props["tabindex"] = "0"
                        item.on("click", lambda _, key=key: self.set_range(key))
                        item.on("keydown.enter", lambda _, key=key: self.set_range(key))
                        self.pills[key] = item
                ui.select(
                    GROUPINGS, value=self.grouping, on_change=lambda e: self.set_grouping(e.value)
                ).props("outlined dense options-dense").classes("yul-nw-select").mark("grouping")

            with ui.element("div").classes("yul-nw-picker").mark("account-picker") as picker:
                self.picker = picker
                self.chips = ui.element("div")
            self._render_chips()
            self.chart = (
                history_chart(self._series(), self.palette, config.budget.currency_format)
                .classes("yul-nw-chart")
                .mark("nw-chart")
            )

        if not self.animated:
            self.animated = True
            count_up(figure, snapshot.worth.total, config.budget.currency_format)
        self._sync_controls()

    def _sync_controls(self) -> None:
        for key, item in self.pills.items():
            if key == self.range:
                item.classes(add="on")
            else:
                item.classes(remove="on")
        if self.picker is not None:
            self.picker.set_visibility(self.grouping == "account")
        self._show_delta()

    def _show_delta(self) -> None:
        if self.delta is None:
            return
        self.delta.clear()
        points = self.history.get(TOTAL, [])
        if not points:
            return
        change = points[-1].value - points[0].value
        formatter = self._formatter()
        since = short_date(points[0].date, dt.date.today())
        with self.delta:
            if change == 0:
                ui.label(f"no change since {since}").classes("yul-faint")
                return
            arrow = "▲" if change > 0 else "▼"
            ui.label(f"{arrow} {formatter.format_amount_milli(abs(change))}").classes(
                "yul-good" if change > 0 else "yul-bad"
            )
            ui.label(f"since {since}").classes("yul-faint")

    def _series(self) -> list[ChartSeries]:
        assert self.snapshot is not None
        palette = self.palette
        if self.grouping == "type":
            return [
                ChartSeries(name, self.history.get(bucket.value, []), palette.series[slot])
                for slot, (bucket, name) in enumerate(_TYPE_SERIES)
            ]
        if self.grouping == "account":
            names = {a.id: self.snapshot.name(a) for a in self.snapshot.tracked}
            picked = sorted(
                (account_id for account_id in self.picked or [] if account_id in names),
                key=lambda account_id: self.slots[account_id],
            )
            return [
                ChartSeries(
                    names[account_id],
                    self.history.get(account_id, []),
                    palette.series[self.slots[account_id]],
                )
                for account_id in picked
            ]
        return [ChartSeries("Net worth", self.history.get(TOTAL, []), palette.accent[0])]

    def _redraw(self) -> None:
        if self.chart is None or self.chart.is_deleted:
            return
        config, _ = state().require()
        set_options(
            self.chart,
            history_options(self._series(), self.palette, config.budget.currency_format),
        )

    def restyle(self) -> None:
        self._redraw()
        if self.drawer is not None:
            chart, series = self.drawer
            if not chart.is_deleted:
                config, _ = state().require()
                set_options(
                    chart, history_options(series, self.palette, config.budget.currency_format)
                )

    async def set_range(self, key: str) -> None:
        if self.snapshot is None or not self.snapshot.tracked:
            return
        self.range = key
        async with self.lock:
            history = await self._load_history(self.snapshot)
            if history is None or self.root.is_deleted:
                return
            self.history = history
            self._sync_controls()
            self._redraw()

    def set_grouping(self, grouping: str) -> None:
        self.grouping = grouping
        self._sync_controls()
        self._redraw()

    def set_picked(self, picked: list[str]) -> None:
        picked = picked[:MAX_PICKED]
        self.picked = picked
        self.slots = assign_slots(self.slots, picked)
        self._render_chips()
        self._redraw()

    def toggle_pick(self, account_id: str) -> None:
        picked = list(self.picked or [])
        if account_id in picked:
            picked.remove(account_id)
        elif len(picked) >= MAX_PICKED:
            return
        else:
            picked.append(account_id)
        self.set_picked(picked)

    def _render_chips(self) -> None:
        """One chip per counted account, in table order; the picked ones carry their colour."""
        if self.chips is None or self.chips.is_deleted or self.snapshot is None:
            return
        snapshot = self.snapshot
        picked = self.picked or []
        full = len(picked) >= MAX_PICKED
        self.chips.clear()
        with self.chips:
            ui.label(f"Accounts · {len(picked)} of {MAX_PICKED}").classes(
                "yul-faint yul-small"
            ).mark("pick-count")
            with ui.element("div").classes("yul-chips"):
                for account in table_order(snapshot):
                    chip = ui.element("div").classes("yul-chipc").mark(f"pick-{account.id}")
                    chip.props["role"] = "button"
                    chip.props["tabindex"] = "0"
                    on = account.id in picked
                    chip.props["aria-pressed"] = "true" if on else "false"
                    if on:
                        chip.classes("on")
                    elif full:
                        chip.classes("off")
                        chip.props["title"] = "Remove one to add another"
                        chip.props["aria-disabled"] = "true"
                    with chip:
                        if on:
                            slot = self.slots[account.id] + 1
                            ui.element("span").classes("yul-swatch").style(
                                f"background:var(--series-{slot})"
                            )
                        ui.label(snapshot.name(account))
                    chip.on("click", lambda _, account_id=account.id: self.toggle_pick(account_id))
                    chip.on(
                        "keydown.enter",
                        lambda _, account_id=account.id: self.toggle_pick(account_id),
                    )

    # ---- buckets ---------------------------------------------------------------------------

    def _buckets(self, snapshot: Snapshot) -> None:
        formatter = self._formatter()
        totals = snapshot.worth.by_bucket()
        total = snapshot.worth.total

        def share(bucket: Bucket) -> str:
            return f"{totals[bucket] / total * 100:.1f}%" if total > 0 else "—"

        targets = {
            target
            for account in snapshot.tracked
            if account.bucket is Bucket.DEBT
            for target in snapshot.mapped(account.id)
        }
        buckets = {a.id: a.bucket for a in snapshot.tracked}
        kind = "cash " if all(buckets[t] is Bucket.CASH for t in targets) else ""
        plural = "" if len(targets) == 1 else "s"
        debt_hint = f"netted into {len(targets)} {kind}account{plural}" if targets else "not netted"

        with ui.element("div").classes("yul-nw-tiles yul-stagger"):
            stat_tile(
                "Assets",
                formatter.format_amount_milli(totals[Bucket.ASSETS]),
                hint=f"{share(Bucket.ASSETS)} of net worth",
                swatch="var(--series-1)",
            ).mark("tile-assets")
            stat_tile(
                "Savings",
                formatter.format_amount_milli(totals[Bucket.SAVINGS]),
                hint=share(Bucket.SAVINGS),
                swatch="var(--series-2)",
            ).mark("tile-savings")
            stat_tile(
                "Cash",
                formatter.format_amount_milli(totals[Bucket.CASH]),
                hint=f"{share(Bucket.CASH)} · after debt",
                swatch="var(--series-3)",
            ).mark("tile-cash")
            stat_tile(
                "Debt", formatter.format_amount_milli(totals[Bucket.DEBT]), hint=debt_hint
            ).mark("tile-debt")
        segmented_bar(
            [
                Segment("Assets", totals[Bucket.ASSETS], "var(--series-1)"),
                Segment("Savings", totals[Bucket.SAVINGS], "var(--series-2)"),
                Segment("Cash", totals[Bucket.CASH], "var(--series-3)"),
            ]
        ).mark("composition")

    # ---- accounts --------------------------------------------------------------------------

    def _accounts(self, snapshot: Snapshot) -> None:
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

            for bucket, title, color in GROUPS:
                accounts = [a for a in ordered if a.bucket is bucket]
                if not accounts:
                    continue
                with ui.element("div").classes("yul-section").mark(f"group-{bucket.value}"):
                    if color:
                        ui.element("span").classes("yul-swatch").style(f"background:{color}")
                    ui.label(title)
                with ui.element("div").classes("yul-stagger"):
                    for account in accounts:
                        self._account_row(snapshot, account, color, shares, widest)

    def _account_row(
        self,
        snapshot: Snapshot,
        account: TrackedAccount,
        color: str | None,
        shares: dict[str, float],
        widest: float,
    ) -> None:
        formatter = self._formatter()
        debt = account.bucket is Bucket.DEBT
        balance = snapshot.raw(account.id) if debt else snapshot.netted(account.id)
        row = ui.element("div").classes("yul-nw-arow").mark(f"row-{account.id}")

        def fill() -> None:
            editing = self.editing == account.id
            row.clear()
            if editing:
                row.classes(add="editing")
            else:
                row.classes(remove="editing")
            with row:
                with ui.element("div").classes("yul-nw-name-cell"):
                    name = ui.label(snapshot.name(account)).classes("yul-nw-name")
                    name.mark(f"name-{account.id}")
                    name.props["role"] = "button"
                    name.props["tabindex"] = "0"
                    name.on("click", lambda: self.open_drawer(account.id))
                    name.on("keydown.enter", lambda: self.open_drawer(account.id))
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
                        share_bar(fraction / widest if widest > 0 else 0, color or "var(--text-3)")
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
        self.draft = self._formatter().format_amount_milli(self.snapshot.raw(account_id))
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
        wanted = self._parse(self.draft)
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

        config, client = state().require()
        formatter = self._formatter()
        account = next(a for a in snapshot.tracked if a.id == account_id)
        name = snapshot.name(account)
        settings = config.adjustments
        budget_id = config.budget.id

        def write() -> list[Adjustment]:
            # The budget copy may lag behind YNAB (the phone app, `yul load`), so the
            # adjustment starts from the balance YNAB has right now
            live = client.account(budget_id, account_id).balance
            adjustments = build_adjustments({account_id: live}, {account_id: wanted})
            if adjustments:
                create_adjustments(
                    client,
                    budget_id,
                    adjustments,
                    settings.memo,
                    settings.payee,
                    TransactionClearedStatus(settings.cleared.value),
                    dt.date.today(),
                )
            return adjustments

        self.busy = True
        try:
            adjustments = await run.io_bound(write)
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

    # ---- account drawer --------------------------------------------------------------------

    async def open_drawer(self, account_id: str) -> None:
        snapshot = self.snapshot
        if snapshot is None:
            return
        account = next((a for a in snapshot.tracked if a.id == account_id), None)
        if account is None:
            return
        config, _ = state().require()
        store = state().store
        formatter = self._formatter()
        start, today = self._start(), dt.date.today()
        loaded = await run.io_bound(
            lambda: (
                balance_series(store, config.budget.id, account_id, start, today),
                store.transactions(config.budget.id, account_id=account_id),
            )
        )
        if loaded is None or self.root.is_deleted:
            return
        points, transactions = loaded
        transactions = transactions[-DRAWER_TRANSACTIONS:][::-1]
        name = snapshot.name(account)
        slot = _SERIES_SLOT.get(account.bucket)
        color = self.palette.accent[0] if slot is None else self.palette.series[slot]
        series = [ChartSeries(name, points, color)]

        with (
            self.root,
            ui.dialog().props("position=right full-height") as dialog,
            ui.element("div").classes("yul-card yul-nw-drawer").mark("nw-drawer"),
        ):
            with ui.element("div").classes("yul-row"):
                with ui.element("div").classes("yul-grow"):
                    ui.label(name).classes("yul-h2")
                    ui.label(f"{account.bucket.value.capitalize()} · balance in YNAB").classes(
                        "yul-faint yul-small"
                    )
                close = button(icon_name="x", kind="ghost", on_click=dialog.close)
                close.props["title"] = "Close"
            ui.label(formatter.format_amount_milli(snapshot.raw(account_id))).classes(
                "yul-nw-drawer-figure yul-num"
            )
            ui.label(f"Since {short_date(start, today)}").classes("yul-faint yul-small")
            chart = (
                history_chart(series, self.palette, config.budget.currency_format, height=220)
                .classes("yul-nw-chart")
                .mark("drawer-chart")
            )
            self.drawer = (chart, series)
            ui.label("Last transactions").classes("yul-section")
            if not transactions:
                ui.label("No transactions in the local copy yet.").classes("yul-faint")
            with ui.element("div").classes("yul-nw-tx-list"):
                for transaction in transactions:
                    self._transaction_row(formatter, transaction)
        dialog.on_value_change(lambda e: None if e.value else dialog.delete())
        dialog.open()

    @staticmethod
    def _transaction_row(formatter: Formatter, transaction: StoredTransaction) -> None:
        with ui.element("div").classes("yul-nw-tx").mark("drawer-tx"):
            ui.label(f"{transaction.date.day} {transaction.date:%b %y}").classes(
                "yul-faint yul-num"
            )
            with ui.element("div").classes("yul-grow"):
                ui.label(transaction.payee_name or "—")
                if transaction.memo:
                    ui.label(transaction.memo).classes("yul-faint yul-small yul-nw-memo")
            amount = ui.label(formatter.format_amount_milli(transaction.amount))
            amount.classes("yul-num yul-nw-tx-amount")


@shell.view(
    "/networth",
    key="networth",
    title="Net worth",
    subtitle="All your accounts in one figure",
    icon="networth",
    order=40,
)
async def networth_view() -> None:
    await NetWorthView().render()


__all__ = [
    "NetWorthView",
    "Snapshot",
    "assign_slots",
    "by_hand_pill",
    "last_set",
    "load_snapshot",
    "range_start",
]

"""The Net worth view: the hero with the history chart, the four buckets, the accounts table.

Everything is read from the local store and the config (`data.load_snapshot`). Every open
account counts unless Settings leaves it out (`web.accounts.effective_accounts`). The view
re-renders itself whenever a sync lands, keeping an open balance editor (`table`) and what was
typed in it, and restyles its charts when the theme changes.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from functools import partial

from nicegui import run, ui

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.core.history import TOTAL, Point, balance_series, net_worth_series
from ynab_unlinked.web import shell, theme
from ynab_unlinked.web.buckets import NET_WORTH_ORDER, SERIES_BUCKETS, STYLES
from ynab_unlinked.web.components import (
    Segment,
    clickable,
    count_up,
    empty_state,
    glass_card,
    segmented_bar,
    stat_tile,
)
from ynab_unlinked.web.components.controls import pill_group
from ynab_unlinked.web.components.history_chart import (
    ChartSeries,
    history_chart,
    history_options,
    set_options,
)
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.networth import data
from ynab_unlinked.web.views.networth.data import (
    DEFAULT_RANGE,
    DRAWER_TRANSACTIONS,
    GROUPINGS,
    RANGES,
    Snapshot,
    assign_slots,
    default_picked,
    load_snapshot,
    range_start,
    table_order,
)
from ynab_unlinked.web.views.networth.drawer import account_drawer
from ynab_unlinked.web.views.networth.table import AccountsTable
from ynab_unlinked.web.wording import plural, short_date


class NetWorthView:
    def __init__(self) -> None:
        self.range = DEFAULT_RANGE
        self.grouping = "total"
        self.picked: list[str] | None = None
        self.slots: dict[str, int] = {}
        self.snapshot: Snapshot | None = None
        self.history: dict[str, list[Point]] = {}
        self.look = self._look()
        self.animated = False
        self.lock = asyncio.Lock()
        self.sync_key = self._sync_key()

        with ui.element("div").classes("yul-nw") as self.root:
            self.body = ui.element("div")
        self.table = AccountsTable(self.root, self.refresh, self.open_drawer)
        self.chart: ui.echart | None = None
        self.delta: ui.element | None = None
        self.picker: ui.element | None = None
        self.chips: ui.element | None = None
        self.drawer: tuple[ui.echart, list[ChartSeries]] | None = None

    # ---- context ---------------------------------------------------------------------------

    @staticmethod
    def _sync_key() -> tuple[object, ...]:
        current = state()
        return (current.last_sync, current.syncing, current.sync_error)

    @staticmethod
    def _look() -> tuple[theme.Theme, bool]:
        """The browser's palette and whether it is dark: the charts are drawn in them."""
        return theme.current_theme(), theme.is_dark()

    @property
    def palette(self) -> theme.Palette:
        return theme.palette_for(*self.look)

    def _start(self) -> dt.date:
        assert self.snapshot is not None
        return range_start(self.range, dt.date.today(), self.snapshot.earliest)

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
            look = self._look()
        except RuntimeError:  # no browser session in this context
            return
        if look != self.look:
            self.look = look
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
                self.picked = default_picked(snapshot)
            if self.picked is not None:
                ids = {a.id for a in snapshot.tracked}
                self.picked = [account_id for account_id in self.picked if account_id in ids]
                self.slots = assign_slots(self.slots, self.picked)

            self.table.reset(snapshot)
            self.body.clear()
            with self.body:
                if not snapshot.stored:
                    self._first_sync()
                elif not snapshot.tracked:
                    empty_state(
                        "Every account is left out of net worth. Count some in Settings.",
                        icon_name="networth",
                        action_label="Open Settings",
                        on_action=lambda: ui.navigate.to(f"{shell.SETTINGS_PATH}?tab=accounts"),
                    ).mark("no-tracked")
                else:
                    self._hero(snapshot)
                    self._buckets(snapshot)
                    self.table.draw(snapshot)

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
        formatter = state().require_formatter()
        with glass_card().classes("yul-nw-hero"):
            with ui.element("div").classes("yul-nw-head"):
                with ui.element("div"):
                    ui.label("Net worth").classes("yul-muted yul-small")
                    figure = ui.label(formatter.format_amount_milli(snapshot.worth.total))
                    figure.classes("yul-grad yul-nw-figure").mark("nw-figure")
                self.delta = ui.element("div").classes("yul-nw-delta").mark("nw-delta")
                ui.element("span").classes("yul-grow")
                pill_group(
                    {key: key for key in RANGES}, self.range, self.set_range, marker="range"
                ).mark("ranges")
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
        formatter = state().require_formatter()
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
                ChartSeries(
                    STYLES[bucket].title,
                    self.history.get(bucket.value, []),
                    palette.series[STYLES[bucket].slot or 0],
                )
                for bucket in SERIES_BUCKETS
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

    # ---- the "by account" chips ------------------------------------------------------------

    def set_picked(self, picked: list[str]) -> None:
        picked = picked[: data.MAX_PICKED]
        self.picked = picked
        self.slots = assign_slots(self.slots, picked)
        self._render_chips()
        self._redraw()

    def toggle_pick(self, account_id: str) -> None:
        picked = list(self.picked or [])
        if account_id in picked:
            picked.remove(account_id)
        elif len(picked) >= data.MAX_PICKED:
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
        full = len(picked) >= data.MAX_PICKED
        self.chips.clear()
        with self.chips:
            ui.label(f"Accounts · {len(picked)} of {data.MAX_PICKED}").classes(
                "yul-faint yul-small"
            ).mark("pick-count")
            with ui.element("div").classes("yul-chips"):
                for account in table_order(snapshot):
                    chip = ui.element("div").classes("yul-chipc").mark(f"pick-{account.id}")
                    clickable(chip, partial(self.toggle_pick, account.id))
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

    # ---- buckets ---------------------------------------------------------------------------

    def _buckets(self, snapshot: Snapshot) -> None:
        formatter = state().require_formatter()
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
        kind = "cash account" if all(buckets[t] is Bucket.CASH for t in targets) else "account"
        debt_hint = f"netted into {plural(len(targets), kind)}" if targets else "not netted"

        hints = {
            Bucket.ASSETS: f"{share(Bucket.ASSETS)} of net worth",
            Bucket.SAVINGS: share(Bucket.SAVINGS),
            Bucket.CASH: f"{share(Bucket.CASH)} · after debt",
            Bucket.DEBT: debt_hint,
        }
        with ui.element("div").classes("yul-nw-tiles yul-stagger"):
            for bucket in NET_WORTH_ORDER:
                style = STYLES[bucket]
                stat_tile(
                    style.title,
                    formatter.format_amount_milli(totals[bucket]),
                    hint=hints[bucket],
                    swatch=style.series,
                ).mark(f"tile-{bucket.value}")
        segmented_bar(
            [
                Segment(STYLES[bucket].title, totals[bucket], STYLES[bucket].color)
                for bucket in SERIES_BUCKETS
            ]
        ).mark("composition")

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
        formatter = state().require_formatter()
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
        name = snapshot.name(account)
        slot = STYLES[account.bucket].slot
        color = self.palette.accent[0] if slot is None else self.palette.series[slot]
        series = [ChartSeries(name, points, color)]
        with self.root:
            chart = account_drawer(
                name=name,
                caption=f"{account.bucket.value.capitalize()} · balance in YNAB",
                balance=formatter.format_amount_milli(snapshot.raw(account_id)),
                since=f"Since {short_date(start, today)}",
                series=series,
                palette=self.palette,
                currency_format=config.budget.currency_format,
                formatter=formatter,
                transactions=transactions[-DRAWER_TRANSACTIONS:][::-1],
            )
        self.drawer = (chart, series)


@shell.view(
    shell.NETWORTH_PATH,
    key="networth",
    title="Net worth",
    subtitle="All your accounts in one figure",
    icon="networth",
    order=40,
)
async def networth_view() -> None:
    await NetWorthView().render()

"""Home: net worth at a glance, a drop target with the last imports, what needs you and activity.

The data comes from `data.load_home`; this module draws it. Live: rendered again after a sync.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from nicegui import run, ui

from ynab_unlinked.core.history import Point
from ynab_unlinked.store import Activity
from ynab_unlinked.web import shell, theme
from ynab_unlinked.web.components import clickable, count_up, glass_card, icon, pill, spinner
from ynab_unlinked.web.components.dropzone import dropzone
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.home.data import (
    SPARK_DAYS,
    Attention,
    HomeData,
    attention_items,
    last_imports_line,
    load_home,
    message_markup,
    relative_time,
)
from ynab_unlinked.web.wording import short_date

SYNC_POLL_SECONDS = 2.0
DOT_KINDS = {"import", "reconcile", "adjustment", "sync", "config"}
"""The activity kinds with their own dot colour; any other gets the `other` dot."""


def _today() -> str:
    today = dt.date.today()
    return f"{today:%A} {today.day} {today:%b}"


def spark_options(points: Sequence[Point]) -> dict[str, Any]:
    """A bare area chart: accent line, accent to transparent fill, no axes, grid or tooltip."""
    start, end = theme.ACCENT
    return {
        "animationDuration": 600,
        "grid": {"left": 0, "right": 0, "top": 4, "bottom": 0},
        "tooltip": {"show": False},
        "xAxis": {
            "type": "category",
            "show": False,
            "boundaryGap": False,
            "data": [point.date.isoformat() for point in points],
        },
        "yAxis": {"type": "value", "show": False, "scale": True},
        "series": [
            {
                "type": "line",
                "data": [point.value / 1000 for point in points],
                "symbol": "none",
                "silent": True,
                "lineStyle": {
                    "width": 2,
                    "join": "round",
                    "color": _gradient(1, 0, [(0, start), (1, end)]),
                },
                "areaStyle": {
                    "color": _gradient(0, 1, [(0, f"{start}73"), (1, f"{end}00")]),
                },
            }
        ],
    }


def _gradient(x2: int, y2: int, stops: list[tuple[float, str]]) -> dict[str, Any]:
    return {
        "type": "linear",
        "x": 0,
        "y": 0,
        "x2": x2,
        "y2": y2,
        "colorStops": [{"offset": offset, "color": color} for offset, color in stops],
    }


def _hero(data: HomeData, today: dt.date) -> None:
    config, _ = state().require()
    money = state().require_formatter().format_amount_milli
    with glass_card(hover=True).classes("yul-hero-card").mark("hero") as card:
        ui.label("Net worth").classes("yul-muted yul-small")
        figure = ui.label(money(data.net_worth)).classes("yul-hero yul-grad").mark("net-worth")
        with ui.element("div").classes("yul-row"):
            if data.delta:
                arrow = "▲" if data.delta > 0 else "▼"
                ui.label(f"{arrow} {money(abs(data.delta))}").classes(
                    "yul-delta " + ("yul-good" if data.delta > 0 else "yul-bad")
                ).mark("net-worth-delta")
            else:
                ui.label("No change").classes("yul-delta yul-muted").mark("net-worth-delta")
            ui.label(f"since {short_date(data.since, today)} · {SPARK_DAYS} days").classes(
                "yul-faint"
            )
        if len(data.spark) > 1:
            ui.echart(spark_options(data.spark)).classes("yul-spark").mark("sparkline")
    clickable(card, lambda: ui.navigate.to(shell.NETWORTH_PATH), role="link")
    count_up(figure, data.net_worth, config.budget.currency_format)


def _activity(entries: Sequence[Activity]) -> None:
    now = dt.datetime.now(dt.UTC)
    with glass_card().mark("activity"):
        ui.label("Recent activity").style("font-weight:600;margin-bottom:10px")
        if not entries:
            ui.label("Nothing yet. Imports, reconciles and balance updates show up here.").classes(
                "yul-muted yul-small"
            ).mark("activity-empty")
            return
        with ui.element("div").classes("yul-act yul-stagger"):
            for entry in entries:
                with ui.element("div").classes("yul-act-it").mark("activity-item"):
                    ui.label(relative_time(entry.at, now)).classes("yul-act-t")
                    kind = entry.kind if entry.kind in DOT_KINDS else "other"
                    ui.element("span").classes(f"yul-act-d {kind}")
                    ui.html(message_markup(entry), sanitize=False).classes("yul-act-m").mark(
                        "activity-message"
                    )


def _attention_card(item: Attention) -> None:
    with glass_card(hover=True).classes("yul-attn-card").mark(f"attention-{item.key}") as card:
        with ui.element("div").classes("yul-attn-head"):
            with ui.element("div").classes("yul-attn-ic"):
                icon(item.icon, 18)
            pill(item.pill, item.pill_kind)
        ui.label(item.figure).classes("yul-attn-k")
        ui.label(item.line).classes("yul-attn-l")
        ui.label(f"{item.action} →").classes("yul-attn-go")
    clickable(card, lambda: ui.navigate.to(item.path), role="link")


def _import_section(data: HomeData, today: dt.date) -> None:
    with ui.element("section").classes("yul-home-block").mark("home-import"):
        ui.label("Import").classes("yul-section")
        dropzone(_drop)
        if (line := last_imports_line(data, today)) is not None:
            ui.label(line).classes("yul-muted yul-small yul-home-line").mark("last-imports")


def _needs_you(data: HomeData) -> None:
    with ui.element("section").classes("yul-home-block yul-needs").mark("needs-you"):
        ui.label("Needs you").classes("yul-section")
        items = attention_items(data)
        if not items:
            ui.label(
                "Nothing waiting. Drop a statement or check back after your next import."
            ).classes("yul-muted yul-small yul-home-line").mark("nothing-waiting")
            return
        with ui.element("div").classes("yul-attn yul-stagger").mark("attention"):
            for item in items:
                _attention_card(item)


async def _drop(files: list[shell.UploadedFile]) -> None:
    await shell.hand_off_uploads(files)


def _banner(body: ui.element) -> ui.element:
    current = state()
    with ui.element("div").classes("yul-banner").mark("first-sync") as banner:
        if current.syncing:
            spinner()
            ui.label("First sync running…")
        else:
            ui.element("span").classes("yul-dot warn")
            ui.label(
                f"Not synced with YNAB yet: {current.sync_error}"
                if current.sync_error
                else "Not synced with YNAB yet. Use the sync chip at the top to fetch your budget."
            )
    if current.syncing:

        async def poll() -> None:
            if state().syncing:
                return
            timer.cancel()
            await _render(body)

        timer = ui.timer(SYNC_POLL_SECONDS, poll)
    return banner


async def _render(body: ui.element) -> None:
    current = state()
    config, _ = current.require()
    today = dt.date.today()
    data = await run.io_bound(load_home, current.store, config, current.loaders, today)
    # None when the app shuts down while reading
    if data is None or body.is_deleted:
        return

    body.clear()
    with body:
        if current.last_sync is None:
            _banner(body)
        with ui.element("div").classes("yul-home-main yul-stagger"):
            _hero(data, today)
            _import_section(data, today)
            _needs_you(data)
        with ui.element("div").classes("yul-home-side"):
            _activity(data.activity)


@shell.view(shell.HOME_PATH, key="home", title="Home", subtitle=_today, icon="home", order=10)
async def home() -> None:
    body = ui.element("div").classes("yul-home").mark("home")
    await _render(body)

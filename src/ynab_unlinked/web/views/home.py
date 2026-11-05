"""Home: net worth at a glance, a drop target with the last imports, what needs you and activity.

Everything comes from the config and the local store; Home never calls YNAB. The store is read
once per visit through `run.io_bound` into a `HomeData`.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from nicegui import run, ui

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.balances import AccountBalance, net_worth
from ynab_unlinked.core.history import TOTAL, Point, net_worth_series
from ynab_unlinked.entities.registry import LoaderSpec
from ynab_unlinked.store import Activity, Store
from ynab_unlinked.web import accounts as tracking
from ynab_unlinked.web import shell, theme
from ynab_unlinked.web.accounts import STALE_AFTER_DAYS
from ynab_unlinked.web.components import (
    PillKind,
    clickable,
    count_up,
    glass_card,
    icon,
    pill,
    spinner,
)
from ynab_unlinked.web.components.dropzone import dropzone
from ynab_unlinked.web.state import state
from ynab_unlinked.web.wording import plural, short_date

SPARK_DAYS = 90
DELTA_FALLBACK_DAYS = 30
"""The hero change is since the last reconcile, or over this many days when there is none."""
RELATIVE_DAYS = 14
"""The last imports line says "3 days ago" under this many days, then the day ("12 Oct")."""
ACTIVITY_LIMIT = 10
SYNC_POLL_SECONDS = 2.0

# Which detail holds the count to embolden in each kind's message (ARCHITECTURE 3.4)
_COUNT_DETAIL = {"import": "created", "reconcile": "count", "sync": "changes"}
_DOT_KINDS = {"import", "reconcile", "adjustment", "sync", "config"}


@dataclass(frozen=True)
class LoaderDue:
    name: str
    key: str
    title: str
    last: dt.date | None
    """Day of the newest import with this loader, None if it was never used from the app."""


@dataclass(frozen=True)
class HomeData:
    net_worth: int
    delta: int
    since: dt.date
    spark: list[Point]
    unreconciled: int
    unreconciled_accounts: int
    stale: list[str]
    """Names of the accounts updated by hand whose balance is older than `STALE_AFTER_DAYS`."""
    last_imports: list[LoaderDue]
    """The banks turned on in Settings, in the order of the loader registry."""
    activity: list[Activity]


def _local_day(moment: dt.datetime) -> dt.date:
    return moment.astimezone().date()


def load_home(
    store: Store,
    config: LatestConfig,
    loaders: Sequence[LoaderSpec],
    today: dt.date,
) -> HomeData:
    """Read everything Home shows from the store. Blocking: run it through `run.io_bound`."""
    budget_id = config.budget.id
    accounts = {account.id: account for account in store.accounts(budget_id)}
    tracked = tracking.effective_accounts(config, accounts.values())
    nettings = tracking.effective_nettings(config)

    worth = net_worth(
        [
            AccountBalance(
                account.id,
                account.name,
                account.bucket,
                stored.balance if (stored := accounts.get(account.id)) else 0,
            )
            for account in tracked
        ],
        nettings,
    )

    reconciles = store.activity(budget_id, limit=1, kind="reconcile")
    since = (
        _local_day(reconciles[0].at)
        if reconciles
        else today - dt.timedelta(days=DELTA_FALLBACK_DAYS)
    )
    spark_start = today - dt.timedelta(days=SPARK_DAYS - 1)
    spark = net_worth_series(store, budget_id, tracked, nettings, spark_start, today)[TOTAL]
    if since >= spark_start:
        before = [point.value for point in spark if point.date <= since]
        then = before[-1] if before else worth.total
    else:
        older = net_worth_series(store, budget_id, tracked, nettings, since, since)[TOTAL]
        then = older[0].value if older else worth.total

    open_ids = {account.id for account in accounts.values() if not account.closed}
    unreconciled = [t for t in store.unreconciled(budget_id) if t.account_id in open_ids]

    stale: list[str] = []
    for account in tracking.by_hand_accounts(config, accounts.values()):
        stored = accounts.get(account.id)
        if stored is not None and stored.closed:
            continue
        transactions = store.transactions(budget_id, account_id=account.id)
        adjustments = [t for t in transactions if t.payee_name == config.adjustments.payee]
        latest = (adjustments or transactions or [None])[-1]
        if latest is None or (today - latest.date).days > STALE_AFTER_DAYS:
            stale.append(account.name)

    last_import: dict[str, dt.date] = {}
    for entry in store.activity(budget_id, limit=None, kind="import"):
        loader = entry.details.get("loader")
        if isinstance(loader, str) and loader not in last_import:
            last_import[loader] = _local_day(entry.at)
    last_imports = [
        LoaderDue(spec.name, spec.key, spec.title, last_import.get(spec.name))
        for spec in loaders
        if (saved := config.entity(spec.name)) is not None and saved.enabled
    ]

    return HomeData(
        net_worth=worth.total,
        delta=worth.total - then,
        since=since,
        spark=spark,
        unreconciled=len(unreconciled),
        unreconciled_accounts=len({t.account_id for t in unreconciled}),
        stale=stale,
        last_imports=last_imports,
        activity=store.activity(budget_id, limit=ACTIVITY_LIMIT),
    )


# ---- wording ------------------------------------------------------------------------------


def relative_time(at: dt.datetime, now: dt.datetime) -> str:
    """ "just now", "2 min", "3 h", then the day ("29 Oct")."""
    seconds = max(0, int((now - at).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min"
    if seconds < 86400:
        return f"{seconds // 3600} h"
    return short_date(_local_day(at), _local_day(now))


def last_import_text(due: LoaderDue, today: dt.date) -> str:
    """ "Sabadell 3 days ago", "Cobee never", "BBVA Credit Card 12 Oct"."""
    if due.last is None:
        when = "never"
    else:
        days = (today - due.last).days
        if days <= 0:
            when = "today"
        elif days == 1:
            when = "yesterday"
        elif days < RELATIVE_DAYS:
            when = f"{days} days ago"
        else:
            when = short_date(due.last, today)
    return f"{due.title} {when}"


def last_imports_line(data: HomeData, today: dt.date) -> str | None:
    """ "Last imports · Cobee never · Sabadell 12 Oct", None when no bank is turned on."""
    if not data.last_imports:
        return None
    return " · ".join(
        ["Last imports", *(last_import_text(due, today) for due in data.last_imports)]
    )


def message_markup(entry: Activity) -> str:
    """The entry's message as escaped HTML, its count in bold and an imported file in mono."""
    markup = html.escape(entry.message)
    count = entry.details.get(_COUNT_DETAIL.get(entry.kind, ""))
    if isinstance(count, int) and not isinstance(count, bool):
        markup = re.sub(rf"(?<![\w.,]){count}(?!\w|[.,]\d)", f"<b>{count}</b>", markup, count=1)
    file = entry.details.get("file")
    if entry.kind == "import" and isinstance(file, str) and file:
        escaped = html.escape(file)
        markup = markup.replace(escaped, f'<span class="yul-mono">{escaped}</span>', 1)
    return markup


@dataclass(frozen=True)
class Attention:
    key: str
    icon: str
    pill: str
    pill_kind: PillKind
    figure: str
    line: str
    action: str
    path: str


def attention_items(data: HomeData) -> list[Attention]:
    """The cards of the "Needs you" row that have something to say, in display order."""
    items: list[Attention] = []
    if data.unreconciled:
        items.append(
            Attention(
                key="unreconciled",
                icon="lock",
                pill="needs you",
                pill_kind="warn",
                figure=plural(data.unreconciled, "transaction"),
                line=f"to reconcile in {plural(data.unreconciled_accounts, 'account')}",
                action="Reconcile",
                path=shell.RECONCILE_PATH,
            )
        )
    if data.stale:
        items.append(
            Attention(
                key="stale",
                icon="networth",
                pill="stale",
                pill_kind="default",
                figure=plural(len(data.stale), "balance"),
                line=f"set by hand, older than {STALE_AFTER_DAYS} days: {', '.join(data.stale)}",
                action="Update balances",
                path=shell.NETWORTH_PATH,
            )
        )
    return items


# ---- rendering ----------------------------------------------------------------------------


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
                    kind = entry.kind if entry.kind in _DOT_KINDS else "other"
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

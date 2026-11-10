"""What Home shows, read and worded without NiceGUI.

`load_home` reads everything once per visit (through `run.io_bound`) into a `HomeData`; the
rest words it: relative times, the last imports line, an activity message as markup, and the
cards of "Needs you". Home never calls YNAB.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.balances import AccountBalance, net_worth
from ynab_unlinked.core.history import TOTAL, Point, net_worth_series
from ynab_unlinked.entities.registry import LoaderSpec
from ynab_unlinked.store import Activity, Store
from ynab_unlinked.web import accounts as tracking
from ynab_unlinked.web import attention
from ynab_unlinked.web.accounts import STALE_AFTER_DAYS
from ynab_unlinked.web.paths import NETWORTH_PATH, RECONCILE_PATH
from ynab_unlinked.web.views.home.pulse import MonthPulse, load_pulse
from ynab_unlinked.web.wording import plural, short_date

if TYPE_CHECKING:
    from ynab_unlinked.web.components import PillKind

SPARK_DAYS = 90
DELTA_FALLBACK_DAYS = 30
"""The hero change is since the last reconcile, or over this many days when there is none."""
RELATIVE_DAYS = 14
"""The last imports line says "3 days ago" under this many days, then the day ("12 Oct")."""
ACTIVITY_LIMIT = 10

# Which detail holds the count to embolden in each kind's message (ARCHITECTURE 3.4)
_COUNT_DETAIL = {"import": "created", "reconcile": "count", "sync": "changes"}


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
    pulse: MonthPulse | None = None
    """The month so far against a usual one; None before the budget has a transaction."""


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
    # Closed accounts held money before they were closed: the history counts them
    history = tracking.history_accounts(config, accounts.values())
    spark = net_worth_series(store, budget_id, history, nettings, spark_start, today)[TOTAL]
    if since >= spark_start:
        before = [point.value for point in spark if point.date <= since]
        then = before[-1] if before else worth.total
    else:
        older = net_worth_series(store, budget_id, history, nettings, since, since)[TOTAL]
        then = older[0].value if older else worth.total

    pending = attention.waiting(store, config, today)

    last_import = {
        loader: _local_day(at) for loader, at in store.last_import_per_loader(budget_id).items()
    }
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
        unreconciled=pending.unreconciled,
        unreconciled_accounts=pending.unreconciled_accounts,
        stale=pending.stale,
        last_imports=last_imports,
        activity=store.activity(budget_id, limit=ACTIVITY_LIMIT),
        pulse=load_pulse(store, config, today) if accounts else None,
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
                path=RECONCILE_PATH,
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
                path=NETWORTH_PATH,
            )
        )
    return items

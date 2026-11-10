"""What is waiting for the user: transactions to reconcile and balances set by hand gone stale.

Home's "Needs you" cards and the sidebar's badges both read it. No NiceGUI here.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.store import Store
from ynab_unlinked.web import accounts as tracking
from ynab_unlinked.web.accounts import STALE_AFTER_DAYS


@dataclass(frozen=True)
class Waiting:
    unreconciled: int
    """Cleared transactions not reconciled yet, in open accounts."""
    unreconciled_accounts: int
    stale: list[str]
    """Names of the open accounts updated by hand whose balance is older than
    `STALE_AFTER_DAYS`."""


NOTHING = Waiting(0, 0, [])


def waiting(store: Store, config: LatestConfig, today: dt.date) -> Waiting:
    """Read what is waiting from the budget copy. Blocking: run it through `run.io_bound`."""
    budget_id = config.budget.id
    accounts = {account.id: account for account in store.accounts(budget_id)}
    open_ids = {account.id for account in accounts.values() if not account.closed}
    unreconciled = [t for t in store.unreconciled(budget_id) if t.account_id in open_ids]

    stale: list[str] = []
    logged = tracking.logged_adjustments(store, budget_id)
    for account in tracking.by_hand_accounts(config, accounts.values()):
        stored = accounts.get(account.id)
        if stored is not None and stored.closed:
            continue
        latest = tracking.last_set_by_hand(
            store.transactions(budget_id, account_id=account.id),
            config.adjustments,
            logged.get(account.id),
        )
        if latest is None or (today - latest).days > STALE_AFTER_DAYS:
            stale.append(account.name)

    return Waiting(
        unreconciled=len(unreconciled),
        unreconciled_accounts=len({t.account_id for t in unreconciled}),
        stale=stale,
    )

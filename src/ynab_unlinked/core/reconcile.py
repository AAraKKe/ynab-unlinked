"""Find what is left to reconcile in YNAB and mark it as reconciled."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from ynab import Account, TransactionClearedStatus, TransactionDetail

from ynab_unlinked.core.progress import NO_PROGRESS, Progress
from ynab_unlinked.ynab_api.client import FULL_SYNC_SINCE, Client


@dataclass(frozen=True)
class AccountToReconcile:
    account: Account
    transactions: tuple[TransactionDetail, ...]
    """Not reconciled yet, newest first."""


def reconciliation_overview(
    client: Client,
    budget_id: str,
    since: dt.date | None,
    progress: Progress = NO_PROGRESS,
) -> list[AccountToReconcile]:
    """
    Every transaction not reconciled since `since` (all of them when None), grouped by account.

    Accounts come in the order YNAB lists them. Closed accounts and accounts with nothing to
    reconcile are left out.
    """
    progress.start("Getting transactions from YNAB")
    # Without a date YNAB answers about one year only, not all of them
    transactions = client.transactions(
        budget_id=budget_id, since_date=FULL_SYNC_SINCE if since is None else since
    )
    accounts = client.accounts(budget_id=budget_id)
    progress.done()

    per_account: dict[str, list[TransactionDetail]] = {}
    for transaction in transactions:
        if transaction.cleared is TransactionClearedStatus.RECONCILED or transaction.deleted:
            continue
        per_account.setdefault(str(transaction.account_id), []).append(transaction)

    return [
        AccountToReconcile(
            account=account,
            transactions=tuple(
                sorted(pending, key=lambda t: t.var_date, reverse=True),
            ),
        )
        for account in accounts
        if not account.closed and (pending := per_account.get(str(account.id)))
    ]


class ReconcileRow(Protocol):
    """What `reconcile` needs of a transaction: its id and its date.

    A stored row of the web app is one as it is; a YNAB `TransactionDetail` goes through
    `RowToLock.of` (its date is `var_date`).
    """

    @property
    def id(self) -> str: ...

    @property
    def date(self) -> dt.date: ...


@dataclass(frozen=True)
class RowToLock:
    """A plain `ReconcileRow`."""

    id: str
    date: dt.date

    @classmethod
    def of(cls, transaction: TransactionDetail) -> RowToLock:
        return cls(id=transaction.id, date=transaction.var_date)


def reconcile(
    client: Client,
    budget_id: str,
    rows: Sequence[ReconcileRow],
    progress: Progress = NO_PROGRESS,
) -> dt.date | None:
    """Mark the transactions as reconciled and return the date of the latest one."""
    if not rows:
        return None

    progress.start("Updating transactions")
    client.update_transactions(
        budget_id=budget_id,
        transaction_ids=[row.id for row in rows],
        cleared=TransactionClearedStatus.RECONCILED,
    )
    progress.done()

    return max(row.date for row in rows)


def next_reconciliation_date(
    locked: Iterable[dt.date], remaining: Iterable[dt.date] = ()
) -> dt.date | None:
    """Where the next reconciliation starts, None when nothing was locked.

    `locked` are the dates just reconciled, `remaining` those of the transactions in scope
    the user chose to leave unreconciled (not the uncleared ones they could not pick, which
    would pin the date forever). With anything left it is the earliest of those, so the next default
    scope still shows them; otherwise the latest date locked. No buffer is applied here: the
    scope rewinds from this date once (`yul reconcile --buffer`, the app's "since" pill).
    """
    latest = max(locked, default=None)
    if latest is None:
        return None
    return min(remaining, default=latest)

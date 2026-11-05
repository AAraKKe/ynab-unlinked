"""Find what is left to reconcile in YNAB and mark it as reconciled."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from ynab import Account, TransactionClearedStatus, TransactionDetail

from ynab_unlinked.config.constants import TRANSACTION_GRACE_PERIOD_DAYS
from ynab_unlinked.core.progress import NO_PROGRESS, Progress
from ynab_unlinked.ynab_api.client import Client


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
    transactions = client.transactions(budget_id=budget_id, since_date=since)
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


def reconcile(
    client: Client,
    budget_id: str,
    transactions: Sequence[TransactionDetail],
    progress: Progress = NO_PROGRESS,
) -> dt.date | None:
    """Mark the transactions as reconciled and return the date of the latest one."""
    if not transactions:
        return None

    progress.start("Updating transactions")
    client.update_transactions(
        budget_id=budget_id,
        transactions=[
            t.model_copy(update={"cleared": TransactionClearedStatus.RECONCILED})
            for t in transactions
        ],
    )
    progress.done()

    return max(t.var_date for t in transactions)


def next_reconciliation_date(latest: dt.date) -> dt.date:
    """Where the next reconciliation starts, rewound so late cleared transactions are seen."""
    return latest - dt.timedelta(days=TRANSACTION_GRACE_PERIOD_DAYS)

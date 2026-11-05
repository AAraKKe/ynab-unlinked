"""What Reconcile shows and writes, worked out without NiceGUI.

The scope ("since" the last reconciliation, or all time), the unreconciled transactions of the
open accounts in it, the rows that could explain a difference with the bank, and the words and
the log entry of a lock. The view (`view`) keeps the selection and draws it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ynab import TransactionClearedStatus, TransactionDetail

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.core.balances import parse_amount_to_milliunits
from ynab_unlinked.core.reconcile import next_reconciliation_date
from ynab_unlinked.store import Store, StoredAccount, StoredTransaction
from ynab_unlinked.web.wording import plural

SYNC_MAX_AGE = dt.timedelta(minutes=10)
SCOPE_BUFFER_DAYS = 7
"""How far before the last reconciliation the "since" scope starts, as `yul reconcile -b`."""

SINCE = "since"
ALL_TIME = "all"
UNCLEARED_SKIPPED = "Uncleared rows are skipped. Turn on “include uncleared” to lock them too."


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


@dataclass
class ReconcileData:
    """The budget's accounts and its unreconciled transactions, as the store has them."""

    accounts: list[StoredAccount] = field(default_factory=list[StoredAccount])
    unreconciled: list[StoredTransaction] = field(default_factory=list[StoredTransaction])

    @classmethod
    def read(cls, store: Store, budget_id: str) -> ReconcileData:
        """Blocking: run it through `run.io_bound`."""
        return cls(accounts=store.accounts(budget_id), unreconciled=store.unreconciled(budget_id))

    def open_transactions(
        self, since: dt.date | None, locked: set[str]
    ) -> list[tuple[StoredAccount, list[StoredTransaction]]]:
        """Unreconciled transactions of open accounts from `since` on, newest first.

        `locked` are the ids locked in this visit: hidden even before a sync catches up.
        """
        per_account: dict[str, list[StoredTransaction]] = {}
        for transaction in reversed(self.unreconciled):
            if transaction.id in locked:
                continue
            if since is not None and transaction.date < since:
                continue
            per_account.setdefault(transaction.account_id, []).append(transaction)
        return [
            (account, per_account[account.id])
            for account in self.accounts
            if not account.closed and account.id in per_account
        ]

    def has_anything(self, locked: set[str]) -> bool:
        """Whether any open account has a transaction left to reconcile, whatever the scope."""
        open_ids = {account.id for account in self.accounts if not account.closed}
        return any(t.account_id in open_ids and t.id not in locked for t in self.unreconciled)


def parse_bank_balance(text: str, currency_format: CurrencyFormat) -> int | None:
    """The balance typed as "your bank says", None when it is empty or not an amount."""
    if not text.strip():
        return None
    try:
        return parse_amount_to_milliunits(
            text,
            decimal_separator=currency_format.decimal_separator,
            group_separator=currency_format.group_separator,
        )
    except ValueError:
        return None


LockBatch = tuple[StoredAccount, Sequence[StoredTransaction]]
"""One account and the transactions of it to lock."""


def lock_confirmation(batches: Sequence[LockBatch]) -> tuple[str, list[str], str]:
    """The confirmation of a lock: its title, what will change, and the action's label."""
    count = sum(len(transactions) for _, transactions in batches)
    lines = [
        f"{account.name} · {plural(len(transactions), 'transaction')}"
        for account, transactions in batches
    ]
    uncleared = sum(
        t.cleared is TransactionClearedStatus.UNCLEARED
        for _, transactions in batches
        for t in transactions
    )
    if uncleared:
        lines.append(f"{uncleared} of them {'is' if uncleared == 1 else 'are'} still uncleared")
    title = f"Lock {plural(count, 'transaction')} in {plural(len(batches), 'account')}?"
    return title, [*lines, "They are marked reconciled in YNAB."], f"Lock {count}"


def lock_log(batches: Sequence[LockBatch]) -> tuple[str, dict[str, Any]]:
    """The activity log message and details of a lock (ARCHITECTURE 3.4)."""
    count = sum(len(transactions) for _, transactions in batches)
    message = f"Reconciled {plural(count, 'transaction')} in {plural(len(batches), 'account')}"
    details: dict[str, Any] = {
        "count": count,
        "accounts": [
            {"id": account.id, "name": account.name, "count": len(transactions)}
            for account, transactions in batches
        ],
    }
    return message, details


def lock_checkpoint(
    locked: Sequence[StoredTransaction],
    pending: Sequence[StoredTransaction],
    *,
    include_uncleared: bool,
) -> dt.date | None:
    """The next `last_reconciliation_date` after locking `locked`, `pending` being every row
    still not reconciled in the scope (the locked ones included or not)."""
    locking = {transaction.id for transaction in locked}
    return next_reconciliation_date(
        [transaction.date for transaction in locked],
        # Only rows the user chose to skip hold the checkpoint back: an uncleared row they
        # could not pick ("include uncleared" off) would pin it, and the scope, forever
        [
            transaction.date
            for transaction in pending
            if transaction.id not in locking
            and (include_uncleared or transaction.cleared is not TransactionClearedStatus.UNCLEARED)
        ],
    )


def pending_title(accounts: int, transactions: int, any_account: bool) -> str:
    """The header of the list: what is left to reconcile in the scope."""
    if transactions:
        return (
            f"{plural(accounts, 'account')} · {plural(transactions, 'transaction')} not reconciled"
        )
    if any_account:
        return "Everything here is reconciled"
    return "Nothing to reconcile in this range"


__all__ = [
    "ALL_TIME",
    "SCOPE_BUFFER_DAYS",
    "SINCE",
    "SYNC_MAX_AGE",
    "UNCLEARED_SKIPPED",
    "LockBatch",
    "ReconcileData",
    "gap_candidates",
    "lock_checkpoint",
    "lock_confirmation",
    "lock_log",
    "parse_bank_balance",
    "pending_title",
    "scope_start",
    "transaction_detail",
]

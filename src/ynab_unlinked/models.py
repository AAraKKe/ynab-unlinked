import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from typing import assert_never

from ynab import TransactionClearedStatus


@dataclass(frozen=True)
class Transaction:
    """Represents a transaction imported from a file by a given entity"""

    date: dt.date
    payee: str
    amount: float


@dataclass(frozen=True)
class PendingImport:
    """A transaction ready to be sent to YNAB under a stable import id."""

    transaction: Transaction
    import_id: str
    legacy_import_id: str


def milliunits(amount: float) -> int:
    return round(amount * 1000)


def cleared_str(cleared: TransactionClearedStatus) -> str:
    match cleared:
        case TransactionClearedStatus.RECONCILED:
            return "🔒 Reconciled"
        case TransactionClearedStatus.CLEARED:
            return "✅ Cleared"
        case TransactionClearedStatus.UNCLEARED:
            return "Uncleared"
        case _ as never:
            assert_never(never)


def _legacy_import_id(transaction: Transaction, counter: int) -> str:
    # Reproduces the id scheme of releases before import ids followed the YNAB convention, so a
    # transaction already imported by one of those is still recognised. Remove it once every user
    # has run an import with the new scheme.
    return sha256(
        f"{transaction.date:%m-%d-%Y}{transaction.payee}{transaction.amount}{counter}".encode()
    ).hexdigest()[:30]


def assign_import_ids(transactions: list[Transaction]) -> list[PendingImport]:
    """
    Pair every transaction with the import id YNAB identifies it by.

    The occurrence of identical rows is counted in file order, so an export that overlaps a
    previous one yields the same ids and YNAB rejects the rows it already holds.
    """
    occurrences: defaultdict[tuple[dt.date, int], int] = defaultdict(int)
    legacy_counters: defaultdict[tuple[dt.date, str, float], int] = defaultdict(int)

    pending: list[PendingImport] = []
    for transaction in transactions:
        amount = milliunits(transaction.amount)
        occurrences[transaction.date, amount] += 1
        legacy_key = (transaction.date, transaction.payee, transaction.amount)
        counter = legacy_counters[legacy_key]
        legacy_counters[legacy_key] += 1

        pending.append(
            PendingImport(
                transaction=transaction,
                import_id=(
                    f"YNAB:{amount}:{transaction.date:%Y-%m-%d}"
                    f":{occurrences[transaction.date, amount]}"
                ),
                legacy_import_id=_legacy_import_id(transaction, counter),
            )
        )

    return pending

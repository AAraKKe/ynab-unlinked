import datetime as dt
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import assert_never

from ynab.models.transaction_cleared_status import TransactionClearedStatus
from ynab.models.transaction_detail import TransactionDetail


class MatchStatus(Enum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    PARTIAL_MATCH = "partial_match"


@dataclass
class Transaction:
    """Represents a transaction imported from a file by a given entity"""

    date: dt.date
    payee: str
    amount: float

    def __post_init__(self):
        self.past = False
        self.counter = 0

    @property
    def pretty_payee(self) -> str:
        return self.payee if len(self.payee) < 15 else f"{self.payee[:15]}..."

    def __hash__(self) -> int:
        return hash(f"{self.date:%m-%d-%Y}{self.payee}{self.amount}")

    @property
    def id(self) -> str:
        return sha256(
            f"{self.date:%m-%d-%Y}{self.payee}{self.amount}{self.counter}".encode()
        ).hexdigest()[:30]

    @property
    def inflow(self) -> float | None:
        return self.amount if self.amount > 0 else None

    @property
    def outflow(self) -> float | None:
        return self.amount if self.amount < 0 else None

    def __repr__(self) -> str:
        return (
            f"Transaction(date={self.date}, payee={self.payee},"
            f"amount={self.amount}, past={self.past}, counter={self.counter})"
        )


class TransactionWithYnabData(Transaction):
    def __init__(self, transaction: Transaction):
        super().__init__(
            date=transaction.date,
            payee=transaction.payee,
            amount=transaction.amount,
        )
        self.match_status: MatchStatus = MatchStatus.UNMATCHED
        self.partial_match: TransactionDetail | None = None
        self.ynab_id: str | None = None
        self.ynab_payee_id: str | None = None
        self.ynab_payee: str | None = transaction.payee
        # All transactions are cleared by default because we get them from an entity export
        self.cleared: TransactionClearedStatus = TransactionClearedStatus.CLEARED
        self.ynab_cleared: TransactionClearedStatus | None = None

    def __repr__(self) -> str:
        return (
            f"Transaction(date={self.date}, payee={self.payee!r}, "
            f"amount={self.amount}, past={self.past}, counter={self.counter}, "
            f"match_status={self.match_status}, partial_match={self.partial_match!r}, "
            f"ynab_id={self.ynab_id!r}, ynab_payee_id={self.ynab_payee_id!r}, "
            f"ynab_payee={self.ynab_payee!r}, cleared={self.cleared}, "
            f"ynab_cleared={self.ynab_cleared})"
        )

    @property
    def needs_creation(self) -> bool:
        match_uncleared = (
            self.partial_match is not None
            and self.partial_match.cleared is TransactionClearedStatus.UNCLEARED
        )
        is_unmatched = self.match_status is MatchStatus.UNMATCHED

        return is_unmatched or match_uncleared

    @property
    def cleared_status(self) -> str:
        """
        Generate cleared string representation.

        If the transaction does not need to be created and it has an internal `ynab_cleared`
        status set, the representation of `ynab_cleared` is shown instead. Otherwise,
        the representation of `cleared` is shown instead.
        """
        cleared = (
            self.ynab_cleared
            if not self.needs_creation and self.ynab_cleared is not None
            else self.cleared
        )
        return self.cleared_str(cleared)

    @property
    def ynab_cleared_status(self) -> str:
        return self.cleared_str(self.ynab_cleared) if self.ynab_cleared else ""

    @property
    def match_emoji(self) -> str:
        match self.match_status:
            case MatchStatus.MATCHED:
                return "🔗"
            case MatchStatus.PARTIAL_MATCH:
                assert self.partial_match is not None, (
                    "Cannot have a partial match without a transaction"
                )

                if self.partial_match.cleared is TransactionClearedStatus.UNCLEARED:
                    return "🔍"
                return "🔗"
            case _:
                return ""

    @staticmethod
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

    def reset_matching(self):
        """Reset the matching status to UNMATCHED and the payee to the original one"""
        self.match_status = MatchStatus.UNMATCHED
        self.partial_match = None
        self.ynab_payee = self.payee
        self.ynab_payee_id = None

    def update_cleared_from_ynab(self, ynab_transaction: TransactionDetail, reconcile: bool):
        if ynab_transaction.cleared is TransactionClearedStatus.RECONCILED or reconcile:
            self.cleared = TransactionClearedStatus.RECONCILED
        elif ynab_transaction.cleared is TransactionClearedStatus.UNCLEARED:
            self.cleared = TransactionClearedStatus.CLEARED

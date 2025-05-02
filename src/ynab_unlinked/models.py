from enum import Enum
import datetime as dt
from dataclasses import dataclass
from typing import assert_never

from ynab import TransactionClearedStatus, TransactionDetail


class MatchStatus(Enum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    PARTIAL_MATCH = "partial_match"


@dataclass
class Transaction:
    date: dt.date
    payee: str
    amount: float
    past: bool = False

    @property
    def pretty_payee(self) -> str:
        return self.payee if len(self.payee) < 15 else f"{self.payee[:15]}..."

    @property
    def pretty_amount(self) -> str:
        return f"{self.amount:.2f}€"

    def __hash__(self) -> int:
        return hash(f"{self.date:%m-%d-%Y}{self.payee}{self.amount}")


class TransactionWithYnabData(Transaction):
    def __init__(self, transaction: Transaction):
        super().__init__(
            date=transaction.date,
            payee=transaction.payee,
            amount=transaction.amount,
            past=transaction.past,
        )
        self.match_status: MatchStatus = MatchStatus.UNMATCHED
        self.partial_match: TransactionDetail | None = None
        self.ynab_id: str | None = None
        self.ynab_payee_id: str | None = None
        self.ynab_payee: str | None = transaction.payee
        # All transactions are cleared by default because we get them from an entity export
        self.cleared: TransactionClearedStatus = TransactionClearedStatus.CLEARED
        self.ynab_cleared: TransactionClearedStatus | None = None

    @property
    def needs_creation(self) -> bool:
        return self.match_status is MatchStatus.UNMATCHED

    @property
    def needs_update(self) -> bool:
        return (
            self.match_status is not MatchStatus.UNMATCHED
            and self.ynab_cleared is not self.cleared
        )

    @property
    def cleared_status(self) -> str:
        return self.cleared_str(self.cleared)

    @property
    def ynab_cleared_status(self) -> str:
        return self.cleared_str(self.ynab_cleared) if self.ynab_cleared else ""

    @property
    def match_emoji(self) -> str:
        match self.match_status:
            case MatchStatus.MATCHED:
                return "🔗"
            case MatchStatus.PARTIAL_MATCH:
                if self.needs_update:
                    return "🔍"
                else:
                    return "🔗"
            case _:
                return ""

    def cleared_str(self, cleared: TransactionClearedStatus) -> str:
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

    def update_cleared_from_ynab(
        self, ynab_transaction: TransactionDetail, reconcile: bool
    ):
        if reconcile:
            self.cleared = TransactionClearedStatus.RECONCILED
        elif ynab_transaction.cleared is TransactionClearedStatus.UNCLEARED:
            self.cleared = TransactionClearedStatus.CLEARED

import datetime as dt
from dataclasses import dataclass
from typing import assert_never

from ynab.models.transaction_cleared_status import TransactionClearedStatus


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
        self.ynab_id: str | None = None
        self.ynab_payee_id: str | None = None
        self.ynab_payee: str | None = None
        self.cleared: TransactionClearedStatus = TransactionClearedStatus.UNCLEARED
        self.needs_update: bool = False

    @property
    def needs_creation(self) -> bool:
        return not (self.ynab_id or self.needs_update)

    @property
    def cleared_status(self) -> str:
        match self.cleared:
            case TransactionClearedStatus.RECONCILED:
                return "🔒 Reconciled"
            case TransactionClearedStatus.CLEARED:
                return "✅ Cleared"
            case TransactionClearedStatus.UNCLEARED:
                return "Uncleared"
            case _ as never:
                assert_never(never)

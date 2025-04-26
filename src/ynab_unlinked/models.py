import datetime as dt
from dataclasses import dataclass
from typing import assert_never

from ynab.models.transaction_cleared_status import TransactionClearedStatus


@dataclass
class Transaction:
    date: dt.date
    payee: str
    amount: float
    past: bool
    cleared: bool = True
    reconciled: bool = False
    ynab_id: str | None = None
    payee_id: str | None = None
    needs_update: bool = False
    ynab_payee: str | None = None

    @property
    def pretty_payee(self) -> str:
        return self.payee if len(self.payee) < 15 else f"{self.payee[:15]}..."

    @property
    def pretty_amount(self) -> str:
        return f"{self.amount:.2f}€"

    @property
    def cleared_status(self) -> str:
        if self.reconciled:
            return "🔒 Reconciled"

        return "✅ Cleared" if self.cleared else "Uncleared"

    @property
    def ynab_cleared_status(self) -> TransactionClearedStatus:
        if self.reconciled:
            return TransactionClearedStatus.RECONCILED
        if self.cleared:
            return TransactionClearedStatus.CLEARED
        return TransactionClearedStatus.UNCLEARED

    @property
    def needs_creation(self) -> bool:
        return not (self.ynab_id or self.needs_update)

    def reconcile_from_ynab(self, ynab_cleared: TransactionClearedStatus):
        match ynab_cleared:
            case TransactionClearedStatus.RECONCILED:
                self.reconciled = True
                self.cleared = True
            case TransactionClearedStatus.CLEARED:
                self.reconciled = False
                self.cleared = True
            case TransactionClearedStatus.UNCLEARED:
                self.reconciled = False
                self.cleared = False
            case _:
                assert_never(ynab_cleared)

    def __str__(self) -> str:
        return f"{self.date:%m-%d-%Y} | {self.pretty_payee:<20} | {self.pretty_amount:>10} | {self.cleared_status:<15}"

    def __hash__(self) -> int:
        return hash(f"{self.date:%m-%d-%Y}{self.payee}{self.amount}")

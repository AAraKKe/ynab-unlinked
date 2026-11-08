"""The selection Reconcile keeps on screen: an account's rows and the elements that show them."""

from __future__ import annotations

from dataclasses import dataclass

from nicegui import ui
from ynab import TransactionClearedStatus

from ynab_unlinked.store import StoredAccount, StoredTransaction


@dataclass(eq=False)
class Row:
    transaction: StoredTransaction
    selected: bool
    locked: bool = False
    """Reconciled in this visit: listed under Reconciled until the list is drawn again."""
    element: ui.element | None = None
    box: ui.element | None = None

    @property
    def uncleared(self) -> bool:
        return self.transaction.cleared is TransactionClearedStatus.UNCLEARED

    @property
    def to_lock(self) -> bool:
        return self.selected and not self.locked


@dataclass(eq=False)
class AccountGroup:
    account: StoredAccount
    rows: list[Row]
    matches: bool | None = None
    """None until a bank balance is typed, then whether it equals the cleared balance."""
    difference: int = 0
    open: bool = False
    cleared_count: ui.label | None = None
    uncleared_count: ui.label | None = None
    match: ui.element | None = None
    rows_box: ui.element | None = None
    cleared_note: ui.label | None = None
    uncleared_note: ui.label | None = None
    bar: ui.element | None = None
    toggle_label: ui.label | None = None
    action: ui.element | None = None
    """The right of the bar: the account's Reconcile button, or "reconciled" once done."""
    lock_button: ui.button | None = None
    lock_label: ui.label | None = None
    done: ui.element | None = None
    bank: ui.input | None = None

    def to_lock(self) -> list[Row]:
        return [row for row in self.rows if row.to_lock]

    def pending(self) -> list[Row]:
        return [row for row in self.rows if not row.locked]

    def cleared(self) -> list[Row]:
        """Cleared rows not reconciled yet: the Cleared section."""
        return [row for row in self.pending() if not row.uncleared]

    def uncleared(self) -> list[Row]:
        """The Uncleared section."""
        return [row for row in self.pending() if row.uncleared]

    def reconciled(self) -> list[Row]:
        """Rows reconciled in this visit: the Reconciled section."""
        return [row for row in self.rows if row.locked]

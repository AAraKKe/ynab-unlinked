"""Whether the account a bank's statements are saved to can still take them.

YNAB accepts transactions into a closed account without complaint, and they then show
nowhere. So the account saved for a bank (`config.entity(name).account_id`) is checked
against the budget's accounts before anything is imported into it.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Protocol


class AccountState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    """Closed in YNAB: what is imported into it is hidden."""
    MISSING = "missing"
    """Deleted in YNAB, or never in this budget (the budget was changed since)."""

    @property
    def reason(self) -> str:
        """Why the account cannot take statements, to follow "The account saved for <bank>"."""
        match self:
            case AccountState.CLOSED:
                return "is closed in YNAB"
            case AccountState.MISSING:
                return "is no longer in the budget"
            case AccountState.OPEN:
                return "is open"


class BudgetAccount(Protocol):
    """An account of the budget as YNAB (`ynab.Account`) or the store (`StoredAccount`) has it."""

    @property
    def id(self) -> object: ...

    @property
    def closed(self) -> bool: ...


def account_state(account_id: str, accounts: Iterable[BudgetAccount]) -> AccountState:
    """Whether `account_id` is an open account among the budget's `accounts`.

    `accounts` must be the whole list of the budget (YNAB's or the store's copy of it): an
    account not in it is `MISSING`. One YNAB flags deleted counts as missing too.
    """
    for account in accounts:
        if str(account.id) != account_id:
            continue
        # Only `ynab.Account` has the flag: the store never keeps a deleted account
        if getattr(account, "deleted", False):
            return AccountState.MISSING
        return AccountState.CLOSED if account.closed else AccountState.OPEN
    return AccountState.MISSING

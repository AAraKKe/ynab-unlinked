"""Which accounts the views count in net worth.

Every open account of the budget counts, in the bucket of its type, unless the config leaves
it out (`TrackedAccount.counted`). A config entry only records what differs from the
defaults: the bucket, the balance set by hand, or being left out.

No NiceGUI here: the views' pure data modules count accounts through it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence

from ynab import AccountType

from ynab_unlinked.buckets import Bucket, bucket_for
from ynab_unlinked.config import Adjustments, LatestConfig, TrackedAccount
from ynab_unlinked.core.balances import DebtNetting
from ynab_unlinked.store import Store, StoredAccount, StoredTransaction

STALE_AFTER_DAYS = 30
"""A balance set by hand is stale once it is older than this: Home's card, Net worth's pill."""


def default_bucket(account_type: str) -> Bucket:
    """The net worth bucket of a YNAB account type given as its string value."""
    try:
        return bucket_for(AccountType(account_type))
    except ValueError:
        return Bucket.ASSETS


def default_account(account: StoredAccount) -> TrackedAccount:
    """How an account counts when the config says nothing about it.

    Investment and other asset accounts are the ones people update by hand.
    """
    bucket = default_bucket(account.type)
    return TrackedAccount(
        id=account.id,
        name=account.name,
        type=account.type,
        bucket=bucket,
        track_balance=bucket is Bucket.ASSETS,
    )


def account_settings(config: LatestConfig, account: StoredAccount) -> TrackedAccount:
    """The config entry of an account, or its defaults, counted or not."""
    if (saved := config.account(account.id)) is not None:
        return saved
    return default_account(account)


def effective_accounts(
    config: LatestConfig, stored: Iterable[StoredAccount]
) -> list[TrackedAccount]:
    """The accounts net worth counts: every open account in `stored` that is not left out.

    Config entries of accounts that are closed or no longer in the budget are ignored.
    """
    accounts: list[TrackedAccount] = []
    for account in stored:
        if account.closed:
            continue
        settings = account_settings(config, account)
        if settings.counted:
            accounts.append(settings)
    return accounts


def follows_return(config: LatestConfig, account: TrackedAccount, on_budget: bool) -> bool:
    """Whether Net worth shows the account's return: Settings say so, else asset and tracking
    accounts do."""
    default = account.bucket is Bucket.ASSETS or not on_budget
    return config.finances.returns.get(account.id, default)


def history_accounts(config: LatestConfig, stored: Iterable[StoredAccount]) -> list[TrackedAccount]:
    """The accounts net worth counts over time: the counted ones and the closed ones not left
    out. A closed account's balance is zero now, but it held money before it was closed, so
    leaving it out would understate every month before and turn its transfers into money from
    nowhere."""
    stored = list(stored)
    closed = [
        settings
        for account in stored
        if account.closed and (settings := account_settings(config, account)).counted
    ]
    return [*effective_accounts(config, stored), *closed]


def by_hand_accounts(config: LatestConfig, stored: Iterable[StoredAccount]) -> list[TrackedAccount]:
    """The counted accounts whose balance the user enters by hand."""
    return [account for account in effective_accounts(config, stored) if account.track_balance]


def effective_nettings(config: LatestConfig) -> tuple[DebtNetting, ...]:
    """The configured debt mappings."""
    return tuple(
        DebtNetting(debt_account_id=mapping.debt_account_id, mapped_to=tuple(mapping.mapped_to))
        for mapping in config.debt_mappings
    )


def last_set_by_hand(
    transactions: Sequence[StoredTransaction], settings: Adjustments, logged: dt.date | None
) -> dt.date | None:
    """When a balance kept by hand was last set: the newest adjustment, else the newest
    transaction, None when the account has none.

    An adjustment is a transaction with the payee or the memo of the adjustment settings, or
    one yul logged for the account (`logged`, the day of the newest `adjustment` entry), so
    the ones made before the settings changed still count.
    """
    adjusted = [
        t.date for t in transactions if t.payee_name == settings.payee or t.memo == settings.memo
    ]
    if logged is not None:
        adjusted.append(logged)
    if adjusted:
        return max(adjusted)
    return max((t.date for t in transactions), default=None)


def logged_adjustments(store: Store, budget_id: str) -> dict[str, dt.date]:
    """The day of the newest adjustment yul logged, per account id."""
    days: dict[str, dt.date] = {}
    for entry in store.activity(budget_id, limit=None, kind="adjustment"):
        account_id = entry.details.get("account_id")
        if isinstance(account_id, str):
            day = entry.at.astimezone().date()
            days[account_id] = max(day, days.get(account_id, day))
    return days

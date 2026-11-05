"""Which accounts the views count in net worth.

Every open account of the budget counts, in the bucket of its type, unless the config leaves
it out (`TrackedAccount.counted`). A config entry only records what differs from the
defaults: the bucket, the balance set by hand, or being left out.
"""

from __future__ import annotations

from collections.abc import Iterable

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import LatestConfig, TrackedAccount
from ynab_unlinked.core.balances import DebtNetting
from ynab_unlinked.store import StoredAccount
from ynab_unlinked.web.state import default_bucket

STALE_AFTER_DAYS = 30
"""A balance set by hand is stale once it is older than this: Home's card, Net worth's pill."""


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


def by_hand_accounts(config: LatestConfig, stored: Iterable[StoredAccount]) -> list[TrackedAccount]:
    """The counted accounts whose balance the user enters by hand."""
    return [account for account in effective_accounts(config, stored) if account.track_balance]


def effective_nettings(config: LatestConfig) -> tuple[DebtNetting, ...]:
    """The configured debt mappings."""
    return tuple(
        DebtNetting(debt_account_id=mapping.debt_account_id, mapped_to=tuple(mapping.mapped_to))
        for mapping in config.debt_mappings
    )

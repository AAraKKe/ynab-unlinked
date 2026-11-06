import datetime as dt

import pytest
from ynab import TransactionClearedStatus

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import Adjustments, DebtMapping, LatestConfig, TrackedAccount
from ynab_unlinked.store import StoredAccount, StoredTransaction
from ynab_unlinked.web.accounts import (
    by_hand_accounts,
    effective_accounts,
    effective_nettings,
    last_set_by_hand,
)

pytestmark = pytest.mark.version("V4")


def stored(id: str, type: str, *, closed: bool = False) -> StoredAccount:
    return StoredAccount(
        id=id,
        name=id.title(),
        type=type,
        closed=closed,
        on_budget=True,
        balance=0,
        cleared_balance=0,
        uncleared_balance=0,
    )


BUDGET = [
    stored("checking", "checking"),
    stored("card", "creditCard"),
    stored("broker", "otherAsset"),
    stored("old", "savings", closed=True),
]


def test_without_account_settings_every_open_account_counts_with_its_defaults(
    config_v4: LatestConfig,
):
    config_v4.debt_mappings = [DebtMapping(debt_account_id="card", mapped_to=["checking"])]

    accounts = effective_accounts(config_v4, BUDGET)

    # Investment and other asset accounts default to a balance entered by hand
    assert [(a.id, a.bucket, a.track_balance) for a in accounts] == [
        ("checking", Bucket.CASH, False),
        ("card", Bucket.DEBT, False),
        ("broker", Bucket.ASSETS, True),
    ]
    assert [a.id for a in by_hand_accounts(config_v4, BUDGET)] == ["broker"]
    [netting] = effective_nettings(config_v4)
    assert (netting.debt_account_id, netting.mapped_to) == ("card", ("checking",))


def test_account_settings_win_over_the_defaults_and_left_out_accounts_do_not_count(
    config_v4: LatestConfig,
):
    config_v4.accounts = [
        TrackedAccount(id="card", name="Card", type="creditCard", bucket=Bucket.DEBT),
        TrackedAccount(id="checking", name="Checking", type="checking", bucket=Bucket.SAVINGS),
        TrackedAccount(
            id="broker", name="Broker", type="otherAsset", bucket=Bucket.ASSETS, counted=False
        ),
        # Settings of a closed account and of one no longer in the budget are ignored
        TrackedAccount(id="old", name="Old", type="savings", bucket=Bucket.SAVINGS),
        TrackedAccount(id="gone", name="Gone", type="cash", bucket=Bucket.CASH),
    ]

    accounts = effective_accounts(config_v4, BUDGET)

    assert accounts == [config_v4.accounts[1], config_v4.accounts[0]]
    assert by_hand_accounts(config_v4, BUDGET) == []


def test_a_config_entry_defaults_to_counted():
    # Configs written before `counted` existed load with every entry counted
    entry = TrackedAccount.model_validate(
        {"id": "card", "name": "Card", "type": "creditCard", "bucket": "debt"}
    )

    assert entry.counted is True


def days_ago(days: int) -> dt.date:
    return dt.date.today() - dt.timedelta(days=days)


def by_hand(id: str, days: int, *, payee: str = "Shop", memo: str | None = None):
    return StoredTransaction(
        id=id,
        account_id="broker",
        date=days_ago(days),
        amount=0,
        cleared=TransactionClearedStatus.RECONCILED,
        approved=True,
        deleted=False,
        payee_name=payee,
        category_name=None,
        import_id=None,
        memo=memo,
        transfer_account_id=None,
    )


@pytest.mark.parametrize(
    ("transactions", "logged", "expected"),
    [
        pytest.param([], None, None, id="nothing-yet"),
        pytest.param([by_hand("d", 2)], None, 2, id="no-adjustment-the-newest-transaction"),
        pytest.param(
            [by_hand("a", 40, payee="Saldo"), by_hand("d", 2)], None, 40, id="by-the-payee"
        ),
        pytest.param(
            [by_hand("a", 40, memo="Set by hand"), by_hand("d", 2)], None, 40, id="by-the-memo"
        ),
        # Made before the payee and the memo changed: only the log still knows it
        pytest.param(
            [by_hand("a", 40, payee="Old payee"), by_hand("d", 2)], 40, 40, id="logged-by-yul"
        ),
    ],
)
def test_a_balance_set_by_hand_dates_from_its_newest_adjustment(
    transactions: list[StoredTransaction], logged: int | None, expected: int | None
):
    settings = Adjustments(payee="Saldo", memo="Set by hand")

    last = last_set_by_hand(transactions, settings, None if logged is None else days_ago(logged))

    assert last == (None if expected is None else days_ago(expected))

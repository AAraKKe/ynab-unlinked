import pytest

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import DebtMapping, LatestConfig, TrackedAccount
from ynab_unlinked.store import StoredAccount
from ynab_unlinked.web.accounts import by_hand_accounts, effective_accounts, effective_nettings

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

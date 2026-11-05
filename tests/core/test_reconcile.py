import datetime as dt
import uuid

import pytest
from ynab import Account, TransactionClearedStatus, TransactionDetail

from tests.core.conftest import BUDGET_ID
from tests.factories import AccountFactory, TransactionDetailFactory
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.core.reconcile import (
    next_reconciliation_date,
    reconcile,
    reconciliation_overview,
)
from ynab_unlinked.ynab_api import Client

CHECKING_ID = uuid.UUID(int=10)
SAVINGS_ID = uuid.UUID(int=11)
OLD_CARD_ID = uuid.UUID(int=12)

CHECKING = AccountFactory(id=CHECKING_ID, name="Checking")
SAVINGS = AccountFactory(id=SAVINGS_ID, name="Savings")
OLD_CARD = AccountFactory(id=OLD_CARD_ID, name="Old card", closed=True)

RECONCILED = TransactionClearedStatus.RECONCILED
UNCLEARED = TransactionClearedStatus.UNCLEARED


def ynab_holds(
    ynab_api: YnabClientStub, transactions: list[TransactionDetail], accounts: list[Account]
) -> None:
    ynab_api.api("transactions").get_transactions.return_value.data.transactions = transactions
    ynab_api.api("accounts").get_accounts.return_value.data.accounts = accounts


def on(account_id: uuid.UUID, id: str, day: int, **kwargs) -> TransactionDetail:
    return TransactionDetailFactory(
        id=id, account_id=account_id, var_date=dt.date(2025, 5, day), **kwargs
    )


@pytest.mark.parametrize(
    ("transactions", "accounts", "expected"),
    [
        pytest.param(
            [on(SAVINGS_ID, "s1", 3), on(CHECKING_ID, "c1", 1), on(CHECKING_ID, "c2", 9)],
            [CHECKING, SAVINGS],
            [("Checking", ["c2", "c1"]), ("Savings", ["s1"])],
            id="accounts-in-ynab-order-transactions-newest-first",
        ),
        pytest.param(
            [
                on(CHECKING_ID, "c1", 1, cleared=RECONCILED),
                on(CHECKING_ID, "c2", 2, deleted=True),
                on(CHECKING_ID, "c3", 3, cleared=UNCLEARED),
            ],
            [CHECKING],
            [("Checking", ["c3"])],
            id="reconciled-and-deleted-transactions-are-left-out",
        ),
        pytest.param(
            [on(CHECKING_ID, "c1", 1)],
            [CHECKING, SAVINGS],
            [("Checking", ["c1"])],
            id="an-account-with-nothing-to-reconcile-is-omitted",
        ),
        pytest.param(
            [on(OLD_CARD_ID, "o1", 1), on(CHECKING_ID, "c1", 1)],
            [OLD_CARD, CHECKING],
            [("Checking", ["c1"])],
            id="a-closed-account-is-omitted",
        ),
        pytest.param(
            [on(CHECKING_ID, "c1", 1, cleared=RECONCILED)],
            [CHECKING],
            [],
            id="everything-reconciled",
        ),
    ],
)
def test_reconciliation_overview_groups_what_is_left_per_account(
    client: Client,
    ynab_api: YnabClientStub,
    transactions: list[TransactionDetail],
    accounts: list[Account],
    expected: list[tuple[str, list[str]]],
):
    ynab_holds(ynab_api, transactions, accounts)

    overview = reconciliation_overview(client, BUDGET_ID, since=None)

    assert [
        (group.account.name, [t.id for t in group.transactions]) for group in overview
    ] == expected


@pytest.mark.parametrize("since", [None, dt.date(2025, 5, 1)], ids=["everything", "a-date"])
def test_reconciliation_overview_asks_ynab_for_the_transactions_since_the_date(
    client: Client, ynab_api: YnabClientStub, since: dt.date | None
):
    ynab_holds(ynab_api, [], [CHECKING])

    reconciliation_overview(client, BUDGET_ID, since=since)

    call = ynab_api.api("transactions").get_transactions.call_args
    assert call.kwargs == {"plan_id": BUDGET_ID, "since_date": since}


def test_reconcile_patches_every_transaction_as_reconciled(
    client: Client, ynab_api: YnabClientStub
):
    transactions = [
        on(CHECKING_ID, "c1", 20),
        on(SAVINGS_ID, "s1", 2, cleared=UNCLEARED),
    ]

    latest = reconcile(client, BUDGET_ID, transactions)

    assert latest == dt.date(2025, 5, 20)
    call = ynab_api.api("transactions").update_transactions.call_args
    assert call.kwargs["plan_id"] == BUDGET_ID
    assert [(t.id, t.account_id, t.cleared) for t in call.kwargs["data"].transactions] == [
        ("c1", CHECKING_ID, RECONCILED),
        ("s1", SAVINGS_ID, RECONCILED),
    ]
    # The caller still holds the transactions as YNAB returned them
    assert transactions[1].cleared is UNCLEARED


def test_reconcile_with_nothing_selected_never_reaches_ynab(
    client: Client, ynab_api: YnabClientStub
):
    assert reconcile(client, BUDGET_ID, []) is None
    ynab_api.api("transactions").update_transactions.assert_not_called()


@pytest.mark.parametrize(
    ("locked", "remaining", "expected"),
    [
        pytest.param([5, 20], [], 20, id="everything-locked-the-latest-locked"),
        pytest.param([20], [9, 12], 9, id="rows-left-the-earliest-left"),
        pytest.param([5], [12], 12, id="left-rows-newer-than-locked-ones"),
        pytest.param([], [12], None, id="nothing-locked"),
    ],
)
def test_next_reconciliation_date(locked: list[int], remaining: list[int], expected: int | None):
    def may(days: list[int]) -> list[dt.date]:
        return [dt.date(2025, 5, day) for day in days]

    result = next_reconciliation_date(may(locked), may(remaining))

    assert result == (None if expected is None else dt.date(2025, 5, expected))

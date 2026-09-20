from __future__ import annotations

import pytest
from ynab import Account, TransactionClearedStatus, TransactionDetail

from tests.factories import AccountFactory, TransactionDetailFactory
from ynab_unlinked.commands.reconcile import build_choices

from .harness import CHECKING_ID, CLEARED, CREDIT_ID, SAVINGS_ID, UNCLEARED

CHECKING = AccountFactory(id=CHECKING_ID, name="Checking")
SAVINGS = AccountFactory(id=SAVINGS_ID, name="Savings")


@pytest.mark.parametrize(
    ("transactions", "accounts", "expected"),
    [
        pytest.param(
            [
                TransactionDetailFactory(id="t1", account_id=CHECKING_ID),
                TransactionDetailFactory(id="t2", account_id=SAVINGS_ID),
                TransactionDetailFactory(id="t3", account_id=CHECKING_ID),
            ],
            [CHECKING, SAVINGS],
            {"Checking": ["t1", "t3"], "Savings": ["t2"]},
            id="transactions-are-grouped-under-the-account-they-belong-to",
        ),
        pytest.param(
            [TransactionDetailFactory(id="t1", account_id=SAVINGS_ID)],
            [CHECKING, SAVINGS],
            {"Savings": ["t1"]},
            id="an-account-without-pending-transactions-is-not-offered",
        ),
        pytest.param(
            [
                TransactionDetailFactory(id="t1", account_id=CHECKING_ID),
                TransactionDetailFactory(id="t2", account_id=CREDIT_ID),
            ],
            [CHECKING],
            {"Checking": ["t1"]},
            id="a-transaction-of-an-unknown-account-is-dropped",
        ),
    ],
)
def test_build_choices_offers_one_group_per_account(
    transactions: list[TransactionDetail],
    accounts: list[Account],
    expected: dict[str, list[str]],
):
    choices = build_choices(transactions, accounts)

    assert {
        choice.title: [child.transaction.id for child in choice.choices] for choice in choices
    } == expected


def test_build_choices_names_each_choice_after_what_it_holds():
    transactions = [TransactionDetailFactory(id="t1", account_id=CHECKING_ID)]

    (checking,) = build_choices(transactions, [CHECKING])

    assert checking.id == f"account-{CHECKING_ID}"
    assert [child.id for child in checking.choices] == ["transaction-t1"]


@pytest.mark.parametrize(
    ("cleared", "selectable"),
    [
        pytest.param(CLEARED, True, id="a-cleared-transaction-follows-its-account"),
        pytest.param(UNCLEARED, False, id="an-uncleared-transaction-is-locked-out"),
    ],
)
def test_build_choices_keeps_uncleared_transactions_out_of_a_selected_account(
    cleared: TransactionClearedStatus, selectable: bool
):
    transactions = [TransactionDetailFactory(id="t1", account_id=CHECKING_ID, cleared=cleared)]

    (checking,) = build_choices(transactions, [CHECKING])
    checking.select()

    (child,) = checking.choices
    assert child.is_selected is selectable

from __future__ import annotations

import datetime as dt

import pytest

from tests.factories import AccountFactory, TransactionDetailFactory
from tests.helpers.types import CliRunner
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.config import ConfigV3

from .harness import (
    CHECKING_ID,
    RECONCILED,
    SAVINGS_ID,
    UNCLEARED,
    TuiStub,
    given_ynab_data,
    updates_sent,
)

pytestmark = pytest.mark.version("V3")

CHECKING = AccountFactory(id=CHECKING_ID, name="Checking")
SAVINGS = AccountFactory(id=SAVINGS_ID, name="Savings")


def test_reconcile_hands_the_app_the_pending_transactions_and_the_budget_formatter(
    yul: CliRunner, ynab: YnabClientStub, stored_config: ConfigV3, tui: TuiStub
):
    given_ynab_data(
        ynab,
        [
            TransactionDetailFactory(id="pending", account_id=CHECKING_ID),
            TransactionDetailFactory(id="done", account_id=CHECKING_ID, cleared=RECONCILED),
        ],
        [CHECKING],
    )

    result = yul("reconcile")

    assert result.exit_code == 0, result.output
    assert [child.transaction.id for choice in tui.choices for child in choice.choices] == [
        "pending"
    ]
    assert tui.config.budget == stored_config.budget
    assert tui.formatter.date_format == stored_config.budget.date_format


def test_reconcile_marks_every_cleared_transaction_of_a_selected_account(
    yul: CliRunner, ynab: YnabClientStub, stored_config: ConfigV3, tui: TuiStub
):
    given_ynab_data(
        ynab,
        [
            TransactionDetailFactory(id="checking-cleared", account_id=CHECKING_ID),
            TransactionDetailFactory(
                id="checking-uncleared", account_id=CHECKING_ID, cleared=UNCLEARED
            ),
            TransactionDetailFactory(id="savings-cleared", account_id=SAVINGS_ID),
        ],
        [CHECKING, SAVINGS],
    )

    result = yul("reconcile")

    assert result.exit_code == 0, result.output
    assert {(update.id, update.cleared) for update in updates_sent(ynab)} == {
        ("checking-cleared", RECONCILED),
        ("savings-cleared", RECONCILED),
    }


def test_reconcile_only_updates_the_transactions_picked_in_the_app(
    yul: CliRunner, ynab: YnabClientStub, stored_config: ConfigV3, tui: TuiStub
):
    given_ynab_data(
        ynab,
        [
            TransactionDetailFactory(id="t1", account_id=CHECKING_ID),
            TransactionDetailFactory(id="t2", account_id=CHECKING_ID),
            TransactionDetailFactory(id="t3", account_id=SAVINGS_ID, cleared=UNCLEARED),
        ],
        [CHECKING, SAVINGS],
    )
    tui.selected_ids = {"transaction-t2", "transaction-t3"}

    result = yul("reconcile")

    assert result.exit_code == 0, result.output
    updates = updates_sent(ynab)
    assert [update.id for update in updates] == ["t2", "t3"]
    assert {update.cleared for update in updates} == {RECONCILED}
    assert (
        ynab.transactions().update_transactions.call_args.kwargs["plan_id"]
        == stored_config.budget.id
    )


def test_reconcile_moves_the_checkpoint_to_the_latest_reconciled_transaction(
    yul: CliRunner, ynab: YnabClientStub, stored_config: ConfigV3, tui: TuiStub
):
    given_ynab_data(
        ynab,
        [
            TransactionDetailFactory(
                id="old", account_id=CHECKING_ID, var_date=dt.date(2025, 5, 2)
            ),
            TransactionDetailFactory(
                id="latest", account_id=CHECKING_ID, var_date=dt.date(2025, 5, 20)
            ),
        ],
        [CHECKING],
    )

    result = yul("reconcile")

    assert result.exit_code == 0, result.output
    # The grace period rewinds the checkpoint so late-cleared transactions are seen again
    assert ConfigV3.load().last_reconciliation_date == dt.date(2025, 5, 18)


@pytest.mark.parametrize(
    ("exit_code", "expected_output"),
    [
        pytest.param(1, "Bye!", id="the-user-cancelled-the-app"),
        pytest.param(2, "Nothing to reconcile.", id="the-user-selected-nothing"),
    ],
)
def test_reconcile_leaves_ynab_untouched_when_the_app_is_dismissed(
    exit_code: int,
    expected_output: str,
    yul: CliRunner,
    ynab: YnabClientStub,
    stored_config: ConfigV3,
    tui: TuiStub,
):
    given_ynab_data(ynab, [TransactionDetailFactory(account_id=CHECKING_ID)], [CHECKING])
    tui.exit_code = exit_code

    result = yul("reconcile")

    assert result.exit_code == 0, result.output
    assert expected_output in result.output
    ynab.transactions().update_transactions.assert_not_called()
    assert ConfigV3.load().last_reconciliation_date is None


def test_reconcile_does_nothing_when_the_confirmed_selection_is_empty(
    yul: CliRunner, ynab: YnabClientStub, stored_config: ConfigV3, tui: TuiStub
):
    given_ynab_data(
        ynab,
        [TransactionDetailFactory(account_id=CHECKING_ID, cleared=UNCLEARED)],
        [CHECKING],
    )

    result = yul("reconcile")

    assert result.exit_code == 0, result.output
    ynab.transactions().update_transactions.assert_not_called()
    assert ConfigV3.load().last_reconciliation_date is None

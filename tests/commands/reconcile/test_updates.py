from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from tests.factories import AccountFactory, TransactionDetailFactory
from tests.helpers.types import CliRunner
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.store import Store

from .harness import (
    CHECKING_ID,
    RECONCILED,
    SAVINGS_ID,
    UNCLEARED,
    TuiStub,
    given_ynab_data,
    updates_sent,
)

pytestmark = pytest.mark.version("V4")

CHECKING = AccountFactory(id=CHECKING_ID, name="Checking")
SAVINGS = AccountFactory(id=SAVINGS_ID, name="Savings")


def test_reconcile_hands_the_app_the_pending_transactions_and_the_budget_formatter(
    yul: CliRunner, ynab: YnabClientStub, stored_config: LatestConfig, tui: TuiStub
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
    yul: CliRunner, ynab: YnabClientStub, stored_config: LatestConfig, tui: TuiStub
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
    yul: CliRunner, ynab: YnabClientStub, stored_config: LatestConfig, tui: TuiStub
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
    yul: CliRunner, ynab: YnabClientStub, stored_config: LatestConfig, tui: TuiStub
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
    # Only `--buffer` rewinds the next scope; the checkpoint itself is not moved back
    assert LatestConfig.load().last_reconciliation_date == dt.date(2025, 5, 20)


def test_reconcile_keeps_the_checkpoint_before_what_was_left_unreconciled(
    yul: CliRunner, ynab: YnabClientStub, stored_config: LatestConfig, tui: TuiStub
):
    given_ynab_data(
        ynab,
        [
            TransactionDetailFactory(
                id="left", account_id=CHECKING_ID, var_date=dt.date(2025, 5, 2)
            ),
            TransactionDetailFactory(
                id="pending", account_id=SAVINGS_ID, var_date=dt.date(2025, 5, 6), cleared=UNCLEARED
            ),
            TransactionDetailFactory(
                id="latest", account_id=CHECKING_ID, var_date=dt.date(2025, 5, 20)
            ),
        ],
        [CHECKING, SAVINGS],
    )
    tui.selected_ids = {"transaction-latest"}

    result = yul("reconcile")

    assert result.exit_code == 0, result.output
    assert [update.id for update in updates_sent(ynab)] == ["latest"]
    assert LatestConfig.load().last_reconciliation_date == dt.date(2025, 5, 2)


def test_reconcile_is_noted_in_the_activity_log_the_app_reads(
    yul: CliRunner,
    ynab: YnabClientStub,
    stored_config: LatestConfig,
    tui: TuiStub,
    store_file: Path,
):
    given_ynab_data(
        ynab,
        [
            TransactionDetailFactory(id="c1", account_id=CHECKING_ID),
            TransactionDetailFactory(id="c2", account_id=CHECKING_ID),
            TransactionDetailFactory(id="s1", account_id=SAVINGS_ID, cleared=UNCLEARED),
        ],
        [CHECKING, SAVINGS],
    )

    result = yul("reconcile")

    assert result.exit_code == 0, result.output
    [entry] = Store(store_file).activity(stored_config.budget.id)
    assert (entry.kind, entry.message) == ("reconcile", "Reconciled 2 transactions in 1 account")
    assert entry.details == {
        "count": 2,
        "accounts": [{"id": str(CHECKING_ID), "name": "Checking", "count": 2}],
    }


def test_reconcile_with_a_broken_store_still_succeeds(
    yul: CliRunner,
    ynab: YnabClientStub,
    stored_config: LatestConfig,
    tui: TuiStub,
    store_file: Path,
):
    store_file.parent.mkdir(parents=True)
    store_file.write_text("this is not a database")
    given_ynab_data(ynab, [TransactionDetailFactory(id="c1", account_id=CHECKING_ID)], [CHECKING])

    result = yul("reconcile")

    assert result.exit_code == 0, result.output
    assert [update.id for update in updates_sent(ynab)] == ["c1"]
    assert "could not note it in its activity log" in result.output
    assert "Reconciliation done!" in result.output


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
    stored_config: LatestConfig,
    tui: TuiStub,
):
    given_ynab_data(ynab, [TransactionDetailFactory(account_id=CHECKING_ID)], [CHECKING])
    tui.exit_code = exit_code

    result = yul("reconcile")

    assert result.exit_code == 0, result.output
    assert expected_output in result.output
    ynab.transactions().update_transactions.assert_not_called()
    assert LatestConfig.load().last_reconciliation_date is None


def test_reconcile_does_nothing_when_the_confirmed_selection_is_empty(
    yul: CliRunner, ynab: YnabClientStub, stored_config: LatestConfig, tui: TuiStub
):
    given_ynab_data(
        ynab,
        [TransactionDetailFactory(account_id=CHECKING_ID, cleared=UNCLEARED)],
        [CHECKING],
    )

    result = yul("reconcile")

    assert result.exit_code == 0, result.output
    ynab.transactions().update_transactions.assert_not_called()
    assert LatestConfig.load().last_reconciliation_date is None

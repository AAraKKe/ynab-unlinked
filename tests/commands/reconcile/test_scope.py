from __future__ import annotations

import datetime as dt

import pytest
from ynab import TransactionDetail

from tests.factories import AccountFactory, TransactionDetailFactory
from tests.helpers.types import CliRunner
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.config import ConfigV3

from .harness import CHECKING_ID, RECONCILED, TuiStub, given_ynab_data

pytestmark = pytest.mark.version("V3")

CHECKING = AccountFactory(id=CHECKING_ID, name="Checking")


@pytest.mark.parametrize(
    "transactions",
    [
        pytest.param([], id="ynab-returned-no-transactions"),
        pytest.param(
            [TransactionDetailFactory(id="t1", account_id=CHECKING_ID, cleared=RECONCILED)],
            id="every-transaction-is-already-reconciled",
        ),
    ],
)
def test_reconcile_stops_when_there_is_nothing_left_to_reconcile(
    transactions: list[TransactionDetail],
    yul: CliRunner,
    ynab: YnabClientStub,
    stored_config: ConfigV3,
    tui: TuiStub,
):
    given_ynab_data(ynab, transactions, [CHECKING])

    result = yul("reconcile")

    assert result.exit_code == 0, result.output
    assert "already reconciled" in result.output
    tui.app_class.assert_not_called()
    ynab.transactions().update_transactions.assert_not_called()


@pytest.mark.parametrize(
    ("command", "last_reconciliation_date", "expected_since_date"),
    [
        pytest.param(
            "reconcile", None, None, id="without-a-checkpoint-every-transaction-is-fetched"
        ),
        pytest.param(
            "reconcile",
            dt.date(2025, 5, 10),
            dt.date(2025, 5, 3),
            id="the-checkpoint-is-rewound-by-the-default-buffer-of-seven-days",
        ),
        pytest.param(
            "reconcile -b 0",
            dt.date(2025, 5, 10),
            dt.date(2025, 5, 10),
            id="a-zero-buffer-starts-right-at-the-checkpoint",
        ),
        pytest.param(
            "reconcile --buffer 30",
            dt.date(2025, 5, 10),
            dt.date(2025, 4, 10),
            id="a-longer-buffer-reaches-further-back",
        ),
        pytest.param(
            "reconcile --all",
            dt.date(2025, 5, 10),
            None,
            id="all-ignores-the-checkpoint-altogether",
        ),
    ],
)
def test_reconcile_asks_ynab_for_transactions_since_the_buffered_checkpoint(
    command: str,
    last_reconciliation_date: dt.date | None,
    expected_since_date: dt.date | None,
    yul: CliRunner,
    ynab: YnabClientStub,
    stored_config: ConfigV3,
    tui: TuiStub,
):
    stored_config.last_reconciliation_date = last_reconciliation_date
    stored_config.save()
    given_ynab_data(ynab, [], [CHECKING])

    result = yul(command)

    assert result.exit_code == 0, result.output
    assert ynab.transactions().get_transactions.call_args.kwargs["since_date"] == (
        expected_since_date
    )

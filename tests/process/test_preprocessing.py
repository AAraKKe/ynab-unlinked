import datetime as dt

import pytest

from tests.factories import TransactionFactory
from ynab_unlinked.config.models.shared import Checkpoint
from ynab_unlinked.process import (
    add_counter_to_existing_transactions,
    add_past_to_transactions,
    filter_transactions,
)

CHECKPOINT = Checkpoint(latest_date_processed=dt.date(2025, 5, 10), latest_transaction_hash=0)


@pytest.mark.parametrize(
    ("date", "expected_past"),
    [
        pytest.param(dt.date(2025, 5, 8), True, id="well before the checkpoint"),
        pytest.param(dt.date(2025, 5, 11), True, id="inside the two day grace period"),
        pytest.param(dt.date(2025, 5, 12), False, id="on the first day after the grace period"),
        pytest.param(dt.date(2025, 5, 13), False, id="after the grace period"),
    ],
)
def test_transactions_up_to_the_checkpoint_grace_period_are_marked_past(
    date: dt.date, expected_past: bool
):
    transactions = [TransactionFactory(date=date)]

    add_past_to_transactions(transactions, CHECKPOINT)

    assert transactions[0].past is expected_past


def test_no_transaction_is_past_without_a_checkpoint():
    transactions = [
        TransactionFactory(date=dt.date(2025, 5, 1)),
        TransactionFactory(date=dt.date(2025, 5, 30)),
    ]

    add_past_to_transactions(transactions, None)

    assert not any(t.past for t in transactions)


def test_repeated_transactions_get_a_unique_import_id():
    transactions = [
        TransactionFactory(date=dt.date(2025, 5, 12)),
        TransactionFactory(date=dt.date(2025, 5, 12)),
        TransactionFactory(date=dt.date(2025, 5, 12)),
        TransactionFactory(date=dt.date(2025, 5, 13)),
    ]

    add_counter_to_existing_transactions(transactions)

    assert [t.counter for t in transactions] == [0, 1, 2, 0]
    assert len({t.id for t in transactions}) == 4


def test_transactions_older_than_the_checkpoint_are_still_processed():
    # Checkpoint filtering is deliberately disabled so that late-cleared transactions
    # from an overlapping export are not dropped
    transactions = [
        TransactionFactory(date=dt.date(2025, 5, 1)),
        TransactionFactory(date=dt.date(2025, 5, 14)),
    ]

    assert list(filter_transactions(transactions, CHECKPOINT)) == transactions

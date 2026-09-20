from __future__ import annotations

from unittest.mock import MagicMock

from tests.factories import TransactionFactory
from tests.utils.builders import column, only_table, styles
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.utils import MAX_PAST_TRANSACTIONS_SHOWN, display_transaction_table


def test_transaction_table_splits_the_amount_into_inflow_and_outflow(
    printed: MagicMock, formatter: Formatter
):
    display_transaction_table(
        [
            TransactionFactory(payee="Salary", amount=1500.0),
            TransactionFactory(payee="Coffee", amount=-12.34),
        ],
        formatter,
    )

    table = only_table(printed)
    assert column(table, "Date") == ["15/05/2025", "15/05/2025"]
    assert column(table, "Inflow") == ["1,500.00€", ""]
    assert column(table, "Outflow") == ["", "-12.34€"]


def test_transaction_table_dims_already_processed_transactions(
    printed: MagicMock, formatter: Formatter
):
    display_transaction_table(
        [TransactionFactory(payee="Old", past=True), TransactionFactory(payee="New")],
        formatter,
    )

    assert styles(only_table(printed)) == ["gray37", "default"]


def test_transaction_table_stops_listing_past_transactions_at_the_cutoff(
    printed: MagicMock, formatter: Formatter
):
    transactions = [
        TransactionFactory(payee=f"Past {index}", past=True)
        for index in range(MAX_PAST_TRANSACTIONS_SHOWN + 2)
    ]
    transactions.append(TransactionFactory(payee="Recent"))

    display_transaction_table(transactions, formatter)

    shown = column(only_table(printed), "Payee")
    assert shown == [f"Past {index}" for index in range(MAX_PAST_TRANSACTIONS_SHOWN - 1)] + ["..."]


def test_transaction_table_of_an_empty_extract_has_no_rows(
    printed: MagicMock, formatter: Formatter
):
    display_transaction_table([], formatter)

    assert only_table(printed).row_count == 0

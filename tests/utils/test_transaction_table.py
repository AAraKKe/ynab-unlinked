from __future__ import annotations

from unittest.mock import MagicMock

from tests.factories import TransactionFactory
from tests.utils.builders import column, only_table
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.utils import display_transaction_table


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


def test_transaction_table_lists_every_row_of_the_export(printed: MagicMock, formatter: Formatter):
    transactions = [TransactionFactory(payee=f"Payee {index}") for index in range(6)]

    display_transaction_table(transactions, formatter)

    assert column(only_table(printed), "Payee") == [f"Payee {index}" for index in range(6)]


def test_transaction_table_of_an_empty_extract_has_no_rows(
    printed: MagicMock, formatter: Formatter
):
    display_transaction_table([], formatter)

    assert only_table(printed).row_count == 0

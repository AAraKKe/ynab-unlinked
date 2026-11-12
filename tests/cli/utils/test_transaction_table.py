from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from tests.cli.utils.builders import cell_styles, column, only_table
from tests.factories import ImportRowFactory, TransactionFactory
from ynab_unlinked.cli.utils import display_import_table, display_transaction_table
from ynab_unlinked.formatter import Formatter


def test_transaction_table_shows_money_in_with_a_plus_in_green(
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
    assert column(table, "Amount") == ["+1,500.00€", "-12.34€"]
    assert cell_styles(table, "Amount") == ["green", ""]


def test_transaction_table_lists_every_row_of_the_export(printed: MagicMock, formatter: Formatter):
    transactions = [TransactionFactory(payee=f"Payee {index}") for index in range(6)]

    display_transaction_table(transactions, formatter)

    assert column(only_table(printed), "Payee") == [f"Payee {index}" for index in range(6)]


def test_transaction_table_of_an_empty_extract_has_no_rows(
    printed: MagicMock, formatter: Formatter
):
    display_transaction_table([], formatter)

    assert only_table(printed).row_count == 0


@pytest.mark.parametrize(
    "show",
    [
        pytest.param(
            lambda payees, formatter: display_transaction_table(
                [TransactionFactory(payee=payee) for payee in payees], formatter
            ),
            id="the-transactions-of-the-export",
        ),
        pytest.param(
            lambda payees, formatter: display_import_table(
                [ImportRowFactory(payee=payee) for payee in payees], formatter
            ),
            id="the-transactions-to-import",
        ),
    ],
)
def test_a_payee_with_brackets_is_shown_as_written(printed: MagicMock, formatter: Formatter, show):
    # Read as markup, "A [/] B" crashed `yul load` and "[red]x" lost its text
    show(["A [/] B", "[red]x"], formatter)

    output = io.StringIO()
    Console(file=output, width=200).print(only_table(printed))
    assert "A [/] B" in output.getvalue()
    assert "[red]x" in output.getvalue()

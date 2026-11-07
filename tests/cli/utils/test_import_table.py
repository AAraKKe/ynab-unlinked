from __future__ import annotations

from unittest.mock import MagicMock

from tests.cli.utils.builders import column, only_table, styles
from tests.factories import ImportRowFactory
from ynab_unlinked.cli.utils import display_import_table
from ynab_unlinked.formatter import Formatter


def test_import_table_dims_the_rows_ynab_already_holds(printed: MagicMock, formatter: Formatter):
    rows = [
        ImportRowFactory(payee="Already there", amount=-10.0, already_imported=True),
        ImportRowFactory(payee="Brand new", amount=-20.0),
    ]

    display_import_table(rows, formatter)

    table = only_table(printed)
    assert column(table, "Payee") == ["Already there", "Brand new"]
    assert styles(table) == ["gray37", "green"]


def test_import_table_splits_the_amount_into_inflow_and_outflow(
    printed: MagicMock, formatter: Formatter
):
    rows = [
        ImportRowFactory(payee="Salary", amount=1500.0),
        ImportRowFactory(payee="Coffee", amount=-12.34),
    ]

    display_import_table(rows, formatter)

    table = only_table(printed)
    assert column(table, "Inflow") == ["1,500.00€", ""]
    assert column(table, "Outflow") == ["", "-12.34€"]


def test_import_table_is_not_printed_when_there_is_nothing_to_import(
    printed: MagicMock, formatter: Formatter
):
    display_import_table([], formatter)

    printed.assert_not_called()

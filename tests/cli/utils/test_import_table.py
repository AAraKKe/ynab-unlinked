from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

from tests.cli.utils.builders import column, only_table, styles
from tests.factories import ImportRowFactory
from ynab_unlinked.cli.utils import display_import_table
from ynab_unlinked.core.importing import Twin
from ynab_unlinked.formatter import Formatter


def test_import_table_tells_each_row_status_apart(printed: MagicMock, formatter: Formatter):
    rows = [
        ImportRowFactory(payee="Already there", amount=-10.0, already_imported=True),
        ImportRowFactory(payee="Brand new", amount=-20.0),
        ImportRowFactory(
            payee="Maya mobile ltd", amount=-18.38, already_imported=True, matched=True
        ),
        ImportRowFactory(payee="Left out in the app", amount=-30.0, excluded=True),
        ImportRowFactory(
            payee="Mercadona Galeria", amount=-53.01, twin=Twin(dt.date(2025, 5, 14), "Mercadona")
        ),
    ]

    display_import_table(rows, formatter)

    table = only_table(printed)
    assert column(table, "Payee") == [
        "Already there",
        "Brand new",
        "Maya mobile ltd",
        "Left out in the app",
        "Mercadona Galeria",
    ]
    assert column(table, "Status") == [
        "in YNAB",
        "new",
        "matched in YNAB",
        "left out",
        "may be in YNAB",
    ]
    assert styles(table) == ["gray37", "green", "gray37", "strike gray37", "yellow"]


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

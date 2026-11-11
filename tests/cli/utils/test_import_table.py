from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

import pytest

from tests.cli.utils.builders import cell_styles, column, only_table, styles
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
    # Only the tag carries the colour of its status, as in the app: a green row would hide
    # the green of an inflow. Rows that need nothing from the user step back.
    assert cell_styles(table, "Status") == ["gray37", "green", "gray37", "gray37", "yellow"]
    assert styles(table) == ["gray37", "None", "gray37", "strike gray37", "None"]


@pytest.mark.parametrize(
    "already_imported, inflow_style",
    [
        pytest.param(False, "green", id="new-row"),
        pytest.param(True, "dim green", id="dimmed-row"),
    ],
)
def test_import_table_shows_money_in_with_a_plus_in_green(
    printed: MagicMock, formatter: Formatter, already_imported: bool, inflow_style: str
):
    rows = [
        ImportRowFactory(payee="Salary", amount=1500.0, already_imported=already_imported),
        ImportRowFactory(payee="Coffee", amount=-12.34, already_imported=already_imported),
    ]

    display_import_table(rows, formatter)

    table = only_table(printed)
    assert column(table, "Amount") == ["+1,500.00€", "-12.34€"]
    assert cell_styles(table, "Amount") == [inflow_style, ""]


def test_import_table_is_not_printed_when_there_is_nothing_to_import(
    printed: MagicMock, formatter: Formatter
):
    display_import_table([], formatter)

    printed.assert_not_called()

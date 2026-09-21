from __future__ import annotations

from unittest.mock import MagicMock

from tests.factories import TransactionFactory
from tests.utils.builders import column, only_table, styles
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.models import assign_import_ids
from ynab_unlinked.utils import display_import_table


def test_import_table_dims_the_rows_ynab_already_holds(printed: MagicMock, formatter: Formatter):
    pending = assign_import_ids(
        [
            TransactionFactory(payee="Already there", amount=-10.0),
            TransactionFactory(payee="Brand new", amount=-20.0),
        ]
    )

    display_import_table(pending, {pending[0].import_id}, formatter)

    table = only_table(printed)
    assert column(table, "Payee") == ["Already there", "Brand new"]
    assert styles(table) == ["gray37", "green"]


def test_import_table_splits_the_amount_into_inflow_and_outflow(
    printed: MagicMock, formatter: Formatter
):
    pending = assign_import_ids(
        [
            TransactionFactory(payee="Salary", amount=1500.0),
            TransactionFactory(payee="Coffee", amount=-12.34),
        ]
    )

    display_import_table(pending, set(), formatter)

    table = only_table(printed)
    assert column(table, "Inflow") == ["1,500.00€", ""]
    assert column(table, "Outflow") == ["", "-12.34€"]


def test_import_table_is_not_printed_when_there_is_nothing_to_import(
    printed: MagicMock, formatter: Formatter
):
    display_import_table([], set(), formatter)

    printed.assert_not_called()

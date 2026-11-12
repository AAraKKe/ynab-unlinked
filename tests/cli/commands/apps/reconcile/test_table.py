from __future__ import annotations

from rich.text import Text
from textual.color import Color
from textual.pilot import Pilot
from textual.widgets import DataTable

from tests.factories import AccountFactory, TransactionDetailFactory
from ynab_unlinked.cli.commands.apps.reconcile import POSITIVE_COLOR
from ynab_unlinked.cli.commands.reconcile import build_choices

from .harness import (
    CHECKING_ID,
    CLEARED,
    UNCLEARED,
    cleared_column,
    quit_app,
    run_app,
    single_account,
    tables,
    toggle_account,
)


def test_table_shows_the_status_each_transaction_will_end_up_with():
    statuses: list[list[str]] = []

    async def scenario(pilot: Pilot[int]):
        statuses.append(cleared_column(pilot))
        await toggle_account(pilot)
        statuses.append(cleared_column(pilot))
        await quit_app(pilot)

    run_app(single_account(CLEARED, UNCLEARED), scenario)

    assert statuses == [["🔒 Reconciled", "Uncleared"], ["✅ Cleared", "Uncleared"]]


def test_a_payee_with_brackets_is_shown_as_written():
    # Read as markup, "A [/] B" crashed the app and "[red]x" lost its text
    choices = build_choices(
        [
            TransactionDetailFactory(id=f"t-{index}", account_id=CHECKING_ID, payee_name=payee)
            for index, payee in enumerate(["A [/] B", "[red]x"])
        ],
        [AccountFactory(id=CHECKING_ID, name="Checking")],
    )
    payees: list[str] = []

    async def scenario(pilot: Pilot[int]):
        table = tables(pilot)[0].query_one(DataTable)
        payees.extend(str(table.get_row_at(row)[1]) for row in range(table.row_count))
        await quit_app(pilot)

    run_app(choices, scenario)

    assert sorted(payees) == ["A [/] B", "[red]x"]


def test_money_in_shows_with_a_plus_in_the_colour_of_a_positive_balance():
    choices = build_choices(
        [
            TransactionDetailFactory(id="refund", account_id=CHECKING_ID, amount=24_500),
            TransactionDetailFactory(id="rent", account_id=CHECKING_ID, amount=-1_100_000),
        ],
        [AccountFactory(id=CHECKING_ID, name="Checking")],
    )
    amounts: dict[str, Text] = {}

    async def scenario(pilot: Pilot[int]):
        table = tables(pilot)[0].query_one(DataTable)
        for row in range(table.row_count):
            cell = table.get_row_at(row)[2]
            assert isinstance(cell, Text)
            amounts[cell.plain] = cell
        await quit_app(pilot)

    run_app(choices, scenario)

    assert sorted(amounts) == ["+24.50€", "-1,100.00€"]
    positive = Color.parse(POSITIVE_COLOR).rich_color
    assert [span.style.color for span in amounts["+24.50€"].spans] == [positive]
    assert amounts["-1,100.00€"].spans == []

from __future__ import annotations

import pytest
from textual.pilot import Pilot
from textual.widgets import Static
from ynab import TransactionClearedStatus

from ynab_unlinked.commands.apps.reconcile import ReconcileModal

from .harness import (
    CLEARED,
    UNCLEARED,
    Scenario,
    press_button,
    quit_app,
    run_app,
    selection,
    single_account,
)


async def cancel(pilot: Pilot[int]):
    await press_button(pilot, "#cancel-button")


async def confirm_reconciliation(pilot: Pilot[int]):
    await press_button(pilot, "#reconcile-button")
    await press_button(pilot, "#button-yes")


async def reconcile_without_a_selection(pilot: Pilot[int]):
    await press_button(pilot, "#uncheck-all")
    await press_button(pilot, "#reconcile-button")


@pytest.mark.parametrize(
    ("scenario", "expected_exit_value"),
    [
        pytest.param(confirm_reconciliation, 0, id="confirming-asks-the-command-to-reconcile"),
        pytest.param(cancel, 1, id="the-cancel-button-aborts"),
        pytest.param(quit_app, 2, id="the-quit-binding-leaves-without-reconciling"),
        pytest.param(
            reconcile_without_a_selection, 2, id="reconciling-nothing-is-the-same-as-leaving"
        ),
    ],
)
def test_exit_value_tells_the_command_what_to_do(scenario: Scenario, expected_exit_value: int):
    assert run_app(single_account(CLEARED, CLEARED), scenario) == expected_exit_value


def test_reconciling_without_a_selection_skips_the_confirmation():
    screens: list[str] = []

    async def scenario(pilot: Pilot[int]):
        await reconcile_without_a_selection(pilot)
        screens.append(type(pilot.app.screen).__name__)

    run_app(single_account(CLEARED), scenario)

    assert ReconcileModal.__name__ not in screens


def test_declining_the_confirmation_returns_to_the_app_with_the_selection_intact():
    choices = single_account(CLEARED, CLEARED)
    still_running: list[bool] = []

    async def scenario(pilot: Pilot[int]):
        await press_button(pilot, "#reconcile-button")
        await press_button(pilot, "#button-no")
        still_running.append(pilot.app.is_running)
        await quit_app(pilot)

    assert run_app(choices, scenario) == 2
    assert still_running == [True]
    assert selection(choices) == [True, True]


@pytest.mark.parametrize(
    ("statuses", "expected_counter"),
    [
        pytest.param(
            [CLEARED, CLEARED], "All transactions", id="the-whole-account-is-being-reconciled"
        ),
        pytest.param(
            [CLEARED, CLEARED, UNCLEARED],
            "2 transactions",
            id="uncleared-transactions-are-left-behind",
        ),
        pytest.param(
            [CLEARED, UNCLEARED],
            "1 transaction",
            id="a-single-transaction-is-not-pluralised",
        ),
    ],
)
def test_confirmation_lists_how_many_transactions_each_account_contributes(
    statuses: list[TransactionClearedStatus], expected_counter: str
):
    summaries: list[str] = []

    async def scenario(pilot: Pilot[int]):
        await press_button(pilot, "#reconcile-button")
        summaries.append(str(pilot.app.screen.query_one("#accounts-list", Static).content))
        await press_button(pilot, "#button-no")
        await quit_app(pilot)

    run_app(single_account(*statuses), scenario)

    assert summaries == [f"- Checking ({expected_counter})"]

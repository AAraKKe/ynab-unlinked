from __future__ import annotations

import pytest
from textual.pilot import Pilot
from textual.widgets import Button
from ynab import TransactionClearedStatus

from .harness import (
    CHECKING_ID,
    CLEARED,
    RECONCILED,
    SAVINGS_ID,
    UNCLEARED,
    Scenario,
    choices_for,
    press_button,
    quit_app,
    run_app,
    select_row,
    selection,
    single_account,
    toggle_account,
    toggle_include_uncleared,
)


async def do_nothing(pilot: Pilot[int]): ...


async def release_account(pilot: Pilot[int]):
    await toggle_account(pilot)


async def release_account_and_pick_second_row(pilot: Pilot[int]):
    await toggle_account(pilot)
    await select_row(pilot, row=1)


async def release_account_and_pick_first_row(pilot: Pilot[int]):
    await toggle_account(pilot)
    await select_row(pilot, row=0)


async def release_account_and_pick_first_row_twice(pilot: Pilot[int]):
    await release_account_and_pick_first_row(pilot)
    await select_row(pilot, row=0)


async def include_uncleared(pilot: Pilot[int]):
    await toggle_include_uncleared(pilot)


async def include_uncleared_and_change_your_mind(pilot: Pilot[int]):
    await toggle_include_uncleared(pilot)
    await toggle_include_uncleared(pilot)


async def release_account_include_uncleared_and_pick_first_row(pilot: Pilot[int]):
    await toggle_account(pilot)
    await toggle_include_uncleared(pilot)
    await select_row(pilot, row=0)


@pytest.mark.parametrize(
    ("statuses", "scenario", "expected"),
    [
        pytest.param(
            [CLEARED, UNCLEARED, RECONCILED],
            do_nothing,
            [True, False, True],
            id="an-account-starts-selected-except-for-its-uncleared-transactions",
        ),
        pytest.param(
            [CLEARED, CLEARED],
            release_account,
            [False, False],
            id="releasing-an-account-releases-all-of-its-transactions",
        ),
        pytest.param(
            [CLEARED, CLEARED],
            release_account_and_pick_second_row,
            [False, True],
            id="a-single-transaction-can-be-picked-once-the-account-is-released",
        ),
        pytest.param(
            [CLEARED],
            release_account_and_pick_first_row_twice,
            [False],
            id="picking-the-same-transaction-twice-leaves-it-unselected",
        ),
        pytest.param(
            [UNCLEARED],
            release_account_and_pick_first_row,
            [False],
            id="an-uncleared-transaction-cannot-be-picked-on-its-own",
        ),
        pytest.param(
            [UNCLEARED],
            release_account_include_uncleared_and_pick_first_row,
            [True],
            id="include-uncleared-unlocks-an-uncleared-transaction",
        ),
        pytest.param(
            [CLEARED, UNCLEARED],
            include_uncleared,
            [True, True],
            id="include-uncleared-pulls-uncleared-transactions-into-a-selected-account",
        ),
        pytest.param(
            [CLEARED, UNCLEARED],
            include_uncleared_and_change_your_mind,
            [True, False],
            id="switching-include-uncleared-back-off-locks-uncleared-transactions-again",
        ),
    ],
)
def test_selection_follows_what_the_user_picked(
    statuses: list[TransactionClearedStatus], scenario: Scenario, expected: list[bool]
):
    choices = single_account(*statuses)

    async def scenario_then_quit(pilot: Pilot[int]):
        await scenario(pilot)
        await quit_app(pilot)

    run_app(choices, scenario_then_quit)

    assert selection(choices) == expected


def test_releasing_one_account_leaves_the_others_selected():
    choices = choices_for(
        (CHECKING_ID, "Checking", [CLEARED, CLEARED]),
        (SAVINGS_ID, "Savings", [CLEARED]),
    )

    async def scenario(pilot: Pilot[int]):
        await toggle_account(pilot, index=0)
        await quit_app(pilot)

    run_app(choices, scenario)

    assert selection(choices) == [False, False, True]


def test_deselect_all_button_releases_every_account_and_flips_back():
    choices = choices_for(
        (CHECKING_ID, "Checking", [CLEARED]),
        (SAVINGS_ID, "Savings", [CLEARED]),
    )
    labels: list[str] = []
    after_deselect: list[list[bool]] = []

    async def scenario(pilot: Pilot[int]):
        await press_button(pilot, "#uncheck-all")
        labels.append(str(pilot.app.query_one("#uncheck-all", Button).label))
        after_deselect.append(selection(choices))

        await press_button(pilot, "#uncheck-all")
        labels.append(str(pilot.app.query_one("#uncheck-all", Button).label))
        await quit_app(pilot)

    run_app(choices, scenario)

    assert labels == ["Select All", "Deselect All"]
    assert after_deselect == [[False, False]]
    assert selection(choices) == [True, True]

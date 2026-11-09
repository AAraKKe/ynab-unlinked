"""Shared plumbing to drive the reconcile Textual app from sync tests."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from unittest import mock

import textual._wait
from textual.pilot import Pilot
from textual.widgets import Button, DataTable, Switch
from ynab import TransactionClearedStatus

from tests.factories import AccountFactory, CurrencyFormatFactory, TransactionDetailFactory
from ynab_unlinked.cli.choices import Choice
from ynab_unlinked.cli.commands.apps.reconcile import AccountTable, Reconcile
from ynab_unlinked.cli.commands.reconcile import build_choices
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.config.models.v2 import Budget
from ynab_unlinked.formatter import Formatter

CHECKING_ID = uuid.UUID("00000000-0000-0000-0000-00000000000a")
SAVINGS_ID = uuid.UUID("00000000-0000-0000-0000-00000000000b")

CLEARED = TransactionClearedStatus.CLEARED
UNCLEARED = TransactionClearedStatus.UNCLEARED
RECONCILED = TransactionClearedStatus.RECONCILED

# Wide enough that every button and table row is on screen and clickable.
TERMINAL_SIZE = (160, 60)

CURRENCY_FORMAT = CurrencyFormatFactory()
CONFIG = LatestConfig(
    api_key="an-api-key",
    budget=Budget(
        id="a-budget", name="A Budget", date_format="DD/MM/YYYY", currency_format=CURRENCY_FORMAT
    ),
)
FORMATTER = Formatter(date_format="DD/MM/YYYY", currency_format=CURRENCY_FORMAT)

Scenario = Callable[[Pilot[int]], Awaitable[None]]


def choices_for(*accounts: tuple[uuid.UUID, str, list[TransactionClearedStatus]]) -> list[Choice]:
    """Build the same choice tree the reconcile command feeds the app."""
    return build_choices(
        [
            TransactionDetailFactory(
                id=f"{name.lower()}-{index}", account_id=account_id, cleared=status
            )
            for account_id, name, statuses in accounts
            for index, status in enumerate(statuses)
        ],
        [AccountFactory(id=account_id, name=name) for account_id, name, _ in accounts],
    )


def single_account(*statuses: TransactionClearedStatus) -> list[Choice]:
    return choices_for((CHECKING_ID, "Checking", list(statuses)))


def run_app(choices: list[Choice], scenario: Scenario) -> int | None:
    """Drive the app through a scenario and return the value it exited with.

    pytest-asyncio is not a dependency, so every scenario is driven from a sync test.
    """
    app = Reconcile(CONFIG, choices, formatter=FORMATTER)
    # A switch slides for 300 ms and the pilot waits for the app to settle after each click
    app.animation_level = "none"

    async def drive():
        async with app.run_test(size=TERMINAL_SIZE) as pilot:
            await scenario(pilot)
            await pilot.pause()

    # Every pilot step ends waiting for the app to go idle: it sleeps 20 ms at a time until
    # one sleep used under 1 ms of CPU, so even an idle app costs 20 ms a step and a scenario
    # has dozens. Same ratio in 5 ms steps: a third of the time. Before that wait the pilot
    # makes every widget handle its pending messages, which is what the scenarios rely on.
    with mock.patch.multiple(textual._wait, SLEEP_GRANULARITY=0.005, SLEEP_IDLE=0.00025):
        asyncio.run(drive())
    return app.return_value


def selection(choices: list[Choice]) -> list[bool]:
    return [child.is_selected for choice in choices for child in choice.choices]


def tables(pilot: Pilot[int]) -> list[AccountTable]:
    return list(pilot.app.query(AccountTable))


def cleared_column(pilot: Pilot[int], table_index: int = 0) -> list[str]:
    table = tables(pilot)[table_index].query_one(DataTable)
    return [table.get_row_at(row)[-1] for row in range(table.row_count)]


async def press_button(pilot: Pilot[int], selector: str):
    button = pilot.app.screen.query_one(selector, Button)
    # Textual ignores a click while the press animation is still running
    button.active_effect_duration = 0
    await pilot.click(selector)
    await pilot.pause()


async def toggle_account(pilot: Pilot[int], index: int = 0):
    await pilot.click(tables(pilot)[index].query_one(Switch))
    await pilot.pause()


async def toggle_include_uncleared(pilot: Pilot[int]):
    await pilot.click("#uncleared-switch")
    await pilot.pause()


async def select_row(pilot: Pilot[int], row: int, table_index: int = 0):
    tables(pilot)[table_index].query_one(DataTable).focus()
    await pilot.press(*["down"] * row, "enter")
    await pilot.pause()


async def quit_app(pilot: Pilot[int]):
    await pilot.press("ctrl+q")

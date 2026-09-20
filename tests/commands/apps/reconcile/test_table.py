from __future__ import annotations

from textual.pilot import Pilot

from .harness import (
    CLEARED,
    UNCLEARED,
    cleared_column,
    quit_app,
    run_app,
    single_account,
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

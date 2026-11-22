"""Done: the rows YNAB did not take because it had their import id (a transaction imported and
deleted in YNAB since), and leaving them out of later imports from there."""

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from tests.helpers.statements import bbva_sheet, write_xls
from tests.helpers.web import User
from tests.helpers.ynab_api import YnabClientStub
from tests.web.views.test_import import (  # noqa: F401 (fixtures)
    BUDGET_ID,
    MAXIMA,
    ORO,
    SABADELL,
    accounts,
    created,
    drop,
    import_ids,
    show_every_row,
    ynab,
)
from ynab_unlinked.store import Store
from ynab_unlinked.web.state import state

# Sabadell goes to Oro and BBVA to Maxima; YNAB holds none of their rows
pytestmark = [pytest.mark.version("V4"), pytest.mark.usefixtures("accounts", "ynab")]


async def import_all(user: User, *paths: Path, created: str) -> None:
    await drop(user, *paths)
    await user.should_see(marker="review", retries=30)
    for index in range(1, len(paths) + 1):
        await user.should_see(marker=f"count-{index}", content="new /", retries=30)
    user.find(marker="review").click()
    user.find(marker="import").click()
    await user.should_see(created, marker="done-title", retries=30)


def left_out(store: Store, account_id: str = ORO) -> list[str]:
    return [row.import_id for row in store.excluded(BUDGET_ID, account_id)]


async def test_the_rows_ynab_did_not_take_are_listed_and_said_why(
    ynab_api: YnabClientStub, user: User
):
    first, *rest = import_ids("sabadell", SABADELL)
    ynab_api.refuse_import_ids(first)

    await import_all(user, SABADELL, created="2 transactions imported")

    await user.should_see(
        "YNAB did not take 1, see below. 0 were already there and were skipped.",
        marker="done-summary",
    )
    await user.should_see("YNAB did not take 1", marker="commit-refused-1")
    await user.should_see("YNAB did not take 1 row", marker="refused-title")
    await user.should_see(
        "You asked for it to be imported and yul sent it, but YNAB answered that it was "
        "imported before. That happens when a transaction was imported and then deleted in "
        "YNAB",
        marker="refused-why",
    )
    await user.should_see("Sabadell", marker="refused-file-1")
    await user.should_see("→ 💳 Oro", marker="refused-file-1")
    await user.should_see("movements.txt", marker="refused-file-1")
    await user.should_see("-48.00€", marker="refused-amount-1-0")
    await user.should_see("Don't import again", marker="never-1-0")
    await user.should_not_see(marker="refused-amount-1-1")
    await user.should_not_see(marker="done-alert")
    # One row: its own button is the only one
    await user.should_not_see(marker="never-all")
    assert [t.import_id for t in created(ynab_api)[ORO]] == [first, *rest]
    [entry] = state().store.activity(BUDGET_ID, kind="import")
    assert (
        entry.message
        == "Imported 2 transactions to 💳 Oro from movements.txt · YNAB did not take 1"
    )
    assert (entry.details["duplicates"], [r["import_id"] for r in entry.details["refused"]]) == (
        1,
        [first],
    )


async def test_nothing_is_said_when_ynab_takes_every_row(ynab_api: YnabClientStub, user: User):
    ynab_api.refuse_import_ids()

    await import_all(user, SABADELL, created="3 transactions imported")

    await user.should_see("0 were already there and were skipped.", marker="done-summary")
    await user.should_not_see(marker="refused")
    await user.should_not_see(marker="commit-refused-1")


async def test_a_row_not_to_import_again_is_left_out_and_undone_in_place(
    ynab_api: YnabClientStub, user: User
):
    first = import_ids("sabadell", SABADELL)[0]
    ynab_api.refuse_import_ids(first)
    await import_all(user, SABADELL, created="2 transactions imported")
    store = state().store

    user.find(marker="never-1-0").click()

    await user.should_see("Will not be imported again", marker="never-done-1-0", retries=20)
    await user.should_see(
        "Later imports list it as left out, with Include again to bring it back.",
        marker="never-all-done",
    )
    assert left_out(store) == [first]
    [entry] = store.activity(BUDGET_ID, kind="exclude")
    assert entry.message == "Left Barberia Docklands (-48.00€, 25/04/2026) out of imports to 💳 Oro"
    assert entry.details["import_id"] == first

    user.find(marker="undo-never-1-0").click()

    await user.should_see("Don't import again", marker="never-1-0", retries=20)
    assert left_out(store) == []
    [entry] = store.activity(BUDGET_ID, kind="include")
    assert entry.details["import_id"] == first


async def test_a_row_not_to_import_again_comes_back_left_out_on_the_next_import(
    ynab_api: YnabClientStub, user: User
):
    first, *rest = import_ids("sabadell", SABADELL)
    ynab_api.refuse_import_ids(first)
    await import_all(user, SABADELL, created="2 transactions imported")
    user.find(marker="never-1-0").click()
    await user.should_see(marker="never-done-1-0", retries=20)
    sent = len(created(ynab_api)[ORO])

    # A drop opens a new import
    await drop(user, SABADELL)

    await user.should_see("2 new / 3", marker="count-1", retries=30)
    await user.should_see("1 left out", marker="files-left-out")
    user.find(marker="review").click()
    show_every_row(user)
    await user.should_see("left out", marker="row-status-1-0", retries=20)
    await user.should_see("Include again", marker="include-1-0")
    user.find(marker="import").click()
    await user.should_see("2 transactions imported", marker="done-title", retries=30)
    assert [t.import_id for t in created(ynab_api)[ORO][sent:]] == rest
    await user.should_not_see(marker="refused")


async def test_every_row_of_every_file_is_left_out_at_once(
    ynab_api: YnabClientStub, user: User, tmp_path: Path
):
    bbva_file = write_xls(tmp_path / "tarjeta_maxima.xlsx", bbva_sheet())
    sabadell = import_ids("sabadell", SABADELL)
    bbva = import_ids("bbva", bbva_file)
    ynab_api.refuse_import_ids(sabadell[0], sabadell[2], bbva[1])
    await import_all(user, SABADELL, bbva_file, created="3 transactions imported")
    await user.should_see("YNAB did not take 3 rows", marker="refused-title")
    await user.should_see("→ 💳 Maxima", marker="refused-file-2")
    await user.should_see("Don't import any of them again", marker="never-all")

    user.find(marker="never-1-1").click()
    await user.should_see(marker="never-done-1-1", retries=20)
    await user.should_see("Don't import the other 2 again", marker="never-all")
    user.find(marker="never-all").click()

    await user.should_see(
        "Later imports list them as left out, with Include again to bring one back.",
        marker="never-all-done",
        retries=20,
    )
    for marker in ("1-0", "1-1", "2-0"):
        await user.should_see("Will not be imported again", marker=f"never-done-{marker}")
    store = state().store
    assert sorted(left_out(store, ORO)) == sorted([sabadell[0], sabadell[2]])
    assert left_out(store, MAXIMA) == [bbva[1]]
    assert len(store.activity(BUDGET_ID, kind="exclude")) == 3


async def test_a_choice_that_cannot_be_saved_leaves_the_row_as_it_was(
    ynab_api: YnabClientStub, user: User, mocker: MockerFixture
):
    ynab_api.refuse_import_ids(import_ids("sabadell", SABADELL)[0])
    await import_all(user, SABADELL, created="2 transactions imported")
    mocker.patch.object(state().store, "exclude", side_effect=OSError("disk full"))

    user.find(marker="never-1-0").click()

    await user.should_see("Could not save it on this computer: disk full", retries=20)
    await user.should_see("Don't import again", marker="never-1-0")
    await user.should_not_see(marker="never-done-1-0")


async def test_no_check_says_it_worked_when_ynab_took_nothing(ynab_api: YnabClientStub, user: User):
    ynab_api.refuse_import_ids(*import_ids("sabadell", SABADELL))

    await import_all(user, SABADELL, created="0 transactions imported")

    await user.should_see(marker="done-alert")
    await user.should_see("YNAB did not take 3 rows", marker="refused-title")

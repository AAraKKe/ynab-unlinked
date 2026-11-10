"""The layout around every page: the command palette, the sidebar's badges, the pages that are
not there or fail, and following a sync that changed the budget copy."""

import asyncio
import dataclasses
import threading

import pytest
from nicegui import ui
from nicegui.testing.user import User
from pytest_mock import MockerFixture

from tests.helpers.store import upsert
from tests.helpers.web import WAIT_SECONDS, eventually
from tests.web.views.test_cashflow_spending import (  # noqa: F401 (fixtures)
    GROCERIES,
    no_sync,
    synced,
)
from tests.web.views.test_home import (  # noqa: F401 (fixtures)
    CLEARED,
    budget,
    days_ago,
    last_imports,
    store,
    transaction,
)
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.store import Store
from ynab_unlinked.web import attention, frame, shell, wording
from ynab_unlinked.web.state import state

pytestmark = pytest.mark.version("V4")


def classes(user: User, marker: str) -> list[str]:
    return user.find(marker=marker).elements.pop().classes


def label(user: User, marker: str) -> ui.label:
    [element] = user.find(marker=marker).elements
    assert isinstance(element, ui.label)
    return element


@pytest.fixture
def fast_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tab looks at the app state every few milliseconds instead of every two seconds."""
    monkeypatch.setattr(frame, "TICK_SECONDS", 0.02)


# ---- command palette ----------------------------------------------------------------------


async def test_the_search_button_opens_the_palette_on_pages_tabs_and_actions(user: User):
    await user.open("/")

    user.find(marker="open-palette").click()

    for key in ("home", "reconcile", "networth", "settings", "sync", "theme"):
        await user.should_see(marker=f"palette-{key}")
    # The first result is the one Enter opens
    assert "on" in classes(user, "palette-home")
    # A tab is found by typing
    await user.should_not_see(marker="palette-networth-months")
    user.find(marker="palette-input").type("months")
    await user.should_see(marker="palette-networth-months")


async def test_typing_narrows_the_palette_and_a_click_goes_there(user: User):
    await user.open("/")
    user.find(marker="open-palette").click()
    await user.should_see(marker="palette-home")

    user.find(marker="palette-input").type("recon")

    await user.should_see(marker="palette-reconcile")
    await user.should_not_see(marker="palette-home")
    user.find(marker="palette-reconcile").click()
    await user.should_see("Reconcile what the bank confirmed")
    assert user.back_history[-1] == "/reconcile"


async def test_enter_opens_the_result_the_arrows_moved_to(user: User):
    await user.open("/")
    user.find(marker="open-palette").click()
    await user.should_see(marker="palette-home")

    user.find(marker="palette-input").type("settings")
    await user.should_see(marker="palette-settings-banks")
    user.find(marker="palette-input").trigger("keydown.down.prevent")
    user.find(marker="palette-input").trigger("keydown.down.prevent")
    assert "on" in classes(user, "palette-settings-banks")
    user.find(marker="palette-input").trigger("keydown.enter.prevent")

    await user.should_see(marker="tab-banks")
    assert user.back_history[-1] == "/settings?tab=banks"


async def test_a_query_that_finds_nothing_says_so(user: User):
    await user.open("/")
    user.find(marker="open-palette").click()
    await user.should_see(marker="palette-home")

    user.find(marker="palette-input").type("zzzz")

    await user.should_see(marker="palette-none")


async def test_the_palette_finds_a_category_and_opens_its_months(
    synced: Store,  # noqa: F811
    no_sync,  # noqa: F811
    user: User,
):
    await user.open("/")
    user.find(marker="open-palette").click()
    await user.should_see(marker="palette-home")

    user.find(marker="palette-input").type("groc")
    await user.should_see(marker=f"palette-category-{GROCERIES}")
    user.find(marker=f"palette-category-{GROCERIES}").click()

    await user.should_see(marker="category-detail")
    await user.should_see("Everyday / 🛒 Groceries")


# ---- sidebar badges ------------------------------------------------------------------------


async def test_the_sidebar_counts_what_is_waiting(
    store: Store,  # noqa: F811
    budget: LatestConfig,  # noqa: F811
    user: User,
):
    upsert(
        store,
        budget.budget.id,
        transactions=[
            transaction("c3", "checking", days_ago(2), -5_000, cleared=CLEARED),
            transaction("c4", "checking", days_ago(1), -7_000, cleared=CLEARED),
            # The broker's balance was last set by hand long ago
            transaction("b2", "broker", days_ago(60), 0, payee="Balance Adjustment"),
        ],
    )

    await user.open("/")

    await user.should_see(marker="nav-badge-reconcile")
    assert label(user, "nav-badge-reconcile").text == "2"
    assert label(user, "nav-badge-networth").text == "1"
    await user.should_not_see(marker="nav-badge-home")


async def test_a_quiet_budget_has_no_badge(store: Store, user: User):  # noqa: F811
    await user.open("/")
    await user.should_see(marker="nothing-waiting")

    await user.should_not_see(marker="nav-badge-reconcile")
    await user.should_not_see(marker="nav-badge-networth")


# ---- pages ---------------------------------------------------------------------------------


async def test_the_browser_tab_is_named_after_the_page(user: User):
    await user.open("/reconcile")
    await user.should_see("Reconcile what the bank confirmed")

    assert user.client is not None
    assert user.client.title == "Reconcile · yul"


async def test_the_way_to_import_is_not_offered_on_import_itself(user: User):
    await user.open("/")
    assert "yul-gone" not in classes(user, "top-import")

    user.find(marker="nav-import").click()

    await user.should_see("Drop bank statements here")
    assert "yul-gone" in classes(user, "top-import")


async def test_an_address_without_a_page_offers_the_way_home(user: User):
    await user.open("/")
    with user:
        ui.navigate.to("/nope")

    await user.should_see(frame.NOT_FOUND)
    await user.should_see(marker="nav-home")
    await user.should_not_see("404")


async def test_a_page_that_fails_to_draw_says_so_and_keeps_the_shell(
    user: User, monkeypatch: pytest.MonkeyPatch
):
    def broken() -> None:
        ui.label("half a page")
        raise RuntimeError("boom")

    views = shell._VIEWS
    monkeypatch.setitem(
        views, shell.CASHFLOW_PATH, dataclasses.replace(views[shell.CASHFLOW_PATH], builder=broken)
    )
    await user.open("/cashflow")

    await user.should_see(frame.PAGE_ERROR)
    await user.should_not_see("half a page")
    # The rest of the app is still there
    user.find(marker="nav-reconcile").click()
    await user.should_see("Reconcile what the bank confirmed")


# ---- following a sync ----------------------------------------------------------------------


async def test_a_sync_that_changed_the_copy_redraws_the_page_and_the_badges(
    store: Store,  # noqa: F811
    budget: LatestConfig,  # noqa: F811
    fast_tick: None,
    user: User,
):
    await user.open("/")
    await user.should_see(marker="nothing-waiting")

    # What a sync in the background does: new rows in the copy, and the version goes up
    upsert(
        store,
        budget.budget.id,
        transactions=[transaction("c3", "checking", days_ago(2), -5_000, cleared=CLEARED)],
    )
    state().data_version += 1

    await user.should_see(marker="attention-unreconciled")
    assert label(user, "nav-badge-reconcile").text == "1"


async def test_a_page_the_user_types_in_is_left_alone_by_a_sync_nobody_asked_for(
    store: Store,  # noqa: F811
    fast_tick: None,
    user: User,
    mocker: MockerFixture,
):
    await user.open("/")
    await user.should_see(marker="nothing-waiting")
    rebuild = mocker.spy(frame._Pages, "refresh")
    with user:
        shell.on_refresh(user.find(marker="home").elements.pop(), automatic=False)

    state().data_version += 1
    await user.should_not_see(marker="attention-unreconciled")
    with user:
        shell.refresh_view(automatic=True)
    assert rebuild.call_count == 0

    # A sync from the chip is the user asking
    with user:
        shell.refresh_view()
    assert rebuild.call_count == 1


async def test_a_view_with_its_own_refresh_is_not_rebuilt(
    store: Store,  # noqa: F811
    user: User,
    mocker: MockerFixture,
):
    await user.open("/")
    await user.should_see(marker="nothing-waiting")
    rebuild = mocker.spy(frame._Pages, "refresh")
    drawn: list[str] = []
    with user:
        shell.on_refresh(user.find(marker="home").elements.pop(), lambda: drawn.append("again"))
        shell.refresh_view(automatic=True)

    assert drawn == ["again"]
    assert rebuild.call_count == 0


# ---- saying what happened --------------------------------------------------------------------


async def test_something_that_worked_is_said_in_the_top_bar_not_over_the_page(user: User):
    await user.open("/")
    await user.should_not_see(marker="status")

    with user:
        shell.notify("Sabadell turned on")

    await user.should_see(marker="status")
    assert label(user, "status-text").text == "Sabadell turned on"
    assert user.notify.messages == []


async def test_a_note_is_said_there_too_without_the_check(user: User):
    await user.open("/")

    with user:
        shell.notify("No change", "info")

    await user.should_see(marker="status")
    assert "info" in classes(user, "status")
    with user:
        shell.notify("Saved")
    assert "info" not in classes(user, "status")
    assert user.notify.messages == []


@pytest.mark.parametrize("kind", ["warn", "error"])
async def test_a_problem_is_a_toast(user: User, kind: str):
    await user.open("/")

    with user:
        shell.notify("Could not reach YNAB", kind)  # type: ignore[arg-type]

    assert user.notify.messages == ["Could not reach YNAB"]
    await user.should_not_see(marker="status")


async def test_the_status_line_is_put_away_when_its_time_is_up(user: User):
    await user.open("/")
    with user:
        shell.notify("Saved")
        shown = shell.layout()
    assert shown is not None
    await user.should_see(marker="status")

    shell.hush(shown)
    await user.should_see(marker="status")  # not yet

    shown.status_until = 0
    shell.hush(shown)
    await user.should_not_see(marker="status")


async def test_the_month_card_explains_why_it_can_differ_from_ynab(
    store: Store,  # noqa: F811
    user: User,
):
    await user.open("/")
    await user.should_see(marker="month-info")

    [note] = user.find(marker="month-info-note").elements
    said = [child.text for child in note.descendants() if isinstance(child, ui.label)]
    assert said == [wording.VERSUS_YNAB_TITLE, *wording.VERSUS_YNAB]


async def test_an_older_look_never_puts_its_count_back_over_a_newer_one(
    store: Store,  # noqa: F811
    user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """The tab looks at the app state on a timer. A look still counting the badges when the
    next one started used to finish after it, and put its older count back: the badge of a
    page already redrawn with the new data went away until the look after that."""
    await user.open("/")
    await user.should_see(marker="nothing-waiting")
    with user:
        shown = shell.layout()
    assert shown is not None
    await eventually(lambda: shown.badges_version == state().data_version and not shown.ticking)

    reading, release = threading.Event(), threading.Event()
    reads: list[int] = []

    def waiting(*_: object) -> attention.Waiting:
        reads.append(len(reads))
        if len(reads) == 1:  # the older look: reads the copy as it was, slowly
            reading.set()
            release.wait(WAIT_SECONDS)
            return attention.Waiting(0, 0, [])
        return attention.Waiting(3, 1, [])

    counted: list[int] = []
    set_badge = frame._set_badge

    def record(layout: shell.Layout, key: str, count: int, title: str) -> None:
        if key == "reconcile":
            counted.append(count)
        set_badge(layout, key, count, title)

    monkeypatch.setattr(frame.attention, "waiting", waiting)
    monkeypatch.setattr(frame, "_set_badge", record)

    async def look() -> None:
        with user:
            await frame._tick(shown)

    state().data_version += 1
    older = asyncio.ensure_future(look())
    await eventually(reading.is_set)
    # A sync lands while the older look is still reading, and the next look comes
    state().data_version += 1
    await asyncio.wait_for(look(), WAIT_SECONDS)
    release.set()
    await asyncio.wait_for(older, WAIT_SECONDS)
    await asyncio.wait_for(look(), WAIT_SECONDS)

    # Oldest first, never back: without the wait this was [3, 0, 3]
    assert counted == [0, 3]
    assert label(user, "nav-badge-reconcile").text == "3"
    assert not shown.ticking

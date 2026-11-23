"""The simulated browser the web tests share (`tests.helpers.web.User`)."""

import pytest
from nicegui import ui

from tests.helpers import web
from tests.helpers.web import User, eventually
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.web import shell

pytestmark = pytest.mark.version("V4")


@pytest.fixture
async def page(config_v4: LatestConfig, user: User, monkeypatch: pytest.MonkeyPatch) -> User:
    """The Import page, whose steps are marked `step-1` (Files), `step-2` (Review)... A check
    that is meant to fail gives up at once."""
    await user.open(shell.IMPORT_PATH)
    await user.should_see(marker="step-1")
    monkeypatch.setattr(web, "WAIT_SECONDS", 0.02)
    return user


@pytest.fixture
async def shown(config_v4: LatestConfig, user: User) -> User:
    """The same page, waiting as long as every other test does."""
    await user.open(shell.IMPORT_PATH)
    await user.should_see(marker="step-1")
    return user


async def test_a_text_with_a_marker_is_that_element_showing_the_text(page: User):
    # The step holds the text in a label, the stepper holds the step
    await page.should_see("Files", marker="step-1")
    await page.should_see("Files", marker="stepper")
    await page.should_not_see("Review", marker="step-1")


async def test_a_text_shown_elsewhere_does_not_pass_for_the_marked_element(page: User):
    # Both are on the page, which is all NiceGUI's own check asks for
    await page.should_see("Review")
    await page.should_see(marker="step-1")

    with pytest.raises(AssertionError, match="element marked 'step-1' showing 'Review'"):
        await page.should_see("Review", marker="step-1")
    with pytest.raises(AssertionError):
        await page.should_not_see("Files", marker="step-1")


@pytest.mark.parametrize(
    "extra", [{"content": "Files"}, {"kind": ui.label}], ids=["content", "kind"]
)
async def test_a_text_with_a_filter_that_would_be_ignored_is_refused(page: User, extra: dict):
    with pytest.raises(TypeError, match="A text target takes a marker only"):
        await page.should_see("Files", **extra)


async def test_what_a_handler_raises_fails_the_test_unless_it_accounts_for_it(shown: User):
    def broken() -> None:
        raise ValueError("no such row")

    with shown:
        ui.button("Break", on_click=broken).mark("break")
    shown.find(marker="break").click()
    await eventually(lambda: len(shown.raised) == 1)

    # What the `guest` fixture runs once the test is over
    with pytest.raises(AssertionError, match="ValueError: no such row"):
        shown.check_raised()

    shown.raised.clear()
    shown.check_raised()


async def test_a_script_sent_to_the_browser_is_kept(shown: User):
    with shown:
        ui.button("Scroll", on_click=lambda: ui.run_javascript("scrollTo(0, 0)")).mark("scroll")

    shown.find(marker="scroll").click()

    await eventually(lambda: "scrollTo(0, 0)" in shown.scripts)

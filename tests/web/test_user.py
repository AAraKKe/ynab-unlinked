"""The simulated browser the web tests share (`tests.helpers.web.User`)."""

import pytest
from nicegui import ui

from tests.helpers import web
from tests.helpers.web import User
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

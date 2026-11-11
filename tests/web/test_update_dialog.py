"""The sidebar's "Update" button and the dialog behind it."""

import pytest
from nicegui import ui
from nicegui.testing.user import User
from pytest_mock import MockerFixture

from tests.helpers.web import eventually
from ynab_unlinked.__about__ import __version__
from ynab_unlinked.core.update import Install, UpdateError, Upgrade
from ynab_unlinked.web import update as web_update
from ynab_unlinked.web import update_dialog
from ynab_unlinked.web.update import updates

pytestmark = pytest.mark.version("V4")

NEWER = "99.0.0"
UV_TOOL = Upgrade(Install.UV_TOOL, ("uv", "tool", "upgrade", "ynab-unlinked"), automatic=True)


@pytest.fixture
def newer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_update, "latest_version", lambda: NEWER)


def installed_with(mocker: MockerFixture, upgrade: Upgrade) -> None:
    mocker.patch.object(update_dialog, "upgrade_plan", return_value=upgrade)


async def open_dialog(user: User) -> None:
    await user.open("/")
    await user.should_see(marker="update")
    user.find(marker="update").click()
    await user.should_see(marker="update-dialog")


def text(user: User, marker: str) -> str:
    [element] = user.find(marker=marker).elements
    assert isinstance(element, ui.label)
    return element.text


async def test_the_sidebar_only_shows_the_version_when_yul_is_the_latest(user: User):
    await user.open("/")
    await user.should_see(f"yul {__version__}")
    await eventually(lambda: updates().latest is not None)

    await user.should_not_see(marker="update")


async def test_a_newer_yul_puts_the_update_button_next_to_the_version(newer: None, user: User):
    await user.open("/")

    await user.should_see(marker="update")
    [button] = user.find(marker="update").elements
    assert button.props["title"] == f"yul {NEWER} is out"


async def test_the_confirmation_is_one_line_and_nothing_runs_before_it(
    newer: None, user: User, mocker: MockerFixture
):
    installed_with(mocker, UV_TOOL)
    run_upgrade = mocker.patch.object(web_update, "run_upgrade")

    await open_dialog(user)

    await user.should_see(f"Update to yul {NEWER}")
    assert text(user, "update-confirm") == update_dialog.CONFIRM
    # How yul updates itself is not the user's business until they must do it by hand
    await user.should_not_see(marker="update-command")
    user.find(marker="update-cancel").click()
    await user.should_not_see(marker="update-dialog")
    run_upgrade.assert_not_called()


async def test_updating_installs_the_new_yul_and_restarts_the_app(
    newer: None, user: User, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
):
    installed_with(mocker, UV_TOOL)
    run_upgrade = mocker.patch.object(web_update, "run_upgrade", return_value=NEWER)
    shutdown = mocker.patch.object(web_update.app, "shutdown")
    monkeypatch.setattr(update_dialog, "LAST_WORDS_SECONDS", 0)
    await open_dialog(user)

    user.find(marker="update-run").click()

    await user.should_see(f"yul {NEWER} is installed. Starting it again…")
    await eventually(lambda: updates().restarting)
    run_upgrade.assert_called_once_with(UV_TOOL, __version__)
    shutdown.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [
        UpdateError("error: Failed to fetch the index"),
        RuntimeError("error: Failed to fetch the index"),
    ],
    ids=["the-tool-failed", "something-unexpected"],
)
async def test_a_failed_update_says_why_and_how_to_do_it_by_hand(
    newer: None, user: User, mocker: MockerFixture, error: Exception
):
    installed_with(mocker, UV_TOOL)
    mocker.patch.object(web_update, "run_upgrade", side_effect=error)
    shutdown = mocker.patch.object(web_update.app, "shutdown")
    await open_dialog(user)

    user.find(marker="update-run").click()

    await user.should_see(marker="update-failed")
    assert text(user, "update-output") == "error: Failed to fetch the index"
    assert text(user, "update-command") == "uv tool upgrade ynab-unlinked"
    shutdown.assert_not_called()
    assert not updates().updating
    user.find(marker="update-close").click()
    await user.should_not_see(marker="update-dialog")


@pytest.mark.parametrize(
    ("upgrade", "line", "command"),
    [
        (
            Upgrade(Install.UNKNOWN, ("pip", "install", "--upgrade", "ynab-unlinked[web]"), False),
            update_dialog.BY_HAND,
            "pip install --upgrade 'ynab-unlinked[web]'",
        ),
        (Upgrade(Install.SOURCE, None, False), update_dialog.FROM_SOURCE, None),
    ],
    ids=["unknown-install", "from-source"],
)
async def test_an_install_yul_cannot_update_gets_the_way_to_do_it_by_hand(
    newer: None,
    user: User,
    mocker: MockerFixture,
    upgrade: Upgrade,
    line: str,
    command: str | None,
):
    installed_with(mocker, upgrade)

    await open_dialog(user)

    assert text(user, "update-by-hand") == line
    await user.should_not_see(marker="update-run")
    if command is None:
        await user.should_not_see(marker="update-command")
    else:
        assert text(user, "update-command") == command

import datetime as dt
from collections.abc import Callable

import pytest

from ynab_unlinked.__about__ import __version__
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.update import Install, UpdateError, Upgrade
from ynab_unlinked.web import state as web_state
from ynab_unlinked.web import update as web_update
from ynab_unlinked.web.state import state
from ynab_unlinked.web.update import CHECK_EVERY, updates

pytestmark = pytest.mark.version("V4")

NEWER = "99.0.0"
UPGRADE = Upgrade(Install.PIP, ("python", "-m", "pip", "install"), automatic=True)


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch: pytest.MonkeyPatch, config_v4: LatestConfig) -> None:
    """The app state read from this test's config, not the one a test before left behind."""
    monkeypatch.setattr(web_state, "_state", None)


@pytest.fixture
def pypi(monkeypatch: pytest.MonkeyPatch, config_v4: LatestConfig) -> Callable[[object], None]:
    """Make PyPI answer with a version, or fail with an error."""

    def answer(result: object) -> None:
        def latest_version() -> object:
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(web_update, "latest_version", latest_version)

    return answer


async def test_a_later_release_on_pypi_is_the_update(pypi: Callable[[object], None]):
    pypi(NEWER)

    assert await updates().check() == NEWER
    assert updates().available == NEWER


@pytest.mark.parametrize("latest", [__version__, "0.0.1"], ids=["the-running-one", "an-older-one"])
async def test_no_update_when_pypi_has_nothing_later(pypi: Callable[[object], None], latest: str):
    pypi(latest)

    assert await updates().check() is None
    assert updates().latest == latest


async def test_pypi_is_asked_when_the_app_opens_and_every_half_hour_after(
    pypi: Callable[[object], None],
):
    pypi(NEWER)
    status = updates()
    assert status.due()
    await status.check()
    now = dt.datetime.now(dt.UTC)

    assert not status.due(now + CHECK_EVERY - dt.timedelta(minutes=1))
    assert status.due(now + CHECK_EVERY)
    # A release is offered within the hour it came out
    assert dt.timedelta(hours=1) > CHECK_EVERY


async def test_a_check_that_fails_keeps_what_was_known_and_is_tried_again_as_often(
    pypi: Callable[[object], None],
):
    status = updates()
    pypi(NEWER)
    await status.check()
    pypi(UpdateError("offline"))

    assert await status.check() == NEWER
    assert status.failed
    now = dt.datetime.now(dt.UTC)
    assert not status.due(now + CHECK_EVERY - dt.timedelta(minutes=1))
    assert status.due(now + CHECK_EVERY)


def test_pypi_is_never_asked_once_the_check_is_turned_off(config_v4: LatestConfig):
    def off(config: LatestConfig) -> None:
        config.check_for_updates = False

    state().update_config(off)

    assert not updates().due()


def test_a_config_written_before_the_switch_existed_has_the_check_on(config_v4: LatestConfig):
    assert "check_for_updates" not in LatestConfig.path().read_text()
    assert config_v4.check_for_updates


async def test_a_failed_update_leaves_the_app_as_it_was(
    monkeypatch: pytest.MonkeyPatch, pypi: Callable[[object], None]
):
    def fail(upgrade: Upgrade, current: str) -> str:
        raise UpdateError("ERROR: no network")

    monkeypatch.setattr(web_update, "run_upgrade", fail)
    status = updates()

    with pytest.raises(UpdateError, match="no network"):
        await status.update(UPGRADE)

    assert not status.updating
    assert not status.restarting
    assert status.due()

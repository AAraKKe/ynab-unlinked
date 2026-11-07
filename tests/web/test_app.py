import stat
import sys
from pathlib import Path

import pytest
from nicegui.storage import Storage
from pytest_mock import MockerFixture

from tests.helpers.web import fresh_nicegui
from ynab_unlinked.web import app as web_app


@pytest.fixture
def ui_run(mocker: MockerFixture, tmp_path: Path):
    mocker.patch("ynab_unlinked.web.app.storage_dir", return_value=tmp_path / "web")
    original = Storage.path
    with fresh_nicegui():
        yield mocker.patch("ynab_unlinked.web.app.ui.run")
        # run() moved the storage; put it back before NiceGUI clears it on the way out
        Storage.path = original


@pytest.mark.version("missing")
@pytest.mark.parametrize(
    ("port", "open_browser"),
    [(None, True), (8765, False)],
    ids=["free-port-browser", "fixed-port-no-browser"],
)
def test_run_serves_on_loopback_only_and_opens_the_token_link(
    config: str, ui_run, port: int | None, open_browser: bool, tmp_path: Path
):
    announced: list[str] = []

    web_app.run(port=port, open_browser=open_browser, announce=announced.append)

    kwargs = ui_run.call_args.kwargs
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["reload"] is False
    if port is not None:
        assert kwargs["port"] == port
    else:
        assert isinstance(kwargs["port"], int) and kwargs["port"] > 0
    url = announced[0].removeprefix("yul is running at ")
    assert url.startswith(f"http://127.0.0.1:{kwargs['port']}/?token=")
    token = url.split("token=")[1]
    assert len(token) >= 32
    assert kwargs["show"] == (f"/?token={token}" if open_browser else False)
    # Preferences live in the user data dir, not in a .nicegui folder wherever yul was started
    assert Storage.path == tmp_path / "web"
    assert (tmp_path / "web" / "secret").read_text() == kwargs["storage_secret"]


@pytest.mark.version("missing")
def test_run_keeps_the_storage_secret_across_runs(config: str, ui_run):
    web_app.run(open_browser=False)
    first = ui_run.call_args.kwargs["storage_secret"]

    web_app.run(open_browser=False)

    assert ui_run.call_args.kwargs["storage_secret"] == first


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no POSIX file modes")
@pytest.mark.version("missing")
def test_run_keeps_the_data_folder_and_the_storage_secret_for_the_user_only(
    config: str, ui_run, tmp_path: Path, mocker: MockerFixture
):
    data = tmp_path / "data"
    mocker.patch("ynab_unlinked.web.app.storage_dir", return_value=data / "web")

    web_app.run(open_browser=False)

    assert mode(data) == 0o700
    assert mode(data / "web") == 0o700
    assert mode(data / "web" / "secret") == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no POSIX file modes")
@pytest.mark.version("missing")
def test_run_narrows_a_storage_folder_an_older_yul_left_readable(
    config: str, ui_run, tmp_path: Path
):
    web = tmp_path / "web"
    web.mkdir(mode=0o755)
    (web / "secret").write_text("kept")
    (web / "secret").chmod(0o644)

    web_app.run(open_browser=False)

    assert ui_run.call_args.kwargs["storage_secret"] == "kept"
    assert mode(web) == 0o700
    assert mode(web / "secret") == 0o600

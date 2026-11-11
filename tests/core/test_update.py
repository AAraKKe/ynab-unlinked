import io
import json
import os
import re
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from ynab_unlinked.core import update
from ynab_unlinked.core.update import Install, UpdateError, Upgrade

PIP_UPGRADE = Upgrade(Install.PIP, ("python", "-m", "pip", "install"), automatic=True)


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [
        ("1.2.0", "1.1.0", True),
        ("1.10.0", "1.9.3", True),
        ("2.0", "1.9.9", True),
        ("1.1.0", "1.1.0", False),
        ("1.1", "1.1.0", False),
        ("1.0.9", "1.1.0", False),
        ("1.2.0rc1", "1.1.0", False),
        ("1.2.0", "1.1.1.dev3+g1a2b3c", False),
        ("", "1.1.0", False),
    ],
    ids=[
        "patch-ahead",
        "numbers-not-text",
        "shorter-but-later",
        "same",
        "same-without-the-zero",
        "older",
        "pre-release-is-not-offered",
        "development-build-is-left-alone",
        "empty",
    ],
)
def test_only_a_later_final_release_is_newer(candidate: str, current: str, newer: bool):
    assert update.is_newer(candidate, current) is newer


def answers(mocker: MockerFixture, body: bytes):
    return mocker.patch("urllib.request.urlopen", return_value=io.BytesIO(body))


def test_the_latest_version_is_the_one_pypi_names(mocker: MockerFixture):
    urlopen = answers(mocker, json.dumps({"info": {"version": "1.2.0"}, "releases": {}}).encode())

    assert update.latest_version() == "1.2.0"
    request = urlopen.call_args.args[0]
    assert request.full_url == "https://pypi.org/pypi/ynab-unlinked/json"
    # Nothing about the user travels with the question
    assert request.data is None
    assert set(request.headers) == {"Accept"}


@pytest.mark.parametrize(
    "body",
    [b"<html>maintenance</html>", b"{}", b'{"info": null}', b"[]"],
    ids=["not-json", "no-info", "info-is-null", "a-list"],
)
def test_an_answer_that_is_not_the_expected_document_is_an_update_error(
    mocker: MockerFixture, body: bytes
):
    answers(mocker, body)

    with pytest.raises(UpdateError):
        update.latest_version()


@pytest.mark.parametrize(
    "error",
    [urllib.error.URLError("no route to host"), TimeoutError("timed out")],
    ids=["offline", "timeout"],
)
def test_an_unreachable_pypi_is_an_update_error(mocker: MockerFixture, error: Exception):
    mocker.patch("urllib.request.urlopen", side_effect=error)

    with pytest.raises(UpdateError):
        update.latest_version()


@pytest.fixture
def environment(tmp_path: Path, mocker: MockerFixture) -> Path:
    """yul installed from PyPI in a virtual environment at `tmp_path`, with pip and every
    tool at hand. A test changes the one thing it is about."""
    mocker.patch.object(sys, "prefix", str(tmp_path))
    mocker.patch.object(sys, "executable", str(tmp_path / "bin" / "python"))
    mocker.patch.object(update, "_from_source", return_value=False)
    mocker.patch.object(update, "_in_environment", return_value=True)
    mocker.patch.object(update, "RESTARTS", True)
    mocker.patch("shutil.which", side_effect=lambda name: f"/usr/local/bin/{name}")
    mocker.patch("importlib.util.find_spec", return_value=object())
    return tmp_path


@pytest.mark.parametrize(
    ("receipt", "install", "command"),
    [
        ("uv-receipt.toml", Install.UV_TOOL, ("uv", "tool", "upgrade", "ynab-unlinked")),
        ("pipx_metadata.json", Install.PIPX, ("pipx", "upgrade", "ynab-unlinked")),
    ],
    ids=["uv-tool", "pipx"],
)
def test_a_tool_install_is_upgraded_by_its_tool(
    environment: Path, receipt: str, install: Install, command: tuple[str, ...]
):
    (environment / receipt).write_text("")

    assert update.upgrade_plan(web=True) == Upgrade(install, command, automatic=True)


def test_a_tool_that_is_not_at_hand_leaves_its_command_to_the_user(
    environment: Path, mocker: MockerFixture
):
    (environment / "uv-receipt.toml").write_text("")
    mocker.patch("shutil.which", return_value=None)

    upgrade = update.upgrade_plan(web=True)

    assert not upgrade.automatic
    assert upgrade.shown == "uv tool upgrade ynab-unlinked"


@pytest.mark.parametrize(
    ("web", "target"),
    [(True, "ynab-unlinked[web]"), (False, "ynab-unlinked")],
    ids=["web-extra-kept", "command-line-only"],
)
def test_pip_in_an_environment_upgrades_with_its_own_interpreter(
    environment: Path, web: bool, target: str
):
    upgrade = update.upgrade_plan(web=web)

    python = str(environment / "bin" / "python")
    assert upgrade == Upgrade(
        Install.PIP, (python, "-m", "pip", "install", "--upgrade", target), automatic=True
    )


@pytest.mark.parametrize(
    "missing",
    ["_in_environment", "pip"],
    ids=["system-python", "environment-without-pip"],
)
def test_without_an_environment_or_pip_the_user_gets_a_command_to_run(
    environment: Path, mocker: MockerFixture, missing: str
):
    if missing == "pip":
        mocker.patch("importlib.util.find_spec", return_value=None)
    else:
        mocker.patch.object(update, missing, return_value=False)

    upgrade = update.upgrade_plan(web=True)

    assert upgrade.install is Install.UNKNOWN
    assert not upgrade.automatic
    assert upgrade.shown == "pip install --upgrade 'ynab-unlinked[web]'"


def test_an_install_from_source_is_never_upgraded_even_inside_a_tool(
    environment: Path, mocker: MockerFixture
):
    (environment / "pipx_metadata.json").write_text("")
    mocker.patch.object(update, "_from_source", return_value=True)

    assert update.upgrade_plan(web=True) == Upgrade(Install.SOURCE, None, automatic=False)


def test_yul_does_not_upgrade_itself_where_it_cannot_restart_itself(
    environment: Path, mocker: MockerFixture
):
    mocker.patch.object(update, "RESTARTS", False)

    upgrade = update.upgrade_plan(web=True)

    assert upgrade.install is Install.PIP
    assert not upgrade.automatic


def test_the_checkout_the_tests_run_from_counts_as_source():
    assert update.upgrade_plan(web=True).install is Install.SOURCE


def ran(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_an_upgrade_returns_the_version_it_installed(mocker: MockerFixture):
    run = mocker.patch("subprocess.run", side_effect=[ran(), ran(stdout="1.2.0\n")])

    assert update.run_upgrade(PIP_UPGRADE, "1.1.0") == "1.2.0"
    assert run.call_args_list[0].args[0] == PIP_UPGRADE.command
    # Without these pip and uv read the releases they remember, from before the new one
    environment = run.call_args_list[0].kwargs["env"]
    assert environment["PIP_NO_CACHE_DIR"] == "1"
    assert environment["UV_NO_CACHE"] == "1"
    assert environment["PATH"] == os.environ["PATH"]
    # The installed version is asked to a new interpreter, never to the running one
    assert run.call_args_list[1].args[0][:2] == [sys.executable, "-c"]


def test_a_failed_upgrade_carries_the_last_lines_the_tool_printed(mocker: MockerFixture):
    noise = "\n".join(f"Collecting dependency-{n}" for n in range(20))
    mocker.patch(
        "subprocess.run",
        return_value=ran(1, stdout=noise, stderr="\nERROR: No matching distribution found\n"),
    )

    with pytest.raises(UpdateError) as raised:
        update.run_upgrade(PIP_UPGRADE, "1.1.0")

    lines = str(raised.value).splitlines()
    assert lines[-1] == "ERROR: No matching distribution found"
    assert len(lines) == update.OUTPUT_LINES


def test_an_upgrade_that_changed_nothing_is_an_error_not_a_restart(mocker: MockerFixture):
    # pip succeeds when it cannot reach the index and the installed yul satisfies the request
    said = "WARNING: Retrying after connection broken\nRequirement already satisfied: ynab-unlinked"
    mocker.patch("subprocess.run", side_effect=[ran(stdout=said), ran(stdout="1.1.0\n")])

    with pytest.raises(UpdateError) as raised:
        update.run_upgrade(PIP_UPGRADE, "1.1.0")

    assert str(raised.value) == f"It ran, but yul is still 1.1.0.\n{said}"


@pytest.mark.parametrize(
    "error",
    [subprocess.TimeoutExpired("pip", 300), FileNotFoundError("pipx")],
    ids=["never-ends", "tool-gone"],
)
def test_an_upgrade_that_cannot_run_is_an_update_error(mocker: MockerFixture, error: Exception):
    mocker.patch("subprocess.run", side_effect=error)

    with pytest.raises(UpdateError):
        update.run_upgrade(PIP_UPGRADE, "1.1.0")


def test_an_install_from_source_refuses_to_upgrade(mocker: MockerFixture):
    run = mocker.patch("subprocess.run")

    with pytest.raises(UpdateError):
        update.run_upgrade(Upgrade(Install.SOURCE, None, automatic=False), "1.1.0")
    run.assert_not_called()


def test_the_restart_command_runs_the_yul_on_disk_through_its_interpreter():
    result = subprocess.run(
        update.restart_command(["--help"]), capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    # Typer colours the help wherever GITHUB_ACTIONS is set, a pipe included
    assert "Usage: yul" in re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)

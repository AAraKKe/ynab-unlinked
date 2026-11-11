"""A newer yul: whether PyPI has one, and how this install is brought up to it.

yul is installed in several ways (`uv tool`, pipx, pip in an environment, a checkout), and
each has its own way to upgrade. `upgrade_plan()` tells them apart from what the running
environment holds, `run_upgrade()` runs the command of the ones yul can upgrade itself, and
`restart_command()` is the command line that starts the upgraded yul.

The check asks PyPI for one public document and sends nothing about the user.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

PACKAGE = "ynab-unlinked"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE}/json"
CHANGELOG_URL = "https://github.com/AAraKKe/ynab-unlinked/blob/main/CHANGELOG.md"

CHECK_TIMEOUT = 5.0
"""Seconds PyPI gets to answer. The check is a nicety: it gives up early."""
UPGRADE_TIMEOUT = 300.0
"""Seconds the upgrade command gets, downloads included."""
RESTARTS = os.name == "posix"
"""Whether yul can replace itself with the upgraded yul (`os.execv`): not on Windows."""
FRESH_INDEX = {"PIP_NO_CACHE_DIR": "1", "UV_NO_CACHE": "1"}
"""Set for the upgrade command, so the tool asks PyPI instead of trusting what it remembers.

pip keeps the list of a package's releases for the ten minutes PyPI allows. An upgrade run
within ten minutes of an install, or of an earlier upgrade, then reads a list from before
the release yul just found and ends with "already at latest version" (pipx with pip did, on
the day 1.3.0 followed 1.2.0). pipx runs pip or uv, so both are told; neither setting is
written to what the tool remembers of the install.
"""
OUTPUT_LINES = 6
"""How many of the last lines a failed upgrade printed are kept for the user."""

_RELEASE = re.compile(r"\d+(\.\d+)*")
_UV_RECEIPT = "uv-receipt.toml"
_PIPX_RECEIPT = "pipx_metadata.json"
_INSTALLED_VERSION = f"from importlib.metadata import version; print(version({PACKAGE!r}))"


class UpdateError(Exception):
    """PyPI could not be asked, or the upgrade did not bring a newer yul."""


class Install(StrEnum):
    """How the running yul was installed."""

    UV_TOOL = "uv tool"
    PIPX = "pipx"
    PIP = "pip"
    SOURCE = "source"
    """From a folder, an archive or a repository rather than from PyPI (a checkout)."""
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Upgrade:
    """How this install of yul gets a newer version."""

    install: Install
    command: tuple[str, ...] | None
    """What upgrades it. None for an install from source: only its owner knows."""
    automatic: bool
    """yul can run `command` and restart itself. Otherwise the user runs it in a terminal."""

    @property
    def shown(self) -> str | None:
        """`command` as one line to read or paste in a terminal."""
        return shlex.join(self.command) if self.command is not None else None


def _release(version: str) -> tuple[int, ...] | None:
    """`1.2.0` as `(1, 2)`: its numbers without trailing zeros. None for anything but a
    final release (a pre-release, a local build), which is never compared."""
    if not _RELEASE.fullmatch(version):
        return None
    numbers = [int(part) for part in version.split(".")]
    while numbers and numbers[-1] == 0:
        numbers.pop()
    return tuple(numbers)


def is_newer(candidate: str, current: str) -> bool:
    """Whether `candidate` is a later release than `current`. False when either is not a
    final release: a development build is never told to move to the published one."""
    new, old = _release(candidate), _release(current)
    return new is not None and old is not None and new > old


def latest_version(timeout: float = CHECK_TIMEOUT) -> str:
    """The newest release of yul on PyPI. `UpdateError` when PyPI cannot be asked."""
    request = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return str(json.load(response)["info"]["version"])
    except (OSError, ValueError, LookupError, TypeError) as error:
        raise UpdateError(f"PyPI could not be asked for the latest yul: {error}") from error


def _from_source() -> bool:
    """Whether yul was installed from a folder, an archive or a repository, not from PyPI."""
    try:
        return distribution(PACKAGE).read_text("direct_url.json") is not None
    except PackageNotFoundError:
        return True


def _in_environment() -> bool:
    """Whether yul runs in a virtual environment, where pip may install freely."""
    return sys.prefix != sys.base_prefix


def upgrade_plan(*, web: bool) -> Upgrade:
    """How the running yul is upgraded, from what its environment holds.

    `uv tool` and pipx leave a receipt in the environment and remember the extras themselves.
    pip is asked for the `web` extra again when `web` is set. yul only upgrades itself where
    it can also restart itself (`os.execv`, not on Windows) and the tool is at hand.
    """
    if _from_source():
        return Upgrade(Install.SOURCE, None, automatic=False)

    prefix = Path(sys.prefix)
    for install, receipt, command in (
        (Install.UV_TOOL, _UV_RECEIPT, ("uv", "tool", "upgrade", PACKAGE)),
        (Install.PIPX, _PIPX_RECEIPT, ("pipx", "upgrade", PACKAGE)),
    ):
        if (prefix / receipt).is_file():
            return Upgrade(
                install, command, automatic=RESTARTS and shutil.which(command[0]) is not None
            )

    target = f"{PACKAGE}[web]" if web else PACKAGE
    if _in_environment() and importlib.util.find_spec("pip") is not None:
        command = (sys.executable, "-m", "pip", "install", "--upgrade", target)
        return Upgrade(Install.PIP, command, automatic=RESTARTS)
    return Upgrade(Install.UNKNOWN, ("pip", "install", "--upgrade", target), automatic=False)


def _last_lines(*outputs: str | None) -> str:
    lines = [line for output in outputs for line in (output or "").splitlines() if line.strip()]
    return "\n".join(lines[-OUTPUT_LINES:])


def installed_version() -> str:
    """The version of yul on disk, which is not the running one once an upgrade ran.

    Asked to a new interpreter: this one may hold a stale view of the environment, or none
    at all when the upgrade rebuilt it.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", _INSTALLED_VERSION],
            capture_output=True,
            text=True,
            timeout=CHECK_TIMEOUT * 6,
            stdin=subprocess.DEVNULL,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise UpdateError(f"The installed yul could not be read: {error}") from error
    return result.stdout.strip()


def run_upgrade(upgrade: Upgrade, current: str, timeout: float = UPGRADE_TIMEOUT) -> str:
    """Run `upgrade.command` and return the version it installed, newer than `current`.

    The command runs with `FRESH_INDEX`: it reads the releases from PyPI, not from what the
    tool remembers. `UpdateError` carries the last lines the command printed when it fails,
    and when it worked without bringing a newer yul (an install pinned to a version, a
    package index that could not be reached): the lines usually say why.
    """
    if upgrade.command is None:
        raise UpdateError("This yul was not installed from PyPI.")
    try:
        result = subprocess.run(
            upgrade.command,
            env={**os.environ, **FRESH_INDEX},
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise UpdateError(f"It did not finish in {timeout:.0f} seconds.") from error
    except OSError as error:
        raise UpdateError(str(error)) from error
    printed = _last_lines(result.stdout, result.stderr)
    if result.returncode != 0:
        raise UpdateError(printed or f"It ended with code {result.returncode}.")
    installed = installed_version()
    if not is_newer(installed, current):
        raise UpdateError(f"It ran, but yul is still {installed}.\n{printed}".strip())
    return installed


def restart_command(arguments: Sequence[str]) -> list[str]:
    """The command line that runs the yul on disk with `arguments` (`python -m ynab_unlinked`).

    Through the interpreter rather than the `yul` script: the script may not be on the PATH
    the app was started with, and an upgrade rewrites it.
    """
    return [sys.executable, "-m", "ynab_unlinked", *arguments]

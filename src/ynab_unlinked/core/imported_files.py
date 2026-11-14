"""The statement files of an import once it is done: where they are, and removing them.

`yul load` knows the path of every file it reads. The web app does not: a browser hands a
page the name and the bytes of a dropped file, never its folder. `find_originals` looks for
the file on this computer instead, by name and then by content, so the only files ever
offered for removal hold exactly the bytes that were imported.

Removing is deleting for good, not moving to the Trash: the point is that statements do not
stay on disk. A file is only removed while its bytes are the ones that were imported (its
SHA-256 is compared when it is found and again right before it is deleted), and what was
removed goes to the activity log with that digest (`removal_log`).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_desktop_dir, user_documents_dir, user_downloads_dir

from ynab_unlinked.core.importing import file_digest
from ynab_unlinked.text import name_list

SEARCH_TIMEOUT = 10.0
"""Seconds Spotlight gets to answer. It usually takes a few hundredths."""
REMOVE_KIND = "remove"
"""The kind of the activity log entry of a removal (`removal_log`)."""


@dataclass(frozen=True)
class Original:
    """A file on this computer that holds exactly the bytes an import read."""

    path: Path
    digest: str
    """SHA-256 of those bytes (`core.importing.file_digest`)."""

    @staticmethod
    def of(path: Path) -> Original:
        """`path` as it is now. Take it before the file is read, so a file that changes
        during the import is not removed after it."""
        return Original(path, file_digest(path))


@dataclass(frozen=True)
class Imported:
    """A file an import read, as the web app knows it: no path, the browser keeps it."""

    name: str
    digest: str
    size: int


@dataclass(frozen=True)
class Located:
    """Where the files of an import are on this computer (`locate`)."""

    originals: tuple[Original, ...]
    missing: tuple[str, ...]
    """The names of the files that were not found."""
    copies: bool
    """Some file is in more than one place: all its copies are in `originals`."""


@dataclass(frozen=True)
class Removal:
    """What `remove_originals` did."""

    removed: tuple[Original, ...]
    failed: tuple[tuple[Path, str], ...]
    """The files still there, each with why."""


def spotlight(name: str) -> list[Path]:
    """The files called `name` anywhere in the home folder, from the Spotlight index (macOS).

    Empty on other systems, when Spotlight is off or has not seen the file, or when it does
    not answer: the caller then looks in `common_folders()`.
    """
    if sys.platform != "darwin" or (mdfind := shutil.which("mdfind")) is None:
        return []
    try:
        result = subprocess.run(
            # `-name` also matches names that contain `name`: filtered below
            [mdfind, "-0", "-onlyin", str(Path.home()), "-name", name],
            capture_output=True,
            timeout=SEARCH_TIMEOUT,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    paths = (Path(os.fsdecode(found)) for found in result.stdout.split(b"\0") if found)
    return [path for path in paths if path.name == name]


def common_folders() -> list[Path]:
    """Where a statement usually lands: the Downloads, Desktop and Documents folders."""
    return [Path(folder()) for folder in (user_downloads_dir, user_desktop_dir, user_documents_dir)]


def _holds(path: Path, digest: str, size: int | None) -> bool:
    """Whether `path` is a file with exactly these bytes. False for one that cannot be read."""
    try:
        if path.is_symlink() or not path.is_file():
            return False
        if size is not None and path.stat().st_size != size:
            return False
        return file_digest(path) == digest
    except OSError:
        return False


def find_originals(name: str, digest: str, size: int | None = None) -> list[Original]:
    """The files on this computer called `name` whose bytes have this `digest`.

    Spotlight names the candidates wherever they are in the home folder (macOS); without an
    answer from it they are looked for in `common_folders()`, not in the folders under
    them. Each candidate is then read: one with the same name and other bytes is not the
    file that was imported. `size` skips reading the ones of another size. Several copies of
    the file give several results, sorted by path.
    """
    candidates = spotlight(name) or [folder / name for folder in common_folders()]
    return [
        Original(path, digest) for path in sorted(set(candidates)) if _holds(path, digest, size)
    ]


def locate(files: Sequence[Imported]) -> Located:
    """`find_originals` for every file of an import. Reads the disk: run it off the loop."""
    originals: list[Original] = []
    missing: list[str] = []
    copies = False
    for file in files:
        found = find_originals(file.name, file.digest, file.size)
        originals += [original for original in found if original not in originals]
        copies = copies or len(found) > 1
        if not found:
            missing.append(file.name)
    return Located(tuple(originals), tuple(missing), copies)


def remove_originals(originals: Iterable[Original]) -> Removal:
    """Delete each file for good, unless its bytes are no longer the ones that were imported.

    Never raises: a file that is gone, changed or cannot be deleted is in `failed` with why.
    """
    removed: list[Original] = []
    failed: list[tuple[Path, str]] = []
    for original in originals:
        path = original.path
        try:
            if not path.is_file():
                failed.append((path, "it is no longer there"))
            elif file_digest(path) != original.digest:
                failed.append((path, "it changed since it was imported"))
            else:
                path.unlink()
                removed.append(original)
        except OSError as error:
            failed.append((path, error.strerror or str(error)))
    return Removal(tuple(removed), tuple(failed))


def removal_log(removed: Sequence[Original]) -> tuple[str, dict[str, Any]]:
    """The activity log message and details of the files a removal deleted (`REMOVE_KIND`):
    where each one was, and the SHA-256 of the bytes it held, the ones that were imported."""
    message = (
        f"Removed {name_list([shown(original.path) for original in removed])} from this computer"
    )
    details: dict[str, Any] = {
        "count": len(removed),
        "files": [{"path": str(original.path), "digest": original.digest} for original in removed],
    }
    return message, details


def shown(path: Path) -> str:
    """`path` as the user reads it: `~/Downloads/movimientos.txt` for one in the home folder."""
    try:
        return str(Path("~") / path.relative_to(Path.home()))
    except ValueError:
        return str(path)

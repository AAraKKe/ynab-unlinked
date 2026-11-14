import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ynab_unlinked.core import imported_files
from ynab_unlinked.core.imported_files import (
    Imported,
    Original,
    find_originals,
    locate,
    removal_log,
    remove_originals,
    shown,
    spotlight,
)
from ynab_unlinked.core.importing import file_digest

BYTES = b"FECHA|CONCEPTO|IMPORTE\n01/01|SHOP|10,00EUR\n"


def write(path: Path, content: bytes = BYTES) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def imported(name: str = "movements.txt", content: bytes = BYTES) -> Imported:
    return Imported(name, hashlib.sha256(content).hexdigest(), len(content))


def test_a_file_with_the_same_name_and_bytes_is_found_in_the_usual_folders(downloads: Path):
    statement = write(downloads / "movements.txt")
    file = imported()

    assert find_originals(file.name, file.digest, file.size) == [
        Original(statement, file_digest(statement))
    ]


@pytest.mark.parametrize(
    ("name", "content"),
    [
        pytest.param("movements.txt", b"another statement, same length!!!!!!!!!!!!!", id="bytes"),
        pytest.param("movements.txt", BYTES + b"more", id="size"),
        pytest.param("other.txt", BYTES, id="name"),
    ],
)
def test_a_file_that_differs_in_name_or_bytes_is_not_the_one_imported(
    downloads: Path, name: str, content: bytes
):
    write(downloads / name, content)
    file = imported()

    assert find_originals(file.name, file.digest, file.size) == []
    assert locate([file]).missing == ("movements.txt",)


def test_a_folder_under_the_usual_ones_is_not_searched(downloads: Path):
    write(downloads / "2026" / "movements.txt")

    assert find_originals(imported().name, imported().digest) == []


def test_what_spotlight_names_is_read_before_it_is_believed(
    tmp_path: Path, downloads: Path, monkeypatch: pytest.MonkeyPatch
):
    kept = write(tmp_path / "archive" / "movements.txt")
    other = write(tmp_path / "old" / "movements.txt", b"last month's")
    link = tmp_path / "link" / "movements.txt"
    link.parent.mkdir()
    link.symlink_to(kept)
    # Never looked at: Spotlight answered
    write(downloads / "movements.txt")
    monkeypatch.setattr(
        imported_files, "spotlight", lambda name: [kept, other, link, tmp_path / "gone.txt"]
    )
    file = imported()

    assert [o.path for o in find_originals(file.name, file.digest, file.size)] == [kept]


def test_every_copy_of_a_file_is_located_and_said_to_be_a_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    first = write(tmp_path / "a" / "movements.txt")
    second = write(tmp_path / "b" / "movements.txt")
    card = write(tmp_path / "a" / "card.xlsx", b"card")
    monkeypatch.setattr(imported_files, "common_folders", lambda: [tmp_path / "a", tmp_path / "b"])

    located = locate([imported(), imported("card.xlsx", b"card"), imported("gone.pdf", b"x")])

    assert [o.path for o in located.originals] == [first, second, card]
    assert located.missing == ("gone.pdf",)
    assert located.copies
    assert not locate([imported("card.xlsx", b"card")]).copies


def test_removing_deletes_the_file_for_good(downloads: Path):
    statement = write(downloads / "movements.txt")

    original = Original.of(statement)

    removal = remove_originals([original])

    assert removal.removed == (original,)
    assert removal.failed == ()
    assert not statement.exists()


def test_a_file_that_changed_or_is_gone_is_left_alone_and_said_so(downloads: Path):
    changed = write(downloads / "movements.txt")
    gone = write(downloads / "card.xlsx")
    originals = [Original.of(changed), Original.of(gone)]
    changed.write_bytes(b"downloaded again, with more rows")
    gone.unlink()

    removal = remove_originals(originals)

    assert removal.removed == ()
    assert removal.failed == (
        (changed, "it changed since it was imported"),
        (gone, "it is no longer there"),
    )
    assert changed.read_bytes() == b"downloaded again, with more rows"


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs file permissions")
def test_a_file_that_cannot_be_deleted_is_reported_not_raised(downloads: Path):
    statement = write(downloads / "movements.txt")
    original = Original.of(statement)
    downloads.chmod(0o500)
    try:
        removal = remove_originals([original])
    finally:
        downloads.chmod(0o700)

    assert removal.removed == ()
    [(path, why)] = removal.failed
    assert path == statement
    assert "denied" in why.lower()
    assert statement.exists()


def test_the_log_entry_of_a_removal_names_each_file_and_the_bytes_it_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    statement = Original(tmp_path / "Downloads" / "movimientos.txt", "a" * 64)
    card = Original(Path("/Volumes/disk/tarjeta.xlsx"), "b" * 64)

    message, details = removal_log([statement, card])

    home = Path("~") / "Downloads" / "movimientos.txt"
    assert message == f"Removed {home} and /Volumes/disk/tarjeta.xlsx from this computer"
    assert details == {
        "count": 2,
        "files": [
            {"path": str(statement.path), "digest": "a" * 64},
            {"path": "/Volumes/disk/tarjeta.xlsx", "digest": "b" * 64},
        ],
    }


def test_a_path_in_the_home_folder_is_shown_from_the_tilde(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert shown(tmp_path / "Downloads" / "movements.txt") == str(
        Path("~") / "Downloads" / "movements.txt"
    )
    assert shown(Path("/Volumes/disk/movements.txt")) == "/Volumes/disk/movements.txt"


def spotlight_answers(monkeypatch: pytest.MonkeyPatch, stdout: bytes, code: int = 0) -> list:
    """Make this a Mac whose `mdfind` prints `stdout`. Returns the command lines it was run with."""
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        return subprocess.CompletedProcess(command, code, stdout, b"")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(imported_files.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(imported_files.subprocess, "run", run)
    return calls


def test_spotlight_is_asked_for_the_name_in_the_home_folder_and_keeps_exact_names(
    monkeypatch: pytest.MonkeyPatch,
):
    calls = spotlight_answers(
        monkeypatch,
        b"/Users/me/Downloads/movements.txt\0/Users/me/old movements.txt.bak\0"
        b"/Users/me/Documents/bank/movements.txt\0",
    )

    assert spotlight("movements.txt") == [
        Path("/Users/me/Downloads/movements.txt"),
        Path("/Users/me/Documents/bank/movements.txt"),
    ]
    assert calls == [
        ["/usr/bin/mdfind", "-0", "-onlyin", str(Path.home()), "-name", "movements.txt"]
    ]


def test_spotlight_answers_nothing_when_it_fails_or_is_not_there(monkeypatch: pytest.MonkeyPatch):
    spotlight_answers(monkeypatch, b"/Users/me/movements.txt\0", code=1)
    assert spotlight("movements.txt") == []

    def hangs(command: list[str], **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(command, 10)

    monkeypatch.setattr(imported_files.subprocess, "run", hangs)
    assert spotlight("movements.txt") == []

    monkeypatch.setattr(sys, "platform", "linux")
    assert spotlight("movements.txt") == []

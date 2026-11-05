"""Helpers shared by the `sniff` implementations of the entities."""

import contextlib
import io
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ._protocol import Match

HEAD_BYTES = 64 * 1024
HEAD_ROWS = 30


def guarded(sniff: Callable[[Path], Match], input_file: Path) -> Match:
    """Run `sniff`, turning any failure into a confidence of 0 so detection never breaks."""
    try:
        return sniff(input_file)
    except Exception as error:  # noqa: BLE001 - a file that cannot be read is not a match
        return Match(0.0, f"Could not read the file: {error}")


def suffix(input_file: Path) -> str:
    """The extension of `input_file` without the dot, lower cased: `MOVIMIENTOS.XLS` is `xls`.

    Every check of a file type goes through this, so detection, `accepts` and `parse` agree.
    """
    return input_file.suffix[1:].lower()


def wrong_suffix(input_file: Path, accepted: Sequence[str]) -> Match | None:
    if suffix(input_file) in accepted:
        return None
    return Match(0.0, f"Does not read {input_file.suffix or 'files without extension'} files")


def head(input_file: Path, size: int = HEAD_BYTES) -> bytes:
    with input_file.open("rb") as stream:
        return stream.read(size)


def first_rows(input_file: Path, limit: int = HEAD_ROWS) -> list[list[Any]]:
    import pyexcel

    return pyexcel.get_array(file_name=str(input_file.absolute()), row_limit=limit)


def first_pdf_table(input_file: Path) -> list[list[str | None]] | None:
    import pdfplumber

    # pdfminer reports harmless layout warnings on stderr, keep the terminal clean
    with contextlib.redirect_stderr(io.StringIO()), pdfplumber.open(input_file) as document:
        if not document.pages:
            return None
        return document.pages[0].extract_table()

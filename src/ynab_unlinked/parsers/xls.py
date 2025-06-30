from collections.abc import Generator, Sequence
from pathlib import Path
from typing import Any


def xls(
    input_file: Path,
    read_after_row: int = 0,
    read_after_row_like: Sequence[str] | None = None,
) -> Generator[Sequence[str]]:
    import pyexcel

    kwargs: dict[str, Any] = {"file_name": str(input_file.absolute())}

    read = False

    for idx, entry in enumerate(pyexcel.get_array(**kwargs)):
        if idx < read_after_row:
            continue

        if read_after_row_like is not None and not read:
            if entry == read_after_row_like:
                read = True
            continue

        if read:
            yield entry

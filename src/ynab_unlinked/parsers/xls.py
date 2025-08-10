from collections.abc import Generator, Sequence
from pathlib import Path
from typing import Any


def xls(
    input_file: Path,
    read_after_row: int = 0,
    read_after_row_like: Sequence[str] | None = None,
    allow_partial_match: bool = False,
) -> Generator[Sequence[str]]:
    """Reads rows from an XLS file, yielding each row as a sequence of strings.

    Skips a specified number of rows or until a matching row is found, then yields subsequent rows.
    Allows for partial or full row matching to determine where to start reading.

    Args:
        input_file: The path to the XLS file to read.
        read_after_row: The number of initial rows to skip before reading.
        read_after_row_like: A sequence of strings to match a row after which reading should begin.
        allow_partial_match: If True, allows partial matching of the row to start reading.

    Returns:
        Generator[Sequence[str]]: A generator yielding each row as a sequence of strings.
    """
    import pyexcel

    kwargs: dict[str, Any] = {"file_name": str(input_file.absolute())}

    read = False

    for idx, entry in enumerate(pyexcel.get_array(**kwargs)):
        if idx < read_after_row:
            continue

        if read_after_row_like is not None and not read:
            if allow_partial_match:
                for after_row_idx, element in enumerate(read_after_row_like):
                    if entry[after_row_idx] != element:
                        break
                else:
                    # We have completed the loop, we are in the right place
                    read = True
            elif entry == read_after_row_like:
                read = True
            continue

        if read:
            yield entry

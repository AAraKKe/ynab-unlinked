import contextlib
import io
from collections.abc import Generator, Sequence
from pathlib import Path
from typing import Any, Literal, overload

from ynab_unlinked import display
from ynab_unlinked.exceptions import ParsingError


@overload
def pdf(
    input_file: Path,
    allow_empty_columns: Literal[False] = False,
    table_settings: dict[str, Any] | None = None,
    expected_number_of_columns: int | None = None,
) -> Generator[Sequence[str]]: ...


@overload
def pdf(
    input_file: Path,
    allow_empty_columns: Literal[True] = True,
    table_settings: dict[str, Any] | None = None,
    expected_number_of_columns: int | None = None,
) -> Generator[Sequence[str | None]]: ...


def pdf(
    input_file: Path,
    allow_empty_columns: bool = False,
    table_settings: dict[str, Any] | None = None,
    expected_number_of_columns: int | None = None,
) -> Generator[Sequence[str | None]]:
    """
    Parse a pdf and extract the main table from it. The table is extracted using
    [pdfplumber](https://github.com/jsvine/pdfplumber).

    Arguments:
    - input_file (Path): the input file to parse
    - table_settings (dict[str, Any]): these are the table settings passed
      to pdfpluber (see [docs](https://github.com/jsvine/pdfplumber/tree/stable?tab=readme-ov-file#table-extraction-settings))

    The return value is a list of rows that contains a list of columns as
    list[list[str]]
    """
    import pdfplumber

    # Capture stderr to process potential non-CropBox messages later
    # This is because the underlying pdf parsing library can generate warnings with
    # no impact that break the usage of the tool
    stderr_capture = io.StringIO()

    with contextlib.redirect_stderr(stderr_capture), pdfplumber.open(input_file) as pdf:
        for page_number, page in enumerate(pdf.pages):
            table = page.extract_table(table_settings=table_settings or {})
            if table is None:
                raise ParsingError(
                    input_file,
                    f"No transaction table was found in page {page_number}",
                )

            for row in table:
                if (
                    expected_number_of_columns is not None
                    and (n_columns := len(row)) != expected_number_of_columns
                ):
                    raise ParsingError(
                        input_file,
                        f"Expected {expected_number_of_columns} but found {n_columns}",
                    )

                if any(c is None for c in row) and not allow_empty_columns:
                    raise ParsingError(
                        input_file,
                        "Malformed Transaction Table: Expected no empty column but found at least one.",
                    )

                yield row

    if captured_output := stderr_capture.getvalue():
        cropbox_message = "CropBox missing from /Page, defaulting to MediaBox"
        if remaining_lines := [
            line for line in captured_output.strip().split("\n") if line.strip() != cropbox_message
        ]:
            remaining_output = "\n".join(remaining_lines)
            display.warning(f"Potential PDF issue reading {input_file}:\n{remaining_output}")

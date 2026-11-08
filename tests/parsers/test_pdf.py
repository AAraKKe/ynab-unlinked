import sys
import warnings
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from tests.helpers import assets
from ynab_unlinked.exceptions import ParsingError
from ynab_unlinked.parsers import pdf
from ynab_unlinked.parsers.pdf import PdfReadWarning

STATEMENT = "parsers/statement.pdf"


def test_every_row_of_every_page_is_yielded():
    rows = list(assets.read_pdf(STATEMENT))

    assert rows == [
        ["Fecha", "Concepto", "Importe"],
        ["11/07/2025\n12/07/2025", "Netflix.com\nOcio y cultura", "-19,99 €"],
        ["05/07/2025", "Recibo mes anterior", "270,74 €"],
        ["Fecha", "Concepto", "Importe"],
        ["03/07/2025\n04/07/2025", "Www.dazn.com\nOcio y cultura", "-5,00 €"],
    ]


def test_a_page_without_a_table_reports_which_page_failed():
    with pytest.raises(ParsingError) as error:
        list(assets.read_pdf("parsers/no_table.pdf"))

    assert "page 1" in error.value.message
    assert error.value.input_file == assets.path("parsers/no_table.pdf")


@pytest.mark.parametrize(
    "expected_columns",
    [
        pytest.param(2, id="fewer-columns-than-the-table-has"),
        pytest.param(4, id="more-columns-than-the-table-has"),
    ],
)
def test_a_row_with_an_unexpected_number_of_columns_is_rejected(expected_columns: int):
    with pytest.raises(ParsingError) as error:
        list(assets.read_pdf(STATEMENT, expected_number_of_columns=expected_columns))

    assert f"Expected {expected_columns} but found 3" in error.value.message


def test_an_empty_column_is_rejected():
    # The fixture drops the border between the two last cells of a row, which is how
    # pdfplumber ends up reporting a column as None
    with pytest.raises(ParsingError) as error:
        list(assets.read_pdf("parsers/merged_cell.pdf"))

    assert "Expected no empty column" in error.value.message


def test_an_empty_column_is_kept_when_it_is_allowed():
    rows = list(assets.read_pdf("parsers/merged_cell.pdf", allow_empty_columns=True))

    assert rows[2] == ["05/07/2025", "Recibo mes anterior 270,74 €", None]


class NoisyPdf:
    """A one page pdf whose reading makes pdfplumber write `noise` on stderr."""

    def __init__(self, noise: str):
        self.noise = noise
        self.pages = [self]

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def extract_table(self, table_settings: dict[str, str]) -> list[list[str]]:
        print(self.noise, file=sys.stderr)
        return [["05/07/2025", "Recibo", "270,74 €"]]


def test_unusual_pdf_output_is_a_warning_not_a_terminal_message(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
):
    mocker.patch("pdfplumber.open", return_value=NoisyPdf("Unexpected xref entry"))

    with pytest.warns(PdfReadWarning, match="Unexpected xref entry"):
        rows = list(pdf(Path("statement.pdf")))

    assert rows == [["05/07/2025", "Recibo", "270,74 €"]]
    assert capsys.readouterr().out == ""


def test_the_harmless_cropbox_message_is_not_a_warning(mocker: MockerFixture):
    noise = "CropBox missing from /Page, defaulting to MediaBox"
    mocker.patch("pdfplumber.open", return_value=NoisyPdf(noise))

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert len(list(pdf(Path("statement.pdf")))) == 1

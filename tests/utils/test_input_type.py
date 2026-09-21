from pathlib import Path

import pytest

from ynab_unlinked.entities import InputType
from ynab_unlinked.exceptions import ParsingError
from ynab_unlinked.utils import extract_type


@pytest.mark.parametrize(
    "input_file, expected_type",
    [
        pytest.param("file.txt", InputType.TXT, id="txt"),
        pytest.param("file.csv", InputType.CSV, id="csv"),
        pytest.param("file.html", InputType.HTML, id="html"),
        pytest.param("file.xls", InputType.XLS, id="xls"),
        pytest.param("file.xlsx", InputType.XLSX, id="xlsx"),
        pytest.param("file.pdf", InputType.PDF, id="pdf"),
    ],
)
def test_valid_input_types(input_file: str, expected_type: InputType):
    assert extract_type(Path(input_file)) == expected_type


def test_an_unknown_extension_is_a_parsing_error_naming_the_accepted_formats():
    with pytest.raises(ParsingError) as error:
        extract_type(Path("file.broken"), [InputType.TXT, InputType.CSV])

    assert error.value.input_file == Path("file.broken")
    assert "txt" in error.value.message
    assert "csv" in error.value.message


def test_a_known_extension_the_caller_does_not_accept_is_a_parsing_error():
    with pytest.raises(ParsingError) as error:
        extract_type(Path("file.pdf"), [InputType.TXT, InputType.CSV])

    assert error.value.input_file == Path("file.pdf")
    assert "txt" in error.value.message
    assert "csv" in error.value.message

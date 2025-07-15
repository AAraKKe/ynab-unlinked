from pathlib import Path

import pytest

from ynab_unlinked.entities import InputType
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


def test_not_supported_input_type():
    with pytest.raises(LookupError):
        extract_type(Path("file.broken"))


def test_invalid_extension():
    with pytest.raises(AttributeError):
        extract_type(Path("file.pdf"), [InputType.TXT, InputType.CSV])

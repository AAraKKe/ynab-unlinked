import pytest

from ynab_unlinked.parsers import parse_amount


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("21.90 €", 21.90, id="a-dot-before-two-digits-is-the-decimal-separator"),
        pytest.param("21,90EUR", 21.90, id="a-comma-before-two-digits-is-the-decimal-separator"),
        pytest.param("-1.234,56 €", -1234.56, id="spanish-thousands-and-decimals"),
        pytest.param("-1,234.56 €", -1234.56, id="english-thousands-and-decimals"),
        pytest.param("12.345.678,90", 12345678.90, id="several-spanish-thousands-separators"),
        pytest.param("12,345,678.90", 12345678.90, id="several-english-thousands-separators"),
        pytest.param("1.234", 1234.0, id="a-lone-dot-before-three-digits-is-a-thousands-separator"),
        pytest.param(
            "1,234", 1234.0, id="a-lone-comma-before-three-digits-is-a-thousands-separator"
        ),
        pytest.param("5.5", 5.5, id="one-decimal-digit"),
        pytest.param("150", 150.0, id="no-separator-at-all"),
        pytest.param("-65.0", -65.0, id="a-number-the-xlsx-reader-already-converted"),
        pytest.param("0,00 €", 0.0, id="zero"),
    ],
)
def test_parse_amount(raw: str, expected: float):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw", ["Restaurante Botin", "€", ""])
def test_a_line_without_digits_is_not_an_amount(raw: str):
    with pytest.raises(ValueError, match="does not contain an amount"):
        parse_amount(raw)

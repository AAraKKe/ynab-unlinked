import pytest

from ynab_unlinked.parsers import parse_amount


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("21.90 €", 21.90, id="a-dot-before-two-digits-is-the-decimal-separator"),
        pytest.param("-€21.90", -21.90, id="the-symbol-comes-first-on-the-cobee-page"),
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


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("Restaurante Botin", id="a-payee"),
        pytest.param("€", id="the-symbol-alone"),
        pytest.param("", id="an-empty-line"),
        pytest.param("Ahorras €9.86", id="a-savings-note-that-mentions-an-amount"),
        pytest.param("12 May 2025", id="a-date"),
    ],
)
def test_a_line_that_is_not_only_an_amount_is_rejected(raw: str):
    with pytest.raises(ValueError, match="is not an amount"):
        parse_amount(raw)

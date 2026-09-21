import datetime as dt

import pytest

from tests.factories import CurrencyFormatFactory
from ynab_unlinked.formatter import Formatter


@pytest.fixture
def currency_formatter(request: pytest.FixtureRequest):
    return Formatter("DD/MM/YYYY", request.param)


def formatter_currency_parameterization() -> list:
    params = [
        pytest.param(
            CurrencyFormatFactory.build(),
            1234.56,
            "1,234.56€",
            id="default_eur_positive",
        ),
        pytest.param(
            CurrencyFormatFactory.build(),
            -1234.56,
            "-1,234.56€",
            id="default_eur_negative",
        ),
        pytest.param(
            CurrencyFormatFactory.build(),
            0,
            "0.00€",
            id="zero",
        ),
        pytest.param(
            CurrencyFormatFactory.build(symbol_first=True, currency_symbol="$", iso_code="USD"),
            -543.21,
            "-$543.21",
            id="usd_symbol_first_negative",
        ),
        pytest.param(
            CurrencyFormatFactory.build(decimal_separator=",", group_separator="."),
            987654.32,
            "987.654,32€",
            id="eur_different_separators_large_number",
        ),
        pytest.param(
            CurrencyFormatFactory.build(display_symbol=False),
            1234.56,
            "1,234.56",
            id="no_symbol",
        ),
        pytest.param(
            CurrencyFormatFactory.build(decimal_digits=3),
            1234.56,
            "1,234.560€",
            id="3_decimal_digits",
        ),
        pytest.param(
            CurrencyFormatFactory.build(group_separator=""),
            -1234.56,
            "-1234.56€",
            id="no_group_separator_negative",
        ),
        pytest.param(
            CurrencyFormatFactory.build(group_separator=" ", decimal_separator=","),
            1234.56,
            "1 234,56€",
            id="space_group_separator_comma_decimal",
        ),
    ]
    return params


@pytest.mark.parametrize(
    "currency_formatter, amount, expected_output",
    formatter_currency_parameterization(),
    indirect=["currency_formatter"],
)
def test_currency_formatter(currency_formatter: Formatter, amount: float, expected_output: str):
    assert currency_formatter.format_amount(amount) == expected_output


def formatter_milli_currency_parameterization():
    return [
        pytest.param(
            CurrencyFormatFactory.build(decimal_digits=2),
            123450,
            "123.45€",
            id="milli_eur_positive",
        ),
        pytest.param(
            CurrencyFormatFactory.build(decimal_digits=2),
            -123450,
            "-123.45€",
            id="milli_eur_negative",
        ),
        pytest.param(
            CurrencyFormatFactory.build(
                symbol_first=True, currency_symbol="$", iso_code="USD", decimal_digits=2
            ),
            -123450,
            "-$123.45",
            id="milli_usd_negative_symbol_first",
        ),
        pytest.param(
            CurrencyFormatFactory.build(decimal_digits=0),
            123567,
            "124€",
            id="milli_eur_rounding",
        ),
    ]


@pytest.mark.parametrize(
    "currency_formatter, amount, expected",
    formatter_milli_currency_parameterization(),
    indirect=["currency_formatter"],
)
def test_format_milli_currency(currency_formatter: Formatter, amount: int, expected: str):
    assert currency_formatter.format_amount_milli(amount) == expected


@pytest.mark.parametrize(
    "date_format, date_obj, expected_str",
    [
        pytest.param("YYYY/MM/DD", dt.date(2025, 12, 30), "2025/12/30", id="YYYY/MM/DD"),
        pytest.param("YYYY-MM-DD", dt.date(2025, 12, 30), "2025-12-30", id="YYYY-MM-DD"),
        pytest.param("DD-MM-YYYY", dt.date(2025, 12, 30), "30-12-2025", id="DD-MM-YYYY"),
        pytest.param("DD/MM/YYYY", dt.date(2025, 12, 30), "30/12/2025", id="DD/MM/YYYY"),
        pytest.param("DD.MM.YYYY", dt.date(2025, 12, 30), "30.12.2025", id="DD.MM.YYYY"),
        pytest.param("MM/DD/YYYY", dt.date(2025, 12, 30), "12/30/2025", id="MM/DD/YYYY"),
        pytest.param("YYYY.MM.DD", dt.date(2025, 12, 30), "2025.12.30", id="YYYY.MM.DD"),
    ],
)
def test_format_date(date_format: str, date_obj: dt.date, expected_str: str):
    currency_format = CurrencyFormatFactory.build()
    formatter = Formatter(date_format, currency_format)
    assert formatter.format_date(date_obj) == expected_str


@pytest.mark.parametrize(
    "currency_formatter, amount, expected",
    [
        pytest.param(
            CurrencyFormatFactory.build(),
            12.34,
            "[green]12.34€[/green]",
            id="a positive amount takes the positive style",
        ),
        pytest.param(
            CurrencyFormatFactory.build(),
            -12.34,
            "[red]-12.34€[/red]",
            id="a negative amount takes the negative style",
        ),
    ],
    indirect=["currency_formatter"],
)
def test_amount_is_wrapped_in_the_requested_style(
    currency_formatter: Formatter, amount: float, expected: str
):
    formatted = currency_formatter.format_amount(
        amount, positive_style="green", negative_style="red"
    )

    assert formatted == expected


@pytest.mark.xfail(
    reason=(
        "formatter.py:33 and formatter.py:36 return before the style is applied, so the "
        "reconcile balances lose their colour for budgets that hide the symbol or put it first"
    ),
    strict=True,
)
@pytest.mark.parametrize(
    "currency_formatter, expected",
    [
        pytest.param(
            CurrencyFormatFactory.build(symbol_first=True, currency_symbol="$", iso_code="USD"),
            "[green]$12.34[/green]",
            id="the symbol comes first",
        ),
        pytest.param(
            CurrencyFormatFactory.build(display_symbol=False),
            "[green]12.34[/green]",
            id="the symbol is hidden",
        ),
    ],
    indirect=["currency_formatter"],
)
def test_style_survives_every_symbol_placement(currency_formatter: Formatter, expected: str):
    assert currency_formatter.format_amount(12.34, positive_style="green") == expected

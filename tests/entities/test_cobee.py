import datetime as dt
from collections.abc import Iterable
from pathlib import Path

import pytest

from tests.helpers import assets
from tests.helpers.statements import cobee_export
from tests.helpers.types import CliRunner
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.entities.cobee.cobee import Cobee, Language, parse_date
from ynab_unlinked.exceptions import ParsingError

pytestmark = [pytest.mark.version("V4"), pytest.mark.usefixtures("config")]

EXPORT = "cobee/transactions.html"

# Heading that opens the list, wallet top up entry, and the two statuses of a transaction
# that never went through, as Cobee words them in each language.
IDENTIFIERS = {
    Language.ES: ("Transacciones", "Acumulación en tarjeta", "Anulada", "Rechazada"),
    Language.EN: ("Transactions", "Accumulation on card", "Cancelled", "Rejected"),
    Language.PT: ("Transações", "Acumulado em cartão", "Anulada", "Recusada"),
}

LANGUAGES = [pytest.param(language, id=f"in-{language.value}") for language in Language]


@pytest.fixture
def export(tmp_path: Path):
    def build(lines: Iterable[str], **kwargs: Iterable[str]) -> Path:
        input_file = tmp_path / "cobee.html"
        input_file.write_text(cobee_export(lines, **kwargs), encoding="utf-8")
        return input_file

    return build


def test_a_saved_page_becomes_transactions():
    transactions = Cobee(Language.ES).parse(assets.path(EXPORT))

    assert [(t.date, t.payee, t.amount) for t in transactions] == [
        (dt.date(2025, 5, 15), "Restaurante Botin", -34.80),
        (dt.date(2025, 5, 2), "Cafeteria Lolina", -2.50),
    ]


@pytest.mark.parametrize("language", LANGUAGES)
def test_only_the_lines_below_the_transactions_heading_are_read(export, language: Language):
    heading, *_ = IDENTIFIERS[language]
    # The page shows the available balance above the heading, in the same shape as an amount
    input_file = export([heading, "15 May 2025", "Restaurante Botin", "-34.80 €"])

    transactions = Cobee(language).parse(input_file)

    assert [(t.date, t.payee, t.amount) for t in transactions] == [
        (dt.date(2025, 5, 15), "Restaurante Botin", -34.80)
    ]


def test_a_date_heading_applies_to_every_transaction_below_it(export):
    input_file = export(
        [
            "Transacciones",
            "15 May 2025",
            "Restaurante Botin",
            "-34.80 €",
            "Mercadona",
            "-12.05 €",
            "2 May 2025",
            "Cafeteria Lolina",
            "-2.50 €",
        ]
    )

    transactions = Cobee(Language.ES).parse(input_file)

    assert [(t.date.day, t.payee) for t in transactions] == [
        (15, "Restaurante Botin"),
        (15, "Mercadona"),
        (2, "Cafeteria Lolina"),
    ]


@pytest.mark.parametrize("language", LANGUAGES)
def test_money_added_to_the_card_is_not_a_transaction(export, language: Language):
    """Top ups come from payroll, importing them would count the same money twice."""
    heading, accumulation, *_ = IDENTIFIERS[language]
    input_file = export(
        [
            heading,
            "1 May 2025",
            accumulation,
            "150.00 €",
            "Restaurante Botin",
            "-34.80 €",
        ]
    )

    transactions = Cobee(language).parse(input_file)

    assert [t.payee for t in transactions] == ["Restaurante Botin"]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize(
    "status",
    [pytest.param(2, id="cancelled"), pytest.param(3, id="rejected")],
)
def test_a_transaction_that_did_not_go_through_is_dropped(export, language: Language, status: int):
    heading, *_ = IDENTIFIERS[language]
    input_file = export(
        [
            heading,
            "15 May 2025",
            "Restaurante Botin",
            "-34.80 €",
            "Mercadona",
            "-12.05 €",
            IDENTIFIERS[language][status],
        ]
    )

    transactions = Cobee(language).parse(input_file)

    assert [t.payee for t in transactions] == ["Restaurante Botin"]


@pytest.mark.parametrize(
    ("lines", "expected_payees"),
    [
        pytest.param(
            [
                "Transacciones",
                "15 May 2025",
                "Restaurante Botin",
                "-34.80 €",
                "Preautorizacion",
                "0.00 €",
                "Rechazada",
            ],
            ["Restaurante Botin"],
            id="the-rejected-charge-above-is-a-zero-that-was-never-imported",
        ),
        pytest.param(
            [
                "Transacciones",
                "15 May 2025",
                "Preautorizacion",
                "0.00 €",
                "Rechazada",
                "Mercadona",
                "-12.05 €",
            ],
            ["Mercadona"],
            id="the-rejected-charge-is-the-first-entry-of-the-list",
        ),
    ],
)
def test_a_marker_never_drops_a_transaction_it_does_not_follow(
    export, lines: list[str], expected_payees: list[str]
):
    """A rejected charge of 0.00 € is skipped as a zero, so its marker has nothing to drop."""
    transactions = Cobee(Language.ES).parse(export(lines))

    assert [t.payee for t in transactions] == expected_payees


def test_a_zero_amount_is_not_imported(export):
    input_file = export(
        ["Transacciones", "15 May 2025", "Preautorizacion", "0.00 €", "Mercadona", "-12.05 €"]
    )

    transactions = Cobee(Language.ES).parse(input_file)

    assert [t.payee for t in transactions] == ["Mercadona"]


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        pytest.param(
            ["Transacciones", "Restaurante Botin", "-34.80 €"],
            "without a date",
            id="an-amount-before-any-date",
        ),
        pytest.param(
            ["Transacciones", "15 Foo 2025", "Restaurante Botin", "-34.80 €"],
            "The month Foo is not valid",
            id="an-unknown-month-name",
        ),
    ],
)
def test_a_page_that_cannot_be_read_is_a_parsing_error(export, lines: list[str], message: str):
    input_file = export(lines)

    with pytest.raises(ParsingError, match=message) as error:
        Cobee(Language.ES).parse(input_file)

    assert error.value.input_file == input_file


def test_the_load_command_reports_a_page_that_cannot_be_read_without_a_traceback(
    export, yul: CliRunner
):
    input_file = export(["Transacciones", "15 Foo 2025", "Restaurante Botin", "-34.80 €"])

    result = yul("load", "--show", "cobee", "--lang", "es", str(input_file))

    assert result.exit_code == 1
    assert "The month Foo is not valid" in result.output
    assert "Traceback" not in result.output
    assert not isinstance(result.exception, ValueError)


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("-1,234.56 €", id="english-separators-as-the-cobee-page-writes-them"),
        pytest.param("-1.234,56 €", id="spanish-separators"),
    ],
)
def test_an_amount_over_a_thousand_euros_is_imported(export, raw: str):
    input_file = export(["Transacciones", "15 May 2025", "Guarderia", raw])

    transactions = Cobee(Language.ES).parse(input_file)

    assert [t.amount for t in transactions] == [-1234.56]


def test_a_dot_is_the_decimal_separator_on_the_cobee_page(export):
    # Regression: stripping every dot as a thousands separator turned 21.90 into 2190
    input_file = export(["Transacciones", "15 May 2025", "Cafeteria", "-€21.90"])

    transactions = Cobee(Language.ES).parse(input_file)

    assert [t.amount for t in transactions] == [-21.90]


def test_the_savings_note_under_a_purchase_is_not_a_transaction(export):
    # Regression: every purchase is followed by how it was paid and how much tax it saved.
    # Parsing "Ahorras €9.86" as an amount imported a fake inflow per purchase
    input_file = export(
        [
            "Transacciones",
            "1 Oct 2026",
            "Glovo 01OCT M1Z4XTCK",
            "-€21.90",
            "Pagado de tu salario",
            "Ahorras €9.86",
            "GRUPO FIKAFE S.L.",
            "-€9.90",
            "Pago Compartido",
            "Ahorras €1.78",
        ]
    )

    transactions = Cobee(Language.ES).parse(input_file)

    assert [(t.payee, t.amount) for t in transactions] == [
        ("Glovo 01OCT M1Z4XTCK", -21.90),
        ("GRUPO FIKAFE S.L.", -9.90),
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("15 May 2025", dt.date(2025, 5, 15), id="a-day-in-the-middle-of-the-month"),
        pytest.param("1 Jan 2024", dt.date(2024, 1, 1), id="a-single-digit-day"),
        pytest.param("31 Dec 2024", dt.date(2024, 12, 31), id="the-last-day-of-the-year"),
        pytest.param("Restaurante Botin", None, id="a-payee-is-not-a-date"),
        pytest.param("15/05/2025", None, id="a-numeric-date-is-not-the-cobee-format"),
    ],
)
def test_dates_are_read_with_english_month_names(raw: str, expected: dt.date | None):
    assert parse_date(raw) == expected


def test_an_unknown_month_name_is_reported():
    with pytest.raises(ValueError, match="Foo"):
        parse_date("15 Foo 2025")


def test_the_load_command_shows_the_transactions_of_the_saved_page(yul: CliRunner):
    result = yul("load", "--show", "cobee", str(assets.path(EXPORT)))

    assert result.exit_code == 0, result.output
    assert "Restaurante Botin" in result.output
    assert "Cafeteria Lolina" in result.output
    assert "Acumulación" not in result.output


def test_the_load_command_needs_the_language_of_the_export(tmp_path: Path, yul: CliRunner):
    """The headings are localised, so an export read with the wrong language finds nothing."""
    input_file = tmp_path / "cobee.html"
    input_file.write_text(
        cobee_export(["Transactions", "15 May 2025", "Restaurante Botin", "-34.80 €"]),
        encoding="utf-8",
    )

    result = yul("load", "--show", "cobee", "--lang", "es", str(input_file))

    assert result.exit_code == 0, result.output
    assert "Restaurante Botin" not in result.output


@pytest.mark.parametrize(
    ("arguments", "found"),
    [
        pytest.param([], True, id="the-language-saved-for-the-bank"),
        pytest.param(["--lang", "es"], False, id="the-command-line-wins-over-the-saved-one"),
    ],
)
def test_the_load_command_reads_the_language_saved_for_the_bank(
    tmp_path: Path, yul: CliRunner, config_v4: LatestConfig, arguments: list[str], found: bool
):
    config_v4.loaders["cobee"].options = {"language": "en"}
    config_v4.save()
    input_file = tmp_path / "cobee.html"
    input_file.write_text(
        cobee_export(["Transactions", "15 May 2025", "Restaurante Botin", "-34.80 €"]),
        encoding="utf-8",
    )

    result = yul("load", "--show", "cobee", *arguments, str(input_file))

    assert result.exit_code == 0, result.output
    assert ("Restaurante Botin" in result.output) is found


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param([], id="read-from-the-page"),
        pytest.param(["--language", "en"], id="the-long-name"),
        pytest.param(["-l", "en"], id="the-short-name"),
    ],
)
def test_the_load_command_reads_a_page_in_another_language(
    tmp_path: Path, yul: CliRunner, arguments: list[str]
):
    input_file = tmp_path / "cobee.html"
    input_file.write_text(
        cobee_export(["Transactions", "15 May 2025", "Restaurante Botin", "-34.80 €"]),
        encoding="utf-8",
    )

    result = yul("load", "--show", "cobee", *arguments, str(input_file))

    assert result.exit_code == 0, result.output
    assert "Restaurante Botin" in result.output

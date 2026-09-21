import datetime as dt
from collections.abc import Iterable
from pathlib import Path

import pytest

from tests.helpers import assets
from tests.helpers.statements import cobee_export
from tests.helpers.types import CliRunner
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.entities.cobee.cobee import Cobee, CobeeContext, Language, parse_date

pytestmark = [pytest.mark.version("V3"), pytest.mark.usefixtures("config")]

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
def cobee_context(context_obj: YnabUnlinkedContext):
    def build(language: Language = Language.ES) -> YnabUnlinkedContext[CobeeContext]:
        context_obj.extras = CobeeContext(language=language)
        return context_obj

    return build


@pytest.fixture
def export(tmp_path: Path):
    def build(lines: Iterable[str], **kwargs: Iterable[str]) -> Path:
        input_file = tmp_path / "cobee.html"
        input_file.write_text(cobee_export(lines, **kwargs), encoding="utf-8")
        return input_file

    return build


def test_a_saved_page_becomes_transactions(cobee_context):
    transactions = Cobee().parse(assets.path(EXPORT), cobee_context())

    assert [(t.date, t.payee, t.amount) for t in transactions] == [
        (dt.date(2025, 5, 15), "Restaurante Botin", -34.80),
        (dt.date(2025, 5, 2), "Cafeteria Lolina", -2.50),
    ]


@pytest.mark.parametrize("language", LANGUAGES)
def test_only_the_lines_below_the_transactions_heading_are_read(
    export, cobee_context, language: Language
):
    heading, *_ = IDENTIFIERS[language]
    # The page shows the available balance above the heading, in the same shape as an amount
    input_file = export([heading, "15 May 2025", "Restaurante Botin", "-34,80 €"])

    transactions = Cobee().parse(input_file, cobee_context(language))

    assert [(t.date, t.payee, t.amount) for t in transactions] == [
        (dt.date(2025, 5, 15), "Restaurante Botin", -34.80)
    ]


def test_a_date_heading_applies_to_every_transaction_below_it(export, cobee_context):
    input_file = export(
        [
            "Transacciones",
            "15 May 2025",
            "Restaurante Botin",
            "-34,80 €",
            "Mercadona",
            "-12,05 €",
            "2 May 2025",
            "Cafeteria Lolina",
            "-2,50 €",
        ]
    )

    transactions = Cobee().parse(input_file, cobee_context())

    assert [(t.date.day, t.payee) for t in transactions] == [
        (15, "Restaurante Botin"),
        (15, "Mercadona"),
        (2, "Cafeteria Lolina"),
    ]


@pytest.mark.parametrize("language", LANGUAGES)
def test_money_added_to_the_card_is_not_a_transaction(export, cobee_context, language: Language):
    """Top ups come from payroll, importing them would count the same money twice."""
    heading, accumulation, *_ = IDENTIFIERS[language]
    input_file = export(
        [
            heading,
            "1 May 2025",
            accumulation,
            "150,00 €",
            "Restaurante Botin",
            "-34,80 €",
        ]
    )

    transactions = Cobee().parse(input_file, cobee_context(language))

    assert [t.payee for t in transactions] == ["Restaurante Botin"]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize(
    "status",
    [pytest.param(2, id="cancelled"), pytest.param(3, id="rejected")],
)
def test_a_transaction_that_did_not_go_through_is_dropped(
    export, cobee_context, language: Language, status: int
):
    heading, *_ = IDENTIFIERS[language]
    input_file = export(
        [
            heading,
            "15 May 2025",
            "Restaurante Botin",
            "-34,80 €",
            "Mercadona",
            "-12,05 €",
            IDENTIFIERS[language][status],
        ]
    )

    transactions = Cobee().parse(input_file, cobee_context(language))

    assert [t.payee for t in transactions] == ["Restaurante Botin"]


@pytest.mark.parametrize(
    ("lines", "expected_payees"),
    [
        pytest.param(
            [
                "Transacciones",
                "15 May 2025",
                "Restaurante Botin",
                "-34,80 €",
                "Preautorizacion",
                "0,00 €",
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
                "0,00 €",
                "Rechazada",
                "Mercadona",
                "-12,05 €",
            ],
            ["Mercadona"],
            id="the-rejected-charge-is-the-first-entry-of-the-list",
        ),
    ],
)
def test_a_marker_never_drops_a_transaction_it_does_not_follow(
    export, cobee_context, lines: list[str], expected_payees: list[str]
):
    """A rejected charge of 0,00 € is skipped as a zero, so its marker has nothing to drop."""
    transactions = Cobee().parse(export(lines), cobee_context())

    assert [t.payee for t in transactions] == expected_payees


def test_a_zero_amount_is_not_imported(export, cobee_context):
    input_file = export(
        ["Transacciones", "15 May 2025", "Preautorizacion", "0,00 €", "Mercadona", "-12,05 €"]
    )

    transactions = Cobee().parse(input_file, cobee_context())

    assert [t.payee for t in transactions] == ["Mercadona"]


def test_an_amount_before_any_date_is_rejected(export, cobee_context):
    input_file = export(["Transacciones", "Restaurante Botin", "-34,80 €"])

    with pytest.raises(ValueError, match="not valid"):
        Cobee().parse(input_file, cobee_context())


def test_an_amount_over_a_thousand_euros_is_imported(export, cobee_context):
    input_file = export(["Transacciones", "15 May 2025", "Guarderia", "-1.234,56 €"])

    transactions = Cobee().parse(input_file, cobee_context())

    assert [t.amount for t in transactions] == [-1234.56]


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
        cobee_export(["Transactions", "15 May 2025", "Restaurante Botin", "-34,80 €"]),
        encoding="utf-8",
    )

    result = yul("load", "--show", "cobee", "--lang", "es", str(input_file))

    assert result.exit_code == 0, result.output
    assert "Restaurante Botin" not in result.output

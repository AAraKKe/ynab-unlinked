import datetime as dt
from collections.abc import Iterable
from pathlib import Path
from typing import cast

import pytest

from tests.helpers import assets
from tests.helpers.statements import sabadell_statement
from tests.helpers.types import CliRunner
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.entities.sabadell.sabadell import ANCHOR_LINE, SabadellParser
from ynab_unlinked.exceptions import ParsingError
from ynab_unlinked.models import Transaction

pytestmark = pytest.mark.version("V3")

TXT_STATEMENT = "sabadell/movements.txt"
XLS_STATEMENT = "sabadell/movements.xls"


@pytest.fixture
def statement(tmp_path: Path):
    def build(lines: Iterable[str], **kwargs: Iterable[str]) -> Path:
        input_file = tmp_path / "sabadell.txt"
        # Sabadell exports its txt statement in the Windows Spanish code page
        input_file.write_text(sabadell_statement(lines, **kwargs), encoding="cp1252")
        return input_file

    return build


def parse(input_file: Path, year: int = 2025) -> list[Transaction]:
    # The parser does not read anything from the context
    return SabadellParser(year=year).parse(input_file, cast(YnabUnlinkedContext, None))


def test_a_txt_statement_becomes_transactions():
    transactions = parse(assets.path(TXT_STATEMENT))

    # The 22/04 operation is still pending, marked with (1), and is not imported
    assert [(t.date, t.payee, t.amount) for t in transactions] == [
        (dt.date(2025, 4, 25), "Barberia Docklands", -48.00),
        (dt.date(2025, 4, 20), "Devolucion Compra", 12.50),
        (dt.date(2025, 4, 19), "Viaje A Japon", -1212.16),
    ]


@pytest.mark.parametrize(
    ("line", "payee", "amount"),
    [
        pytest.param(
            "25/01|MERCADONA|MADRID|20,00EUR",
            "Mercadona",
            -20.00,
            id="a-purchase-is-an-outflow",
        ),
        pytest.param(
            "25/01|DEVOLUCION|MADRID|-10,50EUR",
            "Devolucion",
            10.50,
            id="a-negative-amount-is-a-refund-and-becomes-an-inflow",
        ),
        pytest.param(
            "25/01|VIAJE A JAPON|TOKIO|1.212,16EUR",
            "Viaje A Japon",
            -1212.16,
            id="the-dot-is-a-thousands-separator",
        ),
        pytest.param(
            "25/01|HERENCIA|MADRID|-12.345.678,90EUR",
            "Herencia",
            12345678.90,
            id="several-thousands-separators-are-removed",
        ),
        pytest.param(
            "25/01|UBER   *EATS|HELP.UBER.COM|26,90EUR(2)",
            "Uber   *Eats",
            -26.90,
            id="a-settled-transaction-is-marked-with-a-2",
        ),
    ],
)
def test_a_statement_line_becomes_a_transaction(statement, line: str, payee: str, amount: float):
    transactions = parse(statement([line]))

    assert [(t.payee, t.amount) for t in transactions] == [(payee, amount)]


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("22/04|JUSTEAT|MADRID|18,00EUR(1)", id="a-pending-transaction"),
        pytest.param("FECHA|CONCEPTO|LOCALIDAD|IMPORTE", id="a-repeated-table-header"),
        pytest.param("TOTAL OPERACIONES|929,52 EUR", id="the-total-of-the-statement"),
        pytest.param("(1)Movimientos pendientes de confirmar", id="the-legend-of-the-marks"),
        pytest.param("25/4|MERCADONA|MADRID|20,00EUR", id="a-date-without-a-leading-zero"),
    ],
)
def test_lines_that_are_not_transactions_are_ignored(statement, line: str):
    assert parse(statement([line])) == []


def test_nothing_is_read_before_the_credit_limit_line(statement):
    input_file = statement(
        ["25/04|AFTER THE LIMIT|MADRID|10,00EUR"],
        header=["25/04|BEFORE THE LIMIT|MADRID|48,00EUR", ANCHOR_LINE],
    )

    assert [t.payee for t in parse(input_file)] == ["After The Limit"]


def test_december_moves_to_the_previous_year_when_january_is_also_in_the_file(statement):
    """Sabadell writes no year, so a statement spanning the new year has to be inferred."""
    input_file = statement(
        ["02/01|JAN TRANSACTION|CITY|10,00EUR", "31/12|DEC TRANSACTION|CITY|20,00EUR"]
    )

    assert [t.date for t in parse(input_file, year=2025)] == [
        dt.date(2025, 1, 2),
        dt.date(2024, 12, 31),
    ]


def test_a_statement_that_stays_in_one_month_keeps_the_year_it_was_given(statement):
    input_file = statement(["02/01|JAN TRANSACTION|CITY|10,00EUR"])

    assert [t.date for t in parse(input_file, year=2025)] == [dt.date(2025, 1, 2)]


def test_an_xls_statement_becomes_transactions():
    transactions = parse(assets.path(XLS_STATEMENT))

    # The 29/06 operation is pending, its currency cell reads EUR(1), and is not imported
    assert [(t.date, t.payee, t.amount) for t in transactions] == [
        (dt.date(2025, 6, 28), "Los Diamantes", -34.80),
        (dt.date(2025, 6, 27), "Devolucion Compra", 12.50),
        (dt.date(2025, 6, 26), "Uber   *Eats", -1212.16),
    ]


@pytest.mark.parametrize(
    "statement_file",
    [
        pytest.param(XLS_STATEMENT, id="the-file-ends-with-a-debit-section"),
        pytest.param(
            "sabadell/movements_without_debit.xls", id="the-file-has-no-debit-section-at-all"
        ),
    ],
)
def test_only_credit_movements_are_imported(statement_file: str):
    """Debit movements close the file and belong to the account, not to the credit card."""
    transactions = parse(assets.path(statement_file))

    assert [t.payee for t in transactions] == [
        "Los Diamantes",
        "Devolucion Compra",
        "Uber   *Eats",
    ]


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param(".pdf", id="a-known-format-this-entity-does-not-read"),
        pytest.param(".xlsx", id="the-modern-excel-format"),
        pytest.param(".doc", id="a-format-the-tool-knows-nothing-about"),
    ],
)
def test_a_file_sabadell_cannot_read_is_reported(tmp_path: Path, suffix: str):
    input_file = tmp_path / f"statement{suffix}"
    input_file.touch()

    with pytest.raises(ParsingError) as error:
        parse(input_file)

    assert "txt" in error.value.message
    assert "xls" in error.value.message


def test_the_load_command_shows_the_transactions_of_the_statement(yul: CliRunner):
    result = yul("load", "--show", "sabadell", str(assets.path(TXT_STATEMENT)))

    assert result.exit_code == 0, result.output
    assert "Barberia Docklands" in result.output
    assert "Justeat" not in result.output


@pytest.mark.parametrize(
    ("arguments", "expected_year"),
    [
        pytest.param(["-y", "2023"], "2023", id="the-year-given-in-the-command-line"),
        pytest.param([], "2025", id="the-current-year-when-none-is-given"),
    ],
)
def test_the_load_command_dates_the_statement(
    yul: CliRunner, today: dt.datetime, arguments: list[str], expected_year: str
):
    result = yul(
        "load",
        "--show",
        "sabadell",
        *arguments,
        str(assets.path(TXT_STATEMENT)),
        env={"COLUMNS": "200"},
    )

    assert result.exit_code == 0, result.output
    assert f"25/04/{expected_year}" in result.output

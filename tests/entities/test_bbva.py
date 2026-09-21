import datetime as dt
from pathlib import Path
from uuid import UUID

import pytest

from tests.factories import AccountFactory
from tests.helpers import assets
from tests.helpers.types import CliRunner
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.entities.bbva.bbva import BBVA
from ynab_unlinked.exceptions import ParsingError

pytestmark = [pytest.mark.version("V3"), pytest.mark.usefixtures("config")]

XLSX_STATEMENT = "bbva/bbva.xlsx"
PDF_STATEMENT = "bbva/bbva.pdf"


@pytest.fixture
def account_prompt(ynab_api: YnabClientStub):
    """BBVA has no entry in the test config, so the command asks which account to use."""
    accounts = [
        AccountFactory(id=UUID(int=20), name="Old Card", closed=True),
        AccountFactory(name="BBVA Credit Card"),
    ]
    ynab_api.api("accounts").get_accounts.return_value.data.accounts = accounts


@pytest.mark.parametrize(
    ("position", "date", "payee", "amount"),
    [
        pytest.param(
            0, dt.date(2025, 7, 11), "Netflix.com", -19.99, id="the-first-charge-of-the-statement"
        ),
        pytest.param(
            4, dt.date(2025, 7, 5), "Recibo mes anterior", 270.74, id="the-monthly-card-payment"
        ),
        pytest.param(
            16,
            dt.date(2025, 5, 26),
            "Com. emision y mant t. credito",
            -65.0,
            id="a-whole-number-amount-read-as-an-integer",
        ),
    ],
)
def test_an_xlsx_statement_becomes_transactions(
    context_obj: YnabUnlinkedContext, position: int, date: dt.date, payee: str, amount: float
):
    transactions = BBVA().parse(assets.path(XLSX_STATEMENT), context_obj)

    assert len(transactions) == 17
    assert (transactions[position].date, transactions[position].payee) == (date, payee)
    assert transactions[position].amount == amount


def test_a_pdf_statement_becomes_transactions(context_obj: YnabUnlinkedContext):
    transactions = BBVA().parse(assets.path(PDF_STATEMENT), context_obj)

    # The date and the concept carry a second line, the settlement date and the spending
    # category, and neither the header repeated on page two nor the total are transactions
    assert [(t.date, t.payee, t.amount) for t in transactions] == [
        (dt.date(2025, 7, 11), "Netflix.com", -19.99),
        (dt.date(2025, 7, 9), "Bonificacion pack viajes", 2.45),
        (dt.date(2025, 7, 5), "Recibo mes anterior", 270.74),
        (dt.date(2025, 7, 3), "Www.dazn.com", -5.00),
    ]


def test_a_pdf_without_a_transaction_table_is_reported(context_obj: YnabUnlinkedContext):
    with pytest.raises(ParsingError) as error:
        BBVA().parse(assets.path("parsers/no_table.pdf"), context_obj)

    assert "No transaction table" in error.value.message


def test_a_pdf_row_with_a_blank_cell_is_not_a_transaction(context_obj: YnabUnlinkedContext):
    transactions = BBVA().parse(assets.path("bbva/bbva_blank_cell.pdf"), context_obj)

    assert [t.payee for t in transactions] == ["Netflix.com"]


def test_a_charge_over_a_thousand_euros_is_imported(context_obj: YnabUnlinkedContext):
    transactions = BBVA().parse(assets.path("bbva/bbva_large_amount.pdf"), context_obj)

    assert [t.amount for t in transactions] == [-1234.56]


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param(".txt", id="a-known-format-this-entity-does-not-read"),
        pytest.param(".xls", id="the-legacy-excel-format"),
        pytest.param(".doc", id="a-format-the-tool-knows-nothing-about"),
    ],
)
def test_a_file_bbva_cannot_read_is_reported(
    context_obj: YnabUnlinkedContext, tmp_path: Path, suffix: str
):
    input_file = tmp_path / f"statement{suffix}"
    input_file.touch()

    with pytest.raises(ParsingError) as error:
        BBVA().parse(input_file, context_obj)

    assert "pdf" in error.value.message
    assert "xlsx" in error.value.message


def test_the_load_command_asks_for_an_account_and_shows_the_transactions(
    yul: CliRunner, account_prompt
):
    result = yul(
        "load",
        "--show",
        "bbva",
        str(assets.path(PDF_STATEMENT)),
        input="1\n",
        env={"COLUMNS": "200"},
    )

    assert result.exit_code == 0, result.output
    # Closed accounts are not offered, so the only choice is the open one
    assert "Old Card" not in result.output
    assert "Account selected: BBVA Credit Card" in result.output
    assert "11/07/2025" in result.output
    assert "Netflix.com" in result.output


def test_the_load_command_reports_a_statement_it_cannot_parse(yul: CliRunner, account_prompt):
    result = yul(
        "load",
        "bbva",
        str(assets.path("parsers/no_table.pdf")),
        input="1\n",
        env={"COLUMNS": "200"},
    )

    assert result.exit_code == 1
    assert "No transaction table was found" in result.output

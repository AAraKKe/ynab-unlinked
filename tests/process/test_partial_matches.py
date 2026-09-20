from pathlib import Path

import pytest
from ynab import TransactionClearedStatus

from tests.factories import TransactionDetailFactory, TransactionFactory
from tests.helpers.types import CliRunner, LoadEntityCallback
from tests.helpers.ynab_api import YnabClientStub
from tests.process.builders import THREE_DAYS_AGO, TODAY, saved_config, write_config

pytestmark = pytest.mark.version("V2")

BANK_PAYEE = "ES0021 CARD PURCHASE 4456"
YNAB_PAYEE = "Starbucks Coffee"
AMOUNT = -12.34


def ynab_side(cleared: TransactionClearedStatus):
    return TransactionDetailFactory(
        var_date=THREE_DAYS_AGO,
        amount=round(AMOUNT * 1000),
        payee_name=YNAB_PAYEE,
        cleared=cleared,
    )


def bank_side():
    return TransactionFactory(date=THREE_DAYS_AGO, payee=BANK_PAYEE, amount=AMOUNT)


@pytest.fixture
def a_partial_match(existing_in_ynab, load_entity: LoadEntityCallback):
    """An export whose only transaction matches an uncleared YNAB one under another payee."""
    existing_in_ynab([ynab_side(TransactionClearedStatus.UNCLEARED)])
    load_entity(TODAY, [bank_side()])


@pytest.mark.parametrize(
    ("answer", "expected_rules"),
    [
        pytest.param("y", {YNAB_PAYEE: {BANK_PAYEE}}, id="accepting remembers the payee naming"),
        pytest.param("n", {}, id="rejecting leaves no naming rule behind"),
    ],
)
def test_the_answer_to_a_partial_match_decides_the_payee_rules(
    config_file: Path,
    yul: CliRunner,
    a_partial_match,
    created_transactions,
    answer: str,
    expected_rules: dict,
):
    result = yul("load test", input=f"{answer}\ny\n")

    assert result.exit_code == 0, result.output
    assert saved_config(config_file).payee_rules == expected_rules
    # Either way the transaction is uploaded, because the YNAB side is still uncleared
    assert [t.payee_name for t in created_transactions()] == [BANK_PAYEE]


def test_a_partial_match_is_uploaded_as_cleared(
    config_file: Path, yul: CliRunner, a_partial_match, created_transactions
):
    result = yul("load test", input="y\ny\n")

    assert result.exit_code == 0, result.output
    assert [t.cleared for t in created_transactions()] == [TransactionClearedStatus.CLEARED]


def test_a_known_payee_rule_matches_without_asking(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    ynab: YnabClientStub,
    existing_in_ynab,
):
    write_config(config_file, payee_rules={YNAB_PAYEE: [BANK_PAYEE]})
    existing_in_ynab([ynab_side(TransactionClearedStatus.CLEARED)])
    load_entity(TODAY, [bank_side()])

    result = yul("load test")

    assert result.exit_code == 0, result.output
    assert "Nothing to do" in result.output
    ynab.api("transactions").create_transaction.assert_not_called()


def test_a_cleared_ynab_transaction_never_reaches_the_partial_match_prompt(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    ynab: YnabClientStub,
    existing_in_ynab,
):
    existing_in_ynab([ynab_side(TransactionClearedStatus.CLEARED)])
    load_entity(TODAY, [bank_side()])

    result = yul("load test")

    assert result.exit_code == 0, result.output
    assert "Partial Matches" not in result.output
    ynab.api("transactions").create_transaction.assert_not_called()

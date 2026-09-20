from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from tests.factories import AccountFactory, TransactionFactory
from tests.helpers.types import CliRunner, LoadEntityCallback
from tests.helpers.ynab_api import YnabClientStub
from tests.process.builders import (
    ACCOUNT_ID,
    CLOSED_ACCOUNT_ID,
    OTHER_ACCOUNT_ID,
    THREE_DAYS_AGO,
    TODAY,
    saved_config,
    write_config,
)
from ynab_unlinked.process import get_or_prompt_account_id

pytestmark = pytest.mark.version("V2")


@pytest.fixture
def accounts_in_ynab(ynab: YnabClientStub):
    def setup(*accounts) -> None:
        ynab.api("accounts").get_accounts.return_value.data.accounts = list(accounts)

    return setup


def test_a_known_entity_reuses_its_account_without_asking(
    config_file: Path, ynab: YnabClientStub, mocker: MockerFixture
):
    question = mocker.patch("ynab_unlinked.process.question")

    account_id = get_or_prompt_account_id(saved_config(config_file), "test", force_prompt=False)

    assert account_id == ACCOUNT_ID
    question.assert_not_called()


def test_an_unknown_entity_is_offered_only_the_open_accounts(
    config_file: Path, accounts_in_ynab, mocker: MockerFixture
):
    accounts_in_ynab(
        AccountFactory(id=ACCOUNT_ID, name="Checking"),
        AccountFactory(id=CLOSED_ACCOUNT_ID, name="Old Savings", closed=True),
        AccountFactory(id=OTHER_ACCOUNT_ID, name="Credit Card"),
    )
    question = mocker.patch("ynab_unlinked.process.question", return_value="2")

    account_id = get_or_prompt_account_id(saved_config(config_file), "newbank", force_prompt=False)

    assert question.call_args.kwargs["choices"] == ["1", "2"]
    assert account_id == OTHER_ACCOUNT_ID
    assert saved_config(config_file).entities["newbank"].account_id == OTHER_ACCOUNT_ID


def test_a_forced_prompt_does_not_persist_the_chosen_account(
    config_file: Path, accounts_in_ynab, mocker: MockerFixture
):
    accounts_in_ynab(AccountFactory(id=OTHER_ACCOUNT_ID, name="Credit Card"))
    mocker.patch("ynab_unlinked.process.question", return_value="1")

    account_id = get_or_prompt_account_id(saved_config(config_file), "test", force_prompt=True)

    assert account_id == OTHER_ACCOUNT_ID
    assert saved_config(config_file).entities["test"].account_id == ACCOUNT_ID


def test_a_first_time_entity_is_registered_before_processing(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    accounts_in_ynab,
    mocker: MockerFixture,
):
    write_config(config_file, entities={})
    accounts_in_ynab(AccountFactory(id=ACCOUNT_ID, name="Checking"))
    mocker.patch("ynab_unlinked.process.question", return_value="1")
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO)])

    result = yul("load test", input="y\n")

    assert result.exit_code == 0, result.output
    assert saved_config(config_file).entities["test"].account_id == ACCOUNT_ID


@pytest.mark.xfail(
    reason=(
        "process.py:129 reads config.entities[entity] but get_or_prompt_account_id only stores "
        "the entity when force_prompt is False, so `yul load -a` on a new entity raises KeyError"
    ),
    strict=True,
)
def test_choosing_an_account_for_an_unknown_entity_does_not_crash(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    accounts_in_ynab,
    mocker: MockerFixture,
):
    write_config(config_file, entities={})
    accounts_in_ynab(AccountFactory(id=ACCOUNT_ID, name="Checking"))
    mocker.patch("ynab_unlinked.process.question", return_value="1")
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO)])

    result = yul("load --acount --show test")

    assert result.exit_code == 0, result.output

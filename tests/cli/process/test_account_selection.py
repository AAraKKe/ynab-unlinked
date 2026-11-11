from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from tests.cli.process.builders import (
    ACCOUNT_ID,
    CLOSED_ACCOUNT_ID,
    OTHER_ACCOUNT_ID,
    THREE_DAYS_AGO,
    TODAY,
    saved_config,
    write_config,
)
from tests.factories import AccountFactory, TransactionFactory
from tests.helpers.types import CliRunner, LoadEntityCallback
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.cli.process import get_or_prompt_account_id
from ynab_unlinked.config import update_config

pytestmark = pytest.mark.version("V4")


@pytest.fixture
def accounts_in_ynab(ynab: YnabClientStub):
    def setup(*accounts) -> None:
        ynab.api("accounts").get_accounts.return_value.data.accounts = list(accounts)

    return setup


def test_a_known_entity_reuses_its_account_without_asking(
    config_file: Path, ynab: YnabClientStub, mocker: MockerFixture
):
    question = mocker.patch("ynab_unlinked.cli.process.question")

    account_id = get_or_prompt_account_id(saved_config(config_file), "test", force_prompt=False)

    assert account_id == ACCOUNT_ID
    question.assert_not_called()


@pytest.mark.parametrize(
    ("saved", "reason"),
    [
        (AccountFactory(id=ACCOUNT_ID, closed=True), "is closed in YNAB"),
        (AccountFactory(id=ACCOUNT_ID, deleted=True), "is no longer in the budget"),
        (None, "is no longer in the budget"),
    ],
    ids=["closed", "deleted", "not in the budget"],
)
def test_a_saved_account_gone_from_ynab_is_asked_for_again_and_replaced(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    accounts_in_ynab,
    created_transactions,
    mocker: MockerFixture,
    saved,
    reason: str,
):
    # YNAB takes transactions into a closed account and then shows them nowhere
    accounts_in_ynab(*([saved] if saved else []), AccountFactory(id=OTHER_ACCOUNT_ID))
    question = mocker.patch("ynab_unlinked.cli.process.question", return_value="1")
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO)])

    result = yul("load test", input="y\n")

    assert result.exit_code == 0, result.output
    assert f"The account saved for test {reason}." in result.output
    assert question.call_args.kwargs["choices"] == ["1"]
    assert {str(t.account_id) for t in created_transactions()} == {OTHER_ACCOUNT_ID}
    assert saved_config(config_file).loaders["test"].account_id == OTHER_ACCOUNT_ID


def test_an_unknown_entity_is_offered_only_the_open_accounts(
    config_file: Path, accounts_in_ynab, mocker: MockerFixture
):
    accounts_in_ynab(
        AccountFactory(id=ACCOUNT_ID, name="Checking"),
        AccountFactory(id=CLOSED_ACCOUNT_ID, name="Old Savings", closed=True),
        AccountFactory(id=OTHER_ACCOUNT_ID, name="Credit Card"),
    )
    question = mocker.patch("ynab_unlinked.cli.process.question", return_value="2")

    account_id = get_or_prompt_account_id(saved_config(config_file), "newbank", force_prompt=False)

    assert question.call_args.kwargs["choices"] == ["1", "2"]
    assert account_id == OTHER_ACCOUNT_ID
    assert saved_config(config_file).loaders["newbank"].account_id == OTHER_ACCOUNT_ID


def test_the_chosen_account_is_saved_on_the_config_as_it_is_now(
    config_file: Path, accounts_in_ynab, mocker: MockerFixture
):
    accounts_in_ynab(AccountFactory(id=OTHER_ACCOUNT_ID, name="Credit Card"))
    loaded = saved_config(config_file)
    # Saved by the app while the CLI waited for the answer
    update_config(lambda saved: setattr(saved.loaders["test"], "enabled", False))
    mocker.patch("ynab_unlinked.cli.process.question", return_value="1")

    get_or_prompt_account_id(loaded, "newbank", force_prompt=False)

    on_disk = saved_config(config_file)
    assert on_disk.loaders["newbank"].account_id == OTHER_ACCOUNT_ID
    assert on_disk.loaders["test"].enabled is False
    assert loaded.loaders["newbank"].account_id == OTHER_ACCOUNT_ID


def test_a_forced_prompt_does_not_persist_the_chosen_account(
    config_file: Path, accounts_in_ynab, mocker: MockerFixture
):
    accounts_in_ynab(AccountFactory(id=OTHER_ACCOUNT_ID, name="Credit Card"))
    mocker.patch("ynab_unlinked.cli.process.question", return_value="1")

    account_id = get_or_prompt_account_id(saved_config(config_file), "test", force_prompt=True)

    assert account_id == OTHER_ACCOUNT_ID
    assert saved_config(config_file).loaders["test"].account_id == ACCOUNT_ID


def test_a_first_time_entity_is_registered_before_processing(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    accounts_in_ynab,
    mocker: MockerFixture,
):
    write_config(config_file, loaders={})
    accounts_in_ynab(AccountFactory(id=ACCOUNT_ID, name="Checking"))
    mocker.patch("ynab_unlinked.cli.process.question", return_value="1")
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO)])

    result = yul("load test", input="y\n")

    assert result.exit_code == 0, result.output
    assert saved_config(config_file).loaders["test"].account_id == ACCOUNT_ID


def test_choosing_an_account_for_an_unknown_entity_does_not_crash(
    config_file: Path,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    accounts_in_ynab,
    mocker: MockerFixture,
):
    write_config(config_file, loaders={})
    accounts_in_ynab(AccountFactory(id=ACCOUNT_ID, name="Checking"))
    mocker.patch("ynab_unlinked.cli.process.question", return_value="1")
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO)])

    result = yul("load --acount test", input="y\n")

    assert result.exit_code == 0, result.output

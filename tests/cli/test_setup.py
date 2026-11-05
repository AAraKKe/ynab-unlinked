import datetime as dt
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from ynab import DateFormat, PlanSummary

from tests.cli.process.builders import ACCOUNT_ID, BUDGET_ID, THREE_DAYS_AGO, TODAY
from tests.factories import (
    AccountFactory,
    PlanDetailFactory,
    SdkCurrencyFormatFactory,
    TransactionFactory,
)
from tests.helpers.config import ConfigFiles
from tests.helpers.types import CliRunner, LoadEntityCallback
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.cli.setup import load_context
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.config.core import ConfigError

API_KEY = "a-personal-access-token"
OTHER_BUDGET_ID = "00000000-0000-0000-0000-000000000002"


@pytest.fixture
def unconfigured(config: str, config_files: ConfigFiles, mocker: MockerFixture) -> Path:
    mocker.patch("ynab_unlinked.cli.setup.prompt_for_api_key", return_value=API_KEY)
    return config_files.v2


@pytest.fixture
def budgets_in_ynab(ynab_api: YnabClientStub):
    budget_api = ynab_api.api("budget")
    budget_api.get_plans.return_value.data.plans = [
        PlanSummary(id=BUDGET_ID, name="Personal"),
        PlanSummary(id=OTHER_BUDGET_ID, name="Household"),
    ]
    budget_api.get_plan_by_id.return_value.data.plan = PlanDetailFactory(
        id=OTHER_BUDGET_ID,
        name="Household",
        date_format=DateFormat(format="YYYY-MM-DD"),
        currency_format=SdkCurrencyFormatFactory(iso_code="GBP", currency_symbol="£"),
    )
    return budget_api


@pytest.mark.version("missing")
def test_setup_stores_the_selected_budget(unconfigured: Path, yul: CliRunner, budgets_in_ynab):
    result = yul("setup", input="2\n")

    assert result.exit_code == 0, result.output
    budgets_in_ynab.get_plan_by_id.assert_called_once_with(plan_id=OTHER_BUDGET_ID)
    stored = LatestConfig.model_validate_json(unconfigured.read_text())
    assert stored.api_key == API_KEY
    assert (stored.budget.id, stored.budget.name) == (OTHER_BUDGET_ID, "Household")
    assert stored.budget.date_format == "YYYY-MM-DD"
    assert stored.budget.currency_format.iso_code == "GBP"


@pytest.mark.version("missing")
def test_a_command_without_a_config_runs_the_setup_first(
    unconfigured: Path,
    yul: CliRunner,
    budgets_in_ynab,
    load_entity: LoadEntityCallback,
    ynab_api: YnabClientStub,
    mocker: MockerFixture,
):
    ynab_api.api("accounts").get_accounts.return_value.data.accounts = [
        AccountFactory(id=ACCOUNT_ID, name="Checking")
    ]
    mocker.patch("ynab_unlinked.cli.process.question", return_value="1")
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO, payee="Coffee Shop")])

    result = yul("load --show test", input="1\n")

    assert result.exit_code == 0, result.output
    assert "Welcome to ynab-unlinked" in result.output
    assert "Coffee Shop" in result.output
    assert unconfigured.is_file()


@pytest.mark.parametrize(
    "config",
    [
        pytest.param("missing", id="there is no config file"),
        pytest.param("broken", id="the config file has no version"),
    ],
    indirect=True,
)
def test_yes_fails_instead_of_running_the_setup(
    config: str,
    config_files: ConfigFiles,
    yul: CliRunner,
    load_entity: LoadEntityCallback,
    ynab_api: YnabClientStub,
):
    load_entity(TODAY, [TransactionFactory(date=THREE_DAYS_AGO, payee="Coffee Shop")])

    result = yul("load --yes test")

    assert result.exit_code != 0
    assert "Welcome to ynab-unlinked" not in result.output
    assert config_files.v2.is_file() == (config == "broken")
    ynab_api.api("budget").get_plans.assert_not_called()
    ynab_api.api("transactions").create_transaction.assert_not_called()


@pytest.mark.version("missing")
@pytest.mark.usefixtures("config")
def test_no_context_is_built_when_there_is_no_config():
    assert load_context() is None


@pytest.mark.version("broken")
@pytest.mark.usefixtures("config")
def test_a_config_that_cannot_be_read_is_a_config_error_not_a_missing_config():
    # Treating it as missing would run the setup over the user's file
    with pytest.raises(ConfigError):
        load_context()


UNREADABLE_CONFIGS = [
    pytest.param('{"version": "V4", "api_key": "my-api', id="truncated-json"),
    pytest.param('{"version": "V4", "budget": 3}', id="not-a-v4-config"),
    pytest.param("[1, 2]", id="json-that-is-not-an-object"),
    pytest.param('{"api_key": "my-api-key"}', id="no-version"),
]


@pytest.mark.version("missing")
@pytest.mark.parametrize("content", UNREADABLE_CONFIGS)
def test_an_unreadable_config_is_an_error_pointing_at_reset(
    config_files: ConfigFiles, yul: CliRunner, content: str
):
    config_files.write("V4", content)

    result = yul("config show", env={"COLUMNS": "1000"})

    assert result.exit_code == 1, result.output
    # A clean exit with a message, not a traceback
    assert isinstance(result.exception, SystemExit)
    assert str(config_files.v2) in result.output
    assert "yul config reset" in result.output


@pytest.mark.version("missing")
@pytest.mark.parametrize("content", UNREADABLE_CONFIGS)
def test_privacy_and_reset_work_on_an_unreadable_config(
    config_files: ConfigFiles, yul: CliRunner, content: str
):
    config_files.write("V4", content)

    assert yul("privacy").exit_code == 0

    result = yul("config reset --yes")
    assert result.exit_code == 0, result.output
    assert not config_files.v2.exists()


@pytest.mark.version("V4")
@pytest.mark.usefixtures("config")
def test_privacy_does_not_read_the_config(yul: CliRunner, mocker: MockerFixture):
    # Reading it reads the keychain too, which can raise a system prompt
    get_config = mocker.patch("ynab_unlinked.cli.setup.get_config")

    assert yul("privacy").exit_code == 0

    get_config.assert_not_called()


@pytest.mark.version("V4")
@pytest.mark.usefixtures("config")
def test_the_context_formats_dates_and_amounts_as_the_budget_does():
    context = load_context()

    assert context is not None
    assert context.formatter.format_date(dt.date(2025, 5, 12)) == "12/05/2025"
    assert context.formatter.format_amount(-1234.5) == "-1,234.50€"

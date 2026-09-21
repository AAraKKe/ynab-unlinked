import datetime as dt
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from ynab import DateFormat, PlanSummary

from tests.factories import (
    AccountFactory,
    PlanDetailFactory,
    SdkCurrencyFormatFactory,
    TransactionFactory,
)
from tests.helpers.config import ConfigFiles
from tests.helpers.types import CliRunner, LoadEntityCallback
from tests.helpers.ynab_api import YnabClientStub
from tests.process.builders import ACCOUNT_ID, BUDGET_ID, THREE_DAYS_AGO, TODAY
from ynab_unlinked.config.models.v3 import ConfigV3
from ynab_unlinked.setup import load_context

API_KEY = "a-personal-access-token"
OTHER_BUDGET_ID = "00000000-0000-0000-0000-000000000002"


@pytest.fixture
def unconfigured(config: str, config_files: ConfigFiles, mocker: MockerFixture) -> Path:
    mocker.patch("ynab_unlinked.setup.prompt_for_api_key", return_value=API_KEY)
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
    stored = ConfigV3.model_validate_json(unconfigured.read_text())
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
    mocker.patch("ynab_unlinked.process.question", return_value="1")
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
@pytest.mark.usefixtures("config")
def test_no_context_is_built_when_the_config_cannot_be_read():
    assert load_context() is None


@pytest.mark.version("V3")
@pytest.mark.usefixtures("config")
def test_the_context_formats_dates_and_amounts_as_the_budget_does():
    context = load_context()

    assert context is not None
    assert context.formatter.format_date(dt.date(2025, 5, 12)) == "12/05/2025"
    assert context.formatter.format_amount(-1234.5) == "-1,234.50€"

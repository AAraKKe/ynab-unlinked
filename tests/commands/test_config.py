from __future__ import annotations

import json
from uuid import UUID

import pytest
from pytest_mock import MockerFixture
from ynab import DateFormat, PlanSummary

from tests.factories import PlanDetailFactory, SdkCurrencyFormatFactory
from tests.helpers.config import ConfigFiles
from tests.helpers.types import CliRunner

pytestmark = pytest.mark.version("V3")

# Wide enough that Rich does not wrap the JSON or the stored paths across lines.
WIDE_TERMINAL = {"COLUMNS": "1000"}
NEW_BUDGET_ID = UUID("00000000-0000-0000-0000-0000000000ff")


def test_config_show_prints_the_stored_configuration(yul: CliRunner):
    result = yul("config show", env=WIDE_TERMINAL)

    assert result.exit_code == 0, result.output
    shown = json.loads(result.output)
    assert shown["api_key"] == "my-api-key"
    assert shown["budget"]["name"] == "My Budget"
    assert shown["version"] == "V3"


def test_config_set_api_key_replaces_the_key_on_disk(
    yul: CliRunner, config_files: ConfigFiles, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("getpass.getpass", lambda *args, **kwargs: "a-brand-new-api-key")

    result = yul("config set api_key", env=WIDE_TERMINAL)

    assert result.exit_code == 0, result.output
    assert json.loads(config_files.read())["api_key"] == "a-brand-new-api-key"


def test_config_set_api_key_warns_where_the_key_will_be_stored(
    yul: CliRunner, config_files: ConfigFiles, monkeypatch: pytest.MonkeyPatch
):
    """The privacy notice has to be shown before the key is asked for."""
    monkeypatch.setattr("getpass.getpass", lambda *args, **kwargs: "a-brand-new-api-key")

    result = yul("config set api_key", env=WIDE_TERMINAL)

    output = result.output.replace("\n", "")
    assert "plaintext" in output
    assert str(config_files.v2.parent) in output


def test_config_set_budget_stores_the_budget_picked_by_the_user(
    yul: CliRunner, config_files: ConfigFiles, mocker: MockerFixture
):
    client = mocker.patch("ynab_unlinked.utils.Client")
    client.return_value.budgets.return_value = [PlanSummary(id=NEW_BUDGET_ID, name="Other Budget")]
    client.return_value.budget.return_value = PlanDetailFactory(
        id=NEW_BUDGET_ID,
        name="Other Budget",
        date_format=DateFormat(format="YYYY-MM-DD"),
        currency_format=SdkCurrencyFormatFactory(
            iso_code="USD", symbol_first=True, currency_symbol="$"
        ),
    )

    result = yul("config set budget", input="1\n", env=WIDE_TERMINAL)

    assert result.exit_code == 0, result.output
    stored_budget = json.loads(config_files.read())["budget"]
    assert stored_budget["id"] == str(NEW_BUDGET_ID)
    assert stored_budget["date_format"] == "YYYY-MM-DD"
    assert stored_budget["currency_format"]["iso_code"] == "USD"
    # The rest of the config must survive a budget change
    assert json.loads(config_files.read())["entities"]["sabadell"]["account_id"] == (
        "sabadell-account"
    )

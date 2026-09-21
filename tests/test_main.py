from __future__ import annotations

import json
from uuid import UUID

import pytest
from pytest_mock import MockerFixture
from ynab import PlanSummary

from tests.factories import PlanDetailFactory
from tests.helpers.config import ConfigFiles
from tests.helpers.types import CliRunner

pytestmark = pytest.mark.version("missing")

# Wide enough that Rich does not wrap the command list or the stored paths across lines.
WIDE_TERMINAL = {"COLUMNS": "1000"}
BUDGET_ID = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def answers(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch):
    """Stubs YNAB and the API key prompt so the setup flow can run unattended."""
    monkeypatch.setattr("getpass.getpass", lambda *args, **kwargs: "the-api-key")
    client = mocker.patch("ynab_unlinked.utils.Client")
    client.return_value.budgets.return_value = [PlanSummary(id=BUDGET_ID, name="My Budget")]
    client.return_value.budget.return_value = PlanDetailFactory(id=BUDGET_ID)
    return client


@pytest.mark.usefixtures("answers")
def test_setup_persists_the_answers_it_collects(yul: CliRunner, config_files: ConfigFiles):
    result = yul("setup", input="1\n", env=WIDE_TERMINAL)

    assert result.exit_code == 0, result.output
    stored = json.loads(config_files.read())
    assert stored["api_key"] == "the-api-key"
    assert stored["budget"]["id"] == str(BUDGET_ID)
    assert stored["budget"]["date_format"] == "DD/MM/YYYY"
    assert stored["version"] == "V3"


@pytest.mark.usefixtures("answers")
def test_a_command_that_needs_a_config_runs_setup_first(yul: CliRunner, config_files: ConfigFiles):
    result = yul("config show", input="1\n", env=WIDE_TERMINAL)

    assert result.exit_code == 0, result.output
    assert config_files.v2.is_file(), "The command ran without ever storing a config"
    assert "the-api-key" in result.output

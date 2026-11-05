from __future__ import annotations

import datetime as dt
import json

import pytest
from pytest_mock import MockerFixture

from tests.factories import PlanDetailFactory
from tests.helpers import assets
from tests.helpers.config import ConfigFiles
from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import (
    Adjustments,
    ConfigV4,
    DebtMapping,
    LoaderConfig,
    TrackedAccount,
    edit_config,
    get_config,
    switch_budget,
    update_config,
)
from ynab_unlinked.config.core import ConfigError
from ynab_unlinked.config.models import ConfigV2
from ynab_unlinked.display import CliProgress
from ynab_unlinked.ynab_api import Client


def test_there_is_no_config_before_the_first_setup(config_files: ConfigFiles):
    assert get_config() is None


def test_a_config_from_a_newer_yul_is_reported_as_unsupported(config_files: ConfigFiles):
    config_files.write("V4", json.dumps({"version": "V9"}))

    with pytest.raises(ConfigError, match="Unsupported config version: 'Config:V9'"):
        get_config()


def test_loading_the_current_version_twice_needs_no_migration(config_files: ConfigFiles):
    # A MigrationEngine can only be registered once per class, so get_config building one
    # unconditionally would make the second call blow up.
    config_files.write_asset("V4")

    assert get_config() == get_config()


@pytest.mark.usefixtures("isolated_migration_registry")
def test_a_v1_config_is_migrated_and_replaced_by_the_current_version(
    config_files: ConfigFiles,
    mocker: MockerFixture,
):
    config_files.write_asset("V1")
    mocker.patch.object(Client, "budget", return_value=PlanDetailFactory())

    config = get_config()

    assert isinstance(config, ConfigV4)
    assert config.api_key == "my-api-key"
    assert config.budget.name == "My Budget"
    assert config.loaders["sabadell"].account_id == "sabadell-account"
    assert not config_files.v1.exists(), "The migrated away V1 config was left behind"
    assert config_files.v2.is_file(), "The migration result was not persisted"


@pytest.mark.usefixtures("isolated_migration_registry")
def test_a_failed_save_of_the_migrated_v1_config_keeps_the_v1_config(
    config_files: ConfigFiles,
    mocker: MockerFixture,
):
    config_files.write_asset("V1")
    mocker.patch.object(Client, "budget", return_value=PlanDetailFactory())
    mocker.patch.object(ConfigV2, "save", side_effect=OSError("disk full"))

    with pytest.raises(OSError, match="disk full"):
        get_config()

    assert config_files.v1.is_file(), "The V1 config was deleted before V2 was saved"


@pytest.mark.usefixtures("isolated_migration_registry")
def test_a_second_migration_in_the_same_process_reuses_the_migration_engine(
    config_files: ConfigFiles,
    mocker: MockerFixture,
):
    # Deltas are registered once per class, so an engine built per migration made the second
    # `yul` command of a process blow up with "already been registered".
    mocker.patch.object(Client, "budget", return_value=PlanDetailFactory())
    config_files.write_asset("V1")
    get_config()

    # The first migration removes the V1 file, so put a V1 config back to migrate again
    config_files.write_asset("V1")

    assert isinstance(get_config(), ConfigV4)


@pytest.mark.usefixtures("isolated_migration_registry")
def test_a_v3_config_is_migrated_to_v4_keeping_the_loaders_and_the_reconciliation_date(
    config_files: ConfigFiles,
):
    v3 = json.loads(assets.read_text("config_V3/config.json"))
    v3["last_reconciliation_date"] = "2025-05-01"
    config_files.write("V3", json.dumps(v3))

    config = get_config()

    assert isinstance(config, ConfigV4)
    assert config.last_reconciliation_date == dt.date(2025, 5, 1)
    assert config.loaders == {
        "sabadell": LoaderConfig(account_id="sabadell-account"),
        "cobee": LoaderConfig(account_id="cobee-account"),
        "test": LoaderConfig(account_id="TestAccountID"),
    }
    assert config.accounts == []
    assert config.debt_mappings == []
    assert config.adjustments == Adjustments()

    stored = json.loads(config_files.read("V4"))
    assert stored["version"] == "V4"
    assert "entities" not in stored
    assert stored["loaders"]["sabadell"] == {
        "account_id": "sabadell-account",
        "options": {},
        "enabled": True,
    }


@pytest.mark.usefixtures("isolated_migration_registry")
def test_migrating_shows_progress_but_loading_the_latest_version_does_not(
    config_files: ConfigFiles, capsys: pytest.CaptureFixture[str]
):
    config_files.write_asset("V3")
    get_config(CliProgress())
    assert "Migration done!" in capsys.readouterr().out

    get_config(CliProgress())
    assert "Migration done!" not in capsys.readouterr().out


@pytest.mark.usefixtures("isolated_migration_registry")
def test_a_migration_without_a_progress_prints_nothing(
    config_files: ConfigFiles, capsys: pytest.CaptureFixture[str]
):
    # The web app loads the config without a terminal to draw a spinner on
    config_files.write_asset("V3")

    assert isinstance(get_config(), ConfigV4)

    assert capsys.readouterr().out == ""


@pytest.mark.version("V4")
def test_two_writers_keep_each_others_changes(config: str):
    # The CLI loaded its copy before opening the reconcile TUI; the app saves meanwhile
    cli_copy = ConfigV4.load()
    update_config(lambda saved: setattr(saved.loaders["cobee"], "enabled", False))

    cli_copy.last_reconciliation_date = dt.date(2025, 5, 10)
    update_config(lambda saved: setattr(saved, "last_reconciliation_date", dt.date(2025, 5, 10)))

    on_disk = ConfigV4.load()
    assert on_disk.last_reconciliation_date == dt.date(2025, 5, 10)
    assert on_disk.loaders["cobee"].enabled is False, "The CLI undid what the app saved"


@pytest.mark.version("V4")
def test_a_failing_edit_saves_nothing(config: str, config_files: ConfigFiles):
    before = config_files.read()

    with pytest.raises(RuntimeError), edit_config() as saved:
        saved.api_key = "never-saved"
        raise RuntimeError("the change failed")

    assert config_files.read() == before


@pytest.mark.version("missing")
def test_editing_without_a_config_file_changes_the_fallback_or_fails(
    config: str, config_files: ConfigFiles
):
    with pytest.raises(ConfigError, match="yul setup"):
        update_config(lambda saved: None)
    assert not config_files.v2.exists()

    fallback = ConfigV4.model_validate_json(assets.read_text("config_V4/config.json"))
    saved = update_config(lambda saved: setattr(saved, "api_key", "new-token"), fallback)

    assert ConfigV4.load().api_key == saved.api_key == "new-token"
    assert fallback.api_key == "my-api-key", "The fallback itself is not changed"


def _with_budget_settings() -> ConfigV4:
    config = ConfigV4.model_validate_json(assets.read_text("config_V4/config.json"))
    config.last_reconciliation_date = dt.date(2025, 5, 10)
    config.accounts = [
        TrackedAccount(id="checking", name="Checking", type="checking", bucket=Bucket.CASH)
    ]
    config.debt_mappings = [DebtMapping(debt_account_id="card", mapped_to=["checking"])]
    config.adjustments = Adjustments(memo="By hand")
    return config


def test_switching_budget_clears_what_belongs_to_the_old_budget():
    config = _with_budget_settings()
    other = config.budget.model_copy(update={"id": "another-budget", "name": "Other"})

    switch_budget(config, other)

    assert config.budget == other
    assert (config.loaders, config.accounts, config.debt_mappings) == ({}, [], [])
    assert config.last_reconciliation_date is None
    assert config.api_key == "my-api-key"
    assert config.adjustments.memo == "By hand"


def test_choosing_the_same_budget_again_keeps_its_settings():
    config = _with_budget_settings()
    renamed = config.budget.model_copy(update={"name": "Renamed in YNAB"})

    switch_budget(config, renamed)

    assert config.budget.name == "Renamed in YNAB"
    assert config.loaders and config.accounts and config.debt_mappings
    assert config.last_reconciliation_date == dt.date(2025, 5, 10)

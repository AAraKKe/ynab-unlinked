import datetime as dt
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from tests.helpers.config import ConfigFiles
from tests.helpers.types import CliRunner
from ynab_unlinked.store import ExcludedRow, Store

pytestmark = pytest.mark.version("missing")

# Wide enough that absolute test paths don't get wrapped across lines by Rich.
WIDE_TERMINAL = {"COLUMNS": "1000"}


def test_reset_deletes_v2_directory_with_yes_flag(yul: CliRunner, config_files: ConfigFiles):
    config_files.write("V2", '{"version": "V2"}')

    result = yul("config reset --yes")

    assert result.exit_code == 0, result.output
    assert not config_files.v2.parent.exists()
    assert "deleted" in result.output.lower()


def test_reset_aborts_when_user_declines(yul: CliRunner, config_files: ConfigFiles):
    config_files.write("V2", '{"version": "V2"}')

    result = yul("config reset", input="n\n")

    assert result.exit_code == 0, result.output
    assert config_files.v2.parent.exists()
    assert "Aborted" in result.output


def test_reset_when_nothing_exists_is_a_no_op(yul: CliRunner):
    result = yul("config reset --yes")

    assert result.exit_code == 0, result.output
    assert "Nothing to delete" in result.output


def test_reset_also_removes_legacy_v1_directory(yul: CliRunner, config_files: ConfigFiles):
    config_files.write("V2", '{"version": "V2"}')
    config_files.write("V1", "{}")

    result = yul("config reset --yes")

    assert result.exit_code == 0, result.output
    assert not config_files.v2.parent.exists()
    assert not config_files.v1.parent.exists()


def test_reset_deletes_the_local_store_kept_apart_from_the_config(
    yul: CliRunner, config_files: ConfigFiles, store_file: Path
):
    config_files.write("V2", '{"version": "V2"}')
    Store(store_file).exclude(
        "budget",
        ExcludedRow(
            account_id="account",
            import_id="YNAB:-18380:2025-05-12:1",
            date=dt.date(2025, 5, 12),
            amount=-18_380,
            payee="Maya mobile ltd",
        ),
    )

    result = yul("config reset --yes", env=WIDE_TERMINAL)

    assert result.exit_code == 0, result.output
    assert str(store_file) in result.output
    assert not store_file.exists()
    assert not config_files.v2.parent.exists()
    # The rows left out of imports went with it
    assert Store(store_file).excluded("budget") == []


def test_reset_deletes_the_web_app_preferences_kept_apart_from_the_config(
    yul: CliRunner, config_files: ConfigFiles, web_storage: Path
):
    # On Linux and Windows the data directory is not the config one
    config_files.write("V2", '{"version": "V2"}')
    web_storage.mkdir(parents=True)
    (web_storage / "secret").write_text("browser storage secret")

    result = yul("config reset --yes", env=WIDE_TERMINAL)

    assert result.exit_code == 0, result.output
    assert str(web_storage) in result.output
    assert not web_storage.exists()


def test_reset_deletes_the_local_store_even_without_a_config(yul: CliRunner, store_file: Path):
    Store(store_file)

    result = yul("config reset --yes")

    assert result.exit_code == 0, result.output
    assert not store_file.exists()


def test_reset_lists_a_store_inside_the_config_directory_once(
    yul: CliRunner, config_files: ConfigFiles, mocker: MockerFixture
):
    # On macOS the platformdirs config and data directories are the same one
    config_files.write("V2", '{"version": "V2"}')
    store_file = config_files.v2.parent / "store.sqlite"
    Store(store_file)
    mocker.patch("ynab_unlinked.local_data.store_path", return_value=store_file)

    result = yul("config reset --yes", env=WIDE_TERMINAL)

    assert result.exit_code == 0, result.output
    assert str(store_file) not in result.output
    assert not config_files.v2.parent.exists()

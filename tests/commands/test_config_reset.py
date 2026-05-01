from pathlib import Path

from pytest_mock import MockerFixture
from typer.testing import CliRunner as TyperRunner

from ynab_unlinked.main import app


def _patch_paths(mocker: MockerFixture, v2_config: Path, v1_config: Path) -> None:
    mocker.patch("ynab_unlinked.commands.config.config_path", return_value=v2_config)
    mocker.patch("ynab_unlinked.commands.config.v1_config_path", return_value=v1_config)
    mocker.patch("ynab_unlinked.privacy.config_path", return_value=v2_config)
    mocker.patch("ynab_unlinked.config.core.config_path", return_value=v2_config)


def test_reset_deletes_v2_directory_with_yes_flag(tmp_path: Path, mocker: MockerFixture) -> None:
    v2_dir = tmp_path / "ynab-unlinked"
    v2_dir.mkdir()
    v2_config = v2_dir / "config.json"
    v2_config.write_text('{"version": "V2"}')
    v1_config = tmp_path / "missing" / "config.json"

    _patch_paths(mocker, v2_config, v1_config)

    result = TyperRunner().invoke(app, ["config", "reset", "--yes"])

    assert result.exit_code == 0, result.output
    assert not v2_dir.exists()
    assert "deleted" in result.output.lower()


def test_reset_aborts_when_user_declines(tmp_path: Path, mocker: MockerFixture) -> None:
    v2_dir = tmp_path / "ynab-unlinked"
    v2_dir.mkdir()
    v2_config = v2_dir / "config.json"
    v2_config.write_text('{"version": "V2"}')
    v1_config = tmp_path / "missing" / "config.json"

    _patch_paths(mocker, v2_config, v1_config)

    result = TyperRunner().invoke(app, ["config", "reset"], input="n\n")

    assert result.exit_code == 0, result.output
    assert v2_dir.exists()
    assert "Aborted" in result.output


def test_reset_when_nothing_exists_is_a_no_op(tmp_path: Path, mocker: MockerFixture) -> None:
    v2_config = tmp_path / "missing-v2" / "config.json"
    v1_config = tmp_path / "missing-v1" / "config.json"
    _patch_paths(mocker, v2_config, v1_config)

    result = TyperRunner().invoke(app, ["config", "reset", "--yes"])

    assert result.exit_code == 0, result.output
    assert "Nothing to delete" in result.output


def test_reset_also_removes_legacy_v1_directory(tmp_path: Path, mocker: MockerFixture) -> None:
    v2_dir = tmp_path / "ynab-unlinked"
    v2_dir.mkdir()
    v2_config = v2_dir / "config.json"
    v2_config.write_text('{"version": "V2"}')

    v1_dir = tmp_path / "ynab_unlinked"
    v1_dir.mkdir()
    v1_config = v1_dir / "config.json"
    v1_config.write_text("{}")

    _patch_paths(mocker, v2_config, v1_config)

    result = TyperRunner().invoke(app, ["config", "reset", "--yes"])

    assert result.exit_code == 0, result.output
    assert not v2_dir.exists()
    assert not v1_dir.exists()

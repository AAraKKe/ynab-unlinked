from pathlib import Path

from pytest_mock import MockerFixture
from typer.testing import CliRunner as TyperRunner

from ynab_unlinked.main import app

# Wide enough that absolute test paths don't get wrapped across lines by Rich.
WIDE_TERMINAL = {"COLUMNS": "1000"}


def _flatten(text: str) -> str:
    """Collapse the line breaks Rich introduces when wrapping output."""
    return text.replace("\n", "")


def test_privacy_command_prints_resolved_storage_path(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    config_file = tmp_path / "ynab-unlinked" / "config.json"
    mocker.patch("ynab_unlinked.privacy.config_path", return_value=config_file)

    result = TyperRunner().invoke(app, ["privacy"], env=WIDE_TERMINAL)

    assert result.exit_code == 0, result.output
    output = _flatten(result.output)
    assert str(config_file.parent) in output
    assert "yul config reset" in output
    assert "PRIVACY.md" in output
    assert "not affiliated" in output.lower()


def test_privacy_command_runs_without_a_config_present(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """`yul privacy` must work even when no config has been created yet."""
    missing_config = tmp_path / "no-such-dir" / "config.json"
    mocker.patch("ynab_unlinked.privacy.config_path", return_value=missing_config)
    mocker.patch("ynab_unlinked.config.core.config_path", return_value=missing_config)

    result = TyperRunner().invoke(app, ["privacy"], env=WIDE_TERMINAL)

    assert result.exit_code == 0, result.output
    assert str(missing_config.parent) in _flatten(result.output)

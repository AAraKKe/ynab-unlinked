import pytest

from tests.helpers.config import ConfigFiles
from tests.helpers.types import CliRunner

pytestmark = pytest.mark.version("missing")

# Wide enough that absolute test paths don't get wrapped across lines by Rich.
WIDE_TERMINAL = {"COLUMNS": "1000"}


def _flatten(text: str) -> str:
    """Collapse the line breaks Rich introduces when wrapping output."""
    return text.replace("\n", "")


def test_privacy_command_prints_resolved_storage_path(yul: CliRunner, config_files: ConfigFiles):
    result = yul("privacy", env=WIDE_TERMINAL)

    assert result.exit_code == 0, result.output
    output = _flatten(result.output)
    assert str(config_files.v2.parent) in output
    assert "yul config reset" in output
    assert "PRIVACY.md" in output
    assert "not affiliated" in output.lower()


def test_privacy_command_runs_without_a_config_present(yul: CliRunner, config_files: ConfigFiles):
    """`yul privacy` must work even when no config has been created yet."""
    result = yul("privacy", env=WIDE_TERMINAL)

    assert result.exit_code == 0, result.output
    assert not config_files.v2.exists()
    assert str(config_files.v2.parent) in _flatten(result.output)

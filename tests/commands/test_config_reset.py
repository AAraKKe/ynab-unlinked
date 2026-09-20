import pytest

from tests.helpers.config import ConfigFiles
from tests.helpers.types import CliRunner

pytestmark = pytest.mark.version("missing")


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

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from ynab_unlinked import keychain
from ynab_unlinked.config import paths
from ynab_unlinked.store import store_path
from ynab_unlinked.web import storage_dir


def test_yul_home_holds_every_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path))

    assert paths.config_path() == tmp_path / "config.json"
    assert store_path() == tmp_path / "store.sqlite"
    assert paths.web_storage_dir() == storage_dir() == tmp_path / "web"
    assert paths.v1_config_path() == tmp_path / "v1" / "config.json"


def test_without_yul_home_the_system_locations_are_used(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(paths.HOME_ENV, raising=False)

    assert paths.config_path().name == "config.json"
    assert store_path().name == "store.sqlite"
    assert paths.web_storage_dir() == storage_dir() == store_path().parent / "web"


def test_listing_and_deleting_local_data_needs_no_web_module():
    # Core modules shared by the CLI and the app depend on no UI package
    code = (
        "import sys, ynab_unlinked.local_data, ynab_unlinked.privacy;"
        "sys.exit(any(m.startswith('ynab_unlinked.web') for m in sys.modules))"
    )

    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_a_test_without_fixtures_never_reaches_the_real_files():
    # The autouse `yul_home` fixture is the safety net: no path a test can resolve, nor the
    # keychain item, may point outside the scratch folder of the test
    home = Path(os.environ[paths.HOME_ENV])

    assert Path(tempfile.gettempdir()).resolve() in home.resolve().parents
    for path in (
        paths.config_path(),
        paths.v1_config_path(),
        store_path(),
        paths.web_storage_dir(),
        storage_dir(),
    ):
        assert path.is_relative_to(home)
    assert keychain.service_name() == f"{keychain.DEFAULT_SERVICE} ({home.resolve()})"

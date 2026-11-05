from pathlib import Path

import pytest

from ynab_unlinked.config import paths
from ynab_unlinked.store import store_path
from ynab_unlinked.web import storage_dir


def test_yul_home_holds_every_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path))

    assert paths.config_path() == tmp_path / "config.json"
    assert store_path() == tmp_path / "store.sqlite"
    assert storage_dir() == tmp_path / "web"
    assert paths.v1_config_path() == Path.home() / ".config/ynab_unlinked/config.json"


def test_without_yul_home_the_system_locations_are_used(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(paths.HOME_ENV, raising=False)

    assert paths.config_path().name == "config.json"
    assert store_path().name == "store.sqlite"
    assert storage_dir() == store_path().parent / "web"

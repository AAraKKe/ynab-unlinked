from pathlib import Path

from ynab_unlinked.config.paths import data_dir


def store_path() -> Path:
    return data_dir() / "store.sqlite"

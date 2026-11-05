"""Everything yul keeps on this machine, and how to delete it.

Shared by `yul config reset` and the web app's "Reset all data".
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ynab_unlinked import keychain
from ynab_unlinked.config.paths import config_path, v1_config_path
from ynab_unlinked.store import store_path
from ynab_unlinked.web import storage_dir as web_storage_dir

logger = logging.getLogger(__name__)


def local_data_paths() -> list[Path]:
    """The config directories, the store file and the web app preferences that exist now."""
    paths: list[Path] = []

    config_dir = config_path().parent
    if config_dir.is_dir():
        paths.append(config_dir)

    v1_path = v1_config_path()
    if v1_path.is_file() and v1_path.parent not in paths:
        paths.append(v1_path.parent)

    store = store_path()
    if store.is_file() and not any(store.is_relative_to(p) for p in paths):
        paths.append(store)

    web = web_storage_dir()
    if web.is_dir() and not any(web.is_relative_to(p) for p in paths):
        paths.append(web)

    return paths


def delete_local_data(paths: list[Path] | None = None) -> list[Path]:
    """Delete `paths` (default: `local_data_paths()`) and the token in the keychain.

    Returns the paths deleted.
    """
    paths = local_data_paths() if paths is None else paths
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    if keychain.available():
        try:
            keychain.delete()
        except keychain.KeychainError as error:
            logger.warning("The token could not be removed from the keychain: %s", error)
    return paths

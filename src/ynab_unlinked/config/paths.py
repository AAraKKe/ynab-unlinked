import os
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

from .constants import LATEST_VERSION

HOME_ENV = "YUL_HOME"
"""A folder that holds every file of yul (config, budget copy, web preferences) instead of
the system locations: for scratch runs that must not touch the real ones."""


def yul_home() -> Path | None:
    """The `YUL_HOME` folder, None when yul uses the system locations."""
    value = os.environ.get(HOME_ENV)
    return Path(value).expanduser() if value else None


def data_dir() -> Path:
    """Where the budget copy and the web preferences live."""
    if (home := yul_home()) is not None:
        return home
    return Path(user_data_dir("ynab-unlinked", "committhatline"))


def web_storage_dir() -> Path:
    """Where the web app keeps per browser preferences (theme, sidebar) and their secret.

    Here rather than in `web` so what lists and deletes local data needs no web module.
    """
    return data_dir() / "web"


def v1_config_path() -> Path:
    # This needs to be done especifically for version 1 because it was stored in a different path
    # and was the version before any versioning was implemented
    return Path.home() / ".config/ynab_unlinked/config.json"


def config_path(version: str = LATEST_VERSION.version) -> Path:
    if version == "V1":
        return v1_config_path()
    if (home := yul_home()) is not None:
        return home / "config.json"
    return Path(user_config_dir("ynab-unlinked", "committhatline")) / "config.json"

from pathlib import Path

from platformdirs import user_config_dir

from .constants import LATEST_VERSION


def v1_config_path() -> Path:
    # This needs to be done especifically for version 1 because it was stored in a different path
    # and was the version before any versioning was implemented
    return Path.home() / ".config/ynab_unlinked/config.json"


def config_path(version: str = LATEST_VERSION.version) -> Path:
    if version == "V1":
        return v1_config_path()

    return Path(user_config_dir("ynab-unlinked", "committhatline")) / "config.json"

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Final, cast

from pydantic import ValidationError

from ynab_unlinked.core.progress import NO_PROGRESS, Progress

from .constants import LATEST_VERSION
from .migrations import MigrationEngine, Version
from .models import (
    ConfigV1,
    ConfigV2,
    ConfigV3,
    ConfigV4,
    DeltaConfigV1ToV2,
    DeltaConfigV2ToV3,
    DeltaConfigV3ToV4,
)
from .models.v2 import Budget
from .paths import config_path
from .types import Config

VERSION_MAPPING: Final[dict[str, type[Config]]] = {
    "V1": ConfigV1,
    "V2": ConfigV2,
    "V3": ConfigV3,
    "V4": ConfigV4,
}
LATEST_CONFIG_TYPE = ConfigV4


class ConfigError(ValueError):
    """The config file exists but cannot be used: not JSON, not a config, or from a newer yul."""


# Deltas are registered on a registry shared by every MigrationEngine, so a second engine for
# the same class would be rejected. Build the one engine for the config lazily and reuse it.
_engine: MigrationEngine | None = None


def migration_engine() -> MigrationEngine:
    global _engine
    if _engine is None:
        _engine = MigrationEngine(
            "Config", DeltaConfigV1ToV2(), DeltaConfigV2ToV3(), DeltaConfigV3ToV4()
        )
    return _engine


def config_version() -> Version:
    # Check V1
    # V1 does not have a version in it and was stored in a different path
    if config_path("V1").is_file():
        return Version("Config", "V1")

    latest_config_path = config_path(LATEST_VERSION.version)
    if not latest_config_path.is_file():
        # This can happen when we run the tool for the first time. Return the latest verison
        return LATEST_VERSION

    try:
        content = json.loads(latest_config_path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ConfigError(
            f"The config file {latest_config_path} is not valid JSON: {error}"
        ) from error

    if not isinstance(content, dict) or "version" not in content:
        raise ConfigError(f"The config file {latest_config_path} has no version, it is malformed.")
    version = cast(dict[str, object], content)["version"]
    return Version("Config", str(version))


def get_config(progress: Progress = NO_PROGRESS) -> LATEST_CONFIG_TYPE | None:
    """Get the latest supported version of the config running any migrations if needed.

    `progress` shows the migration steps: the CLI passes its `CliProgress`.
    """
    version = config_version()

    if (current_config := VERSION_MAPPING.get(version.version)) is None:
        raise ConfigError(f"Unsupported config version: {version!r}")

    if not current_config.exists():
        return None

    try:
        loaded = current_config.load()
    except ValidationError as error:
        # Also what pydantic raises for a file that is not JSON
        raise ConfigError(
            f"The config file {config_path(version.version)} is not a valid {version.version} config: "
            f"{error}"
        ) from error

    if isinstance(loaded, LATEST_CONFIG_TYPE):
        return loaded

    return migration_engine().migrate(loaded, LATEST_CONFIG_TYPE, progress=progress)


@contextmanager
def edit_config(fallback: LATEST_CONFIG_TYPE | None = None) -> Generator[LATEST_CONFIG_TYPE]:
    """Change the config on disk in a block: read again, change what the block yields, save.

    The file is read again first, so what another process (the CLI or the app) saved since
    this one loaded its copy is kept: each writer only changes what its block touches.
    `fallback` is changed instead when there is no file yet. Nothing is saved when the block
    raises. There is no lock: two saves in the same instant still race, the last one wins.
    """
    if LATEST_CONFIG_TYPE.exists():
        config = LATEST_CONFIG_TYPE.load()
    elif fallback is not None:
        config = fallback.model_copy(deep=True)
    else:
        raise ConfigError("There is no config to change yet. Run `yul setup` first.")
    yield config
    config.save()


def update_config(
    change: Callable[[LATEST_CONFIG_TYPE], None], fallback: LATEST_CONFIG_TYPE | None = None
) -> LATEST_CONFIG_TYPE:
    """`edit_config` as a call: apply `change` to the config on disk; returns what was saved."""
    with edit_config(fallback) as config:
        change(config)
    return config


def switch_budget(config: LATEST_CONFIG_TYPE, budget: Budget) -> None:
    """Point `config` at another budget, forgetting what belonged to the old one.

    Bank accounts, tracked accounts, debt mappings and the last reconciliation are ids and
    dates of the old budget, so they are cleared. The token and the adjustment settings are
    not tied to a budget and stay. Choosing the budget already set changes nothing.
    """
    if config.budget.id == budget.id:
        config.budget = budget
        return
    config.budget = budget
    config.loaders = {}
    config.accounts = []
    config.debt_mappings = []
    config.last_reconciliation_date = None

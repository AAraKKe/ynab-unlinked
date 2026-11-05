from __future__ import annotations

import json
from typing import Final

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
_MIGRATION_ENGINE: MigrationEngine | None = None


def migration_engine() -> MigrationEngine:
    global _MIGRATION_ENGINE
    if _MIGRATION_ENGINE is None:
        _MIGRATION_ENGINE = MigrationEngine(
            "Config", DeltaConfigV1ToV2(), DeltaConfigV2ToV3(), DeltaConfigV3ToV4()
        )
    return _MIGRATION_ENGINE


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
    return Version("Config", str(content["version"]))


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

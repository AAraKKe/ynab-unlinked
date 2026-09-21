from __future__ import annotations

import json
from typing import Final

from .constants import LATEST_VERSION
from .migrations import MigrationEngine, Version
from .models import ConfigV1, ConfigV2, ConfigV3, DeltaConfigV1ToV2, DeltaConfigV2ToV3
from .paths import config_path
from .types import Config

VERSION_MAPPING: Final[dict[str, type[Config]]] = {
    "V1": ConfigV1,
    "V2": ConfigV2,
    "V3": ConfigV3,
}
LATESST_CONFIG_TYPE = ConfigV3


class ConfigError(ValueError): ...


# Deltas are registered on a registry shared by every MigrationEngine, so a second engine for
# the same class would be rejected. Build the one engine for the config lazily and reuse it.
_MIGRATION_ENGINE: MigrationEngine | None = None


def migration_engine() -> MigrationEngine:
    global _MIGRATION_ENGINE
    if _MIGRATION_ENGINE is None:
        _MIGRATION_ENGINE = MigrationEngine("Config", DeltaConfigV1ToV2(), DeltaConfigV2ToV3())
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

    with open(latest_config_path) as config_file:
        content = json.load(config_file)
        if "version" not in content:
            raise ConfigError(
                "Configuration file malformatted. Run `yul config reset` to reconfigure yul."
            )
        return Version("Config", content["version"])


def get_config() -> LATESST_CONFIG_TYPE | None:
    """Get the latest supported version of the config running any migrations if needed"""
    version = config_version()

    if (current_config := VERSION_MAPPING.get(version.version)) is None:
        raise ConfigError(f"Unsupported config version: {version!r}")

    if not current_config.exists():
        return None

    if current_config is LATESST_CONFIG_TYPE:
        return LATESST_CONFIG_TYPE.load()

    return migration_engine().migrate(current_config.load(), LATESST_CONFIG_TYPE)

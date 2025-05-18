from typing import Final

from .config_migrations import DeltaConfigV1ToV2
from .core import (
    LATEST_VERSION,
    MAX_CONFIG_VERSION,
    TRANSACTION_GRACE_PERIOD_DAYS,
    Checkpoint,
    Config,
    ConfigError,
    EntityConfig,
    config_path,
    config_version,
    v1_config_path,
)
from .migrations import Delta, DeltaRegistry, MigrationEngine, Version, Versioned
from .v1 import ConfigV1
from .v2 import ConfigV2

# Keep a mapping fro all versions and which classes they represent
VERSION_MAPPING: Final = {
    "V1": ConfigV1,
    "V2": ConfigV2,
}

migration_engine = MigrationEngine("Config", DeltaConfigV1ToV2())


__all__ = [
    "Checkpoint",
    "ConfigError",
    "Config",
    "ConfigV1",
    "ConfigV2",
    "Delta",
    "DeltaRegistry",
    "DeltaConfigV1ToV2",
    "EntityConfig",
    "MAX_CONFIG_VERSION",
    "LATEST_VERSION",
    "MigrationEngine",
    "migration_engine",
    "TRANSACTION_GRACE_PERIOD_DAYS",
    "Version",
    "Versioned",
    "config_version",
    "config_path",
    "v1_config_path",
    "VERSION_MAPPING",
]

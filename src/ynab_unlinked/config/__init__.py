from .constants import LATEST_VERSION, MAX_CONFIG_VERSION
from .core import edit_config, get_config, switch_budget, update_config
from .models import (
    Adjustments,
    ClearedStatus,
    ConfigV1,
    ConfigV2,
    ConfigV3,
    ConfigV4,
    DebtMapping,
    Finances,
    LoaderConfig,
    TrackedAccount,
)
from .types import Config

# The newest config version. Code outside this package types against this alias.
LatestConfig = ConfigV4

__all__ = [
    "ConfigV1",
    "ConfigV2",
    "ConfigV3",
    "ConfigV4",
    "Adjustments",
    "ClearedStatus",
    "Config",
    "DebtMapping",
    "Finances",
    "LatestConfig",
    "LoaderConfig",
    "TrackedAccount",
    "edit_config",
    "get_config",
    "switch_budget",
    "update_config",
    "LATEST_VERSION",
    "MAX_CONFIG_VERSION",
]

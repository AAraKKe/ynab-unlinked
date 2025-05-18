from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Protocol

from platformdirs import user_config_dir
from pydantic import BaseModel

from ynab_unlinked.config.migrations import Version, Versioned
from ynab_unlinked.models import Transaction, TransactionWithYnabData

CONFIG_PATH_AFTER_V2 = user_config_dir("ynab-unlinked", "committhatline")

TRANSACTION_GRACE_PERIOD_DAYS = 2
MAX_CONFIG_VERSION = 2
LATEST_VERSION = Version("Config", f"V{MAX_CONFIG_VERSION}")


class ConfigError(ValueError): ...


class Checkpoint(BaseModel):
    latest_date_processed: dt.date
    latest_transaction_hash: int


class EntityConfig(BaseModel):
    account_id: str
    checkpoint: Checkpoint | None = None


class Config(Versioned, Protocol):
    @staticmethod
    def exists() -> bool: ...
    def save(self): ...
    @staticmethod
    def load() -> Config: ...
    def update_and_save(self, last_transaction: Transaction, entity_name: str): ...
    def add_payee_rules(self, transactions: list[TransactionWithYnabData]): ...
    def payee_from_fules(self, payee: str) -> str | None: ...


def v1_config_path() -> Path:
    # This needs to be done especifically for version 1 because it was stored in a different path
    # and was the version before any versioning was implemented
    return Path.home() / ".config/ynab_unlinked/config.json"


def config_path() -> Path:
    return Path(user_config_dir("ynab-unlinked", "committhatline")) / "config.json"


def config_version() -> Version:
    # Check V1
    # V1 does not have a version in it and was stored in a different path
    if v1_config_path().is_file():
        return Version("Config", "V1")

    if not config_path().is_file():
        # This can happen when we run the tool for the first time. Return the latest verison
        return LATEST_VERSION

    with open(config_path()) as config_file:
        content = json.load(config_file)
        if "version" not in content:
            raise ConfigError(
                "Configuration file malformatted. Run `yul config reset` to reconfigure yul."
            )
        return Version("Config", content["version"])

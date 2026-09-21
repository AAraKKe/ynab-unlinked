from __future__ import annotations

import datetime as dt
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ynab_unlinked.config.migrations import Version
from ynab_unlinked.config.paths import config_path

from .shared import EntityConfig


class CurrencyFormat(BaseModel):
    iso_code: str
    decimal_digits: int
    decimal_separator: str
    symbol_first: bool
    group_separator: str
    currency_symbol: str
    display_symbol: bool


class Budget(BaseModel):
    id: str
    name: str
    date_format: str
    currency_format: CurrencyFormat


class ConfigV2(BaseModel):
    api_key: str
    budget: Budget
    last_reconciliation_date: dt.date | None = None
    entities: dict[str, EntityConfig] = Field(default_factory=dict)
    payee_rules: dict[str, set[str]] = Field(default_factory=dict)
    version_number: str = Field(default="V2", alias="version")

    model_config = ConfigDict(validate_by_alias=True, serialize_by_alias=True)

    @staticmethod
    def version() -> Version:
        return Version("Config", "V2")

    @staticmethod
    def path() -> Path:
        return config_path(ConfigV2.version().version)

    def save(self):
        self.path().parent.mkdir(parents=True, exist_ok=True)
        self.path().write_text(self.model_dump_json(indent=4))

    @staticmethod
    def load() -> ConfigV2:
        return ConfigV2.model_validate_json(ConfigV2.path().read_text())

    @staticmethod
    def exists() -> bool:
        return ConfigV2.path().is_file()

    def entity(self, name: str) -> EntityConfig | None:
        return self.entities.get(name)

    def set_entity_account(self, name: str, account_id: str):
        if (entity := self.entities.get(name)) is not None:
            entity.account_id = account_id

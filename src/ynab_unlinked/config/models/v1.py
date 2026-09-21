from __future__ import annotations

import datetime as dt
from pathlib import Path

from pydantic import BaseModel, Field

from ynab_unlinked.config.migrations import Version
from ynab_unlinked.config.paths import config_path

from .shared import EntityConfig


class ConfigV1(BaseModel):
    api_key: str
    budget_id: str
    last_reconciliation_date: dt.date | None = None
    entities: dict[str, EntityConfig] = Field(default_factory=dict)
    payee_rules: dict[str, set[str]] = Field(default_factory=dict)

    @staticmethod
    def version() -> Version:
        return Version("Config", "V1")

    @staticmethod
    def path() -> Path:
        return config_path(ConfigV1.version().version)

    def save(self):
        self.path().parent.mkdir(parents=True, exist_ok=True)
        self.path().write_text(self.model_dump_json(indent=4))

    @staticmethod
    def load() -> ConfigV1:
        return ConfigV1.model_validate_json(ConfigV1.path().read_text())

    @staticmethod
    def exists() -> bool:
        return ConfigV1.path().is_file()

    def entity(self, name: str) -> EntityConfig | None:
        return self.entities.get(name)

    def set_entity_account(self, name: str, account_id: str):
        if (entity := self.entities.get(name)) is not None:
            entity.account_id = account_id

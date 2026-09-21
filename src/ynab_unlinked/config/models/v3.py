from __future__ import annotations

import datetime as dt
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ynab_unlinked.config.migrations import Version
from ynab_unlinked.config.paths import config_path

from .shared import EntityConfigV3
from .v2 import Budget


class ConfigV3(BaseModel):
    api_key: str
    budget: Budget
    last_reconciliation_date: dt.date | None = None
    entities: dict[str, EntityConfigV3] = Field(default_factory=dict)
    version_number: str = Field(default="V3", alias="version")

    model_config = ConfigDict(validate_by_alias=True, serialize_by_alias=True)

    @staticmethod
    def version() -> Version:
        return Version("Config", "V3")

    @staticmethod
    def path() -> Path:
        return config_path(ConfigV3.version().version)

    def save(self):
        self.path().parent.mkdir(parents=True, exist_ok=True)
        self.path().write_text(self.model_dump_json(indent=4))

    @staticmethod
    def load() -> ConfigV3:
        return ConfigV3.model_validate_json(ConfigV3.path().read_text())

    @staticmethod
    def exists() -> bool:
        return ConfigV3.path().is_file()

    def entity(self, name: str) -> EntityConfigV3 | None:
        return self.entities.get(name)

    def set_entity_account(self, name: str, account_id: str):
        if (entity := self.entities.get(name)) is None:
            self.entities[name] = EntityConfigV3(account_id=account_id)
        else:
            entity.account_id = account_id

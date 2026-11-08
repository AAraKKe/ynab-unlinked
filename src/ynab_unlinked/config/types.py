from __future__ import annotations

from typing import Protocol

from .migrations import Versioned
from .models.shared import EntityConfig, EntityConfigV3
from .models.v4 import LoaderConfig


class Config(Versioned, Protocol):
    @staticmethod
    def exists() -> bool: ...
    def save(self): ...
    @staticmethod
    def load() -> Config: ...
    def entity(self, name: str) -> EntityConfig | EntityConfigV3 | LoaderConfig | None: ...
    def set_entity_account(self, name: str, account_id: str): ...

from __future__ import annotations

import datetime as dt
from pathlib import Path

from pydantic import BaseModel, Field

from ynab_unlinked.config.constants import TRANSACTION_GRACE_PERIOD_DAYS
from ynab_unlinked.config.migrations import Version
from ynab_unlinked.config.paths import config_path
from ynab_unlinked.models import Transaction, TransactionWithYnabData

from .shared import Checkpoint, EntityConfig


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

    def update_and_save(self, last_transaction: Transaction, entity_name: str):
        checkpoint = Checkpoint(
            latest_date_processed=(
                last_transaction.date - dt.timedelta(days=TRANSACTION_GRACE_PERIOD_DAYS)
            ),
            latest_transaction_hash=hash(last_transaction),
        )

        self.entities[entity_name].checkpoint = checkpoint

        self.save()

    @staticmethod
    def load() -> ConfigV1:
        return ConfigV1.model_validate_json(ConfigV1.path().read_text())

    @staticmethod
    def exists() -> bool:
        return ConfigV1.path().is_file()

    def add_payee_rules(self, transactions: list[TransactionWithYnabData]):
        # For each transaction, add a rule that matches both payees
        for transaction in transactions:
            if transaction.partial_match is None:
                continue

            if transaction.ynab_payee is None:
                continue

            imported_payee = transaction.payee
            ynab_payee = transaction.ynab_payee

            if imported_payee == ynab_payee:
                continue

            self.payee_rules.setdefault(ynab_payee, set()).add(imported_payee)
            self.save()

    def payee_from_fules(self, payee: str) -> str | None:
        return next(
            (
                ynab_payee
                for ynab_payee, valid_names in self.payee_rules.items()
                if payee in valid_names
            ),
            None,
        )

    def entity(self, name: str) -> EntityConfig | None:
        return self.entities.get(name)

    def set_entity_account(self, name: str, account_id: str):
        if (entity := self.entities.get(name)) is not None:
            entity.account_id = account_id

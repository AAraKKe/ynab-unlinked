from __future__ import annotations

import datetime as dt
from pathlib import Path

from pydantic import BaseModel, Field

from ynab_unlinked.models import Transaction, TransactionWithYnabData

CONFIG_PATH = Path.home() / ".config/ynab_unlinked/config.json"
TRANSACTION_GRACE_PERIOD_DAYS = 60


class Checkpoint(BaseModel):
    latest_date_processed: dt.date
    latest_transaction_hash: int


class EntityConfig(BaseModel):
    account_id: str
    checkpoint: Checkpoint | None = None


class Config(BaseModel):
    api_key: str
    budget_id: str
    entities: dict[str, EntityConfig] = Field(default_factory=dict)
    payee_rules: dict[str, set[str]] = Field(default_factory=dict)

    def save(self):
        CONFIG_PATH.write_text(self.model_dump_json(indent=4))

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
    def load() -> Config:
        return Config.model_validate_json(CONFIG_PATH.read_text())

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

    def payee_from_fules(self, payee: str) -> str | None:
        for ynab_payee, valid_names in self.payee_rules.items():
            if payee in valid_names:
                return ynab_payee

        return None


def ensure_config():
    if not CONFIG_PATH.is_file():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        return False
    return True

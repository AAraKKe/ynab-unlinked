from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from ynab_unlinked.config.core import (
    TRANSACTION_GRACE_PERIOD_DAYS,
    Checkpoint,
    EntityConfig,
    config_path,
)
from ynab_unlinked.config.migrations import Version
from ynab_unlinked.models import Transaction, TransactionWithYnabData


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

    def save(self):
        config_path().write_text(self.model_dump_json(indent=4))

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
    def load() -> ConfigV2:
        return ConfigV2.model_validate_json(config_path().read_text())

    @staticmethod
    def exists() -> bool:
        return config_path().is_file()

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

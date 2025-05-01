from __future__ import annotations

import datetime as dt
from pathlib import Path

from pydantic import BaseModel

from ynab_unlinked.models import Transaction


CONFIG_PATH = Path.home() / ".config/ynab_unlinked/config.json"
TRANSACTION_GRACE_PERIOD_DAYS = 60


class Checkpoint(BaseModel):
    latest_date_processed: dt.date
    latest_transaction_hash: int


class Config(BaseModel):
    api_key: str
    budget_id: str
    account_id: str
    checkpoint: Checkpoint | None = None

    def save(self):
        CONFIG_PATH.write_text(self.model_dump_json(indent=4))

    def update_and_save(self, last_transaction: Transaction):
        self.checkpoint = Checkpoint(
            latest_date_processed=(
                last_transaction.date - dt.timedelta(days=TRANSACTION_GRACE_PERIOD_DAYS)
            ),
            latest_transaction_hash=hash(last_transaction),
        )
        self.save()

    @staticmethod
    def load() -> Config:
        return Config.model_validate_json(CONFIG_PATH.read_text())


def ensure_config():
    if not CONFIG_PATH.is_file():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        return False
    return True

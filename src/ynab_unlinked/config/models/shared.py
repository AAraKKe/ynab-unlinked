import datetime as dt

from pydantic import BaseModel


class Checkpoint(BaseModel):
    latest_date_processed: dt.date
    latest_transaction_hash: int


class EntityConfig(BaseModel):
    account_id: str
    checkpoint: Checkpoint | None = None

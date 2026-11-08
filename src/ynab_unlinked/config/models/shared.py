import datetime as dt
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel


class Checkpoint(BaseModel):
    latest_date_processed: dt.date
    latest_transaction_hash: int


class EntityConfig(BaseModel):
    account_id: str
    checkpoint: Checkpoint | None = None


class EntityConfigV3(BaseModel):
    account_id: str


def write_private(path: Path, text: str) -> None:
    """Write through a user only temp file in the same directory, then swap it in.

    Every config version goes through it: V1 to V3 hold the token in plain text too.
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # mkstemp creates the file with mode 0o600
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise

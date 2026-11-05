"""The store's schema as numbered SQL scripts, one file per step.

`NNNN_<what>.sql` takes a store at `PRAGMA user_version` NNNN - 1 to NNNN, inside one
transaction run by `apply()`. To change the schema add the next number; never edit a released
script. The store is a cache of the budget, so a script may also drop and refill.

Rules for a script: no `BEGIN` or `COMMIT` inside it (it already runs in a transaction), and
no `PRAGMA foreign_keys` (it cannot change inside a transaction).
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable

from ynab_unlinked.core.progress import NO_PROGRESS, Progress

_FILE_NAME = re.compile(r"^(?P<number>\d{4})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True)
class Migration:
    number: int
    """The schema version the script leaves the store at."""
    file: str
    sql: str


class MigrationFilesError(Exception):
    """The migration files are not `0001_*.sql`, `0002_*.sql`... without gaps."""


class MigrationError(Exception):
    """A script failed; the store is left at the version before it."""


def load(folder: Traversable) -> tuple[Migration, ...]:
    found: list[Migration] = []
    for entry in folder.iterdir():
        if not entry.name.endswith(".sql"):
            continue
        if (match := _FILE_NAME.match(entry.name)) is None:
            raise MigrationFilesError(
                f"{entry.name} is not named NNNN_<what>.sql, so it would never run"
            )
        found.append(Migration(int(match["number"]), entry.name, entry.read_text("utf-8")))
    found.sort(key=lambda migration: migration.number)
    for expected, migration in enumerate(found, start=1):
        if migration.number != expected:
            raise MigrationFilesError(
                f"Expected migration {expected:04d} but found {migration.file}"
            )
    return tuple(found)


MIGRATIONS: tuple[Migration, ...] = load(files(__name__))
SCHEMA_VERSION = len(MIGRATIONS)
"""Equal to the last script's number because `load` refuses gaps."""


def version_of(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def apply(
    conn: sqlite3.Connection,
    migrations: Sequence[Migration] | None = None,
    progress: Progress = NO_PROGRESS,
) -> int:
    """Run the scripts the store has not seen yet, one transaction each. Returns the version.

    `BEGIN IMMEDIATE` makes a second process (the app open while the CLI runs) wait for the
    lock; when it gets it the step may already be done, so the version is read again.
    """
    if migrations is None:
        migrations = MIGRATIONS
    version = version_of(conn)
    for migration in migrations[version:]:
        progress.info(f"Updating the local store ({migration.file})")
        try:
            conn.executescript(
                f"BEGIN IMMEDIATE; {migration.sql}; "
                f"PRAGMA user_version = {migration.number}; COMMIT;"
            )
        except sqlite3.Error as error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            if version_of(conn) >= migration.number:
                continue  # another process applied it first
            raise MigrationError(f"{migration.file}: {error}") from error
    return version_of(conn)

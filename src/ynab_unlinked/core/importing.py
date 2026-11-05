"""Turn the transactions of a bank export into YNAB transactions."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ynab import TransactionClearedStatus

from ynab_unlinked.core.progress import NO_PROGRESS, Progress
from ynab_unlinked.entities import Entity
from ynab_unlinked.models import PendingImport, Transaction, assign_import_ids
from ynab_unlinked.ynab_api.client import Client

IMPORT_BUFFER_DAYS = 15
"""Days before the earliest transaction of a file that YNAB is read from to spot the rows it
already has (`yul load --buffer`, the app's import)."""


@dataclass(frozen=True)
class ImportRow:
    transaction: Transaction
    import_id: str
    already_imported: bool


@dataclass(frozen=True)
class ImportPlan:
    entity_name: str
    account_id: str
    input_file: Path
    rows: tuple[ImportRow, ...]

    @property
    def new_rows(self) -> tuple[ImportRow, ...]:
        return tuple(row for row in self.rows if not row.already_imported)

    @property
    def already_imported_count(self) -> int:
        return sum(1 for row in self.rows if row.already_imported)


@dataclass(frozen=True)
class ImportResult:
    created: int
    duplicate_import_ids: tuple[str, ...]


def file_digest(input_file: Path) -> str:
    """The SHA-256 of the file's bytes: two copies of one export have the same digest."""
    return hashlib.sha256(input_file.read_bytes()).hexdigest()


def unique_files(files: Sequence[Path]) -> tuple[list[Path], list[tuple[Path, Path]]]:
    """
    The files, each export once, and the (copy, first) pairs of the ones left out.

    A second copy would show every row as new again and only be turned away by YNAB, as
    duplicates, once the first copy is in.
    """
    seen: dict[str, Path] = {}
    unique: list[Path] = []
    copies: list[tuple[Path, Path]] = []
    for input_file in files:
        digest = file_digest(input_file)
        if (first := seen.get(digest)) is not None:
            copies.append((input_file, first))
            continue
        seen[digest] = input_file
        unique.append(input_file)
    return unique, copies


def parse_transactions(entity: Entity, input_file: Path) -> list[Transaction]:
    """Read the export with the entity's parser. A `ParsingError` reaches the caller."""
    return entity.parse(input_file)


def build_import_plan(
    client: Client,
    budget_id: str,
    account_id: str,
    entity_name: str,
    input_file: Path,
    transactions: list[Transaction],
    buffer_days: int = IMPORT_BUFFER_DAYS,
    progress: Progress = NO_PROGRESS,
) -> ImportPlan:
    """
    Pair every transaction with its import id and flag the ones YNAB already holds.

    YNAB is read for the account from `buffer_days` before the earliest transaction, so a row
    YNAB dated a few days off from the export is still recognised.
    """
    pending = assign_import_ids(transactions)
    if not pending:
        return ImportPlan(entity_name, account_id, input_file, rows=())

    earliest = min(t.date for t in transactions)

    progress.start("Reading transactions...")
    ynab_transactions = client.transactions(
        budget_id=budget_id,
        account_id=account_id,
        since_date=earliest - dt.timedelta(days=buffer_days),
    )
    progress.done("Transactions read")

    known_ids = frozenset(t.import_id for t in ynab_transactions if t.import_id is not None)
    return ImportPlan(entity_name, account_id, input_file, _rows(pending, known_ids))


def _rows(pending: Sequence[PendingImport], known_ids: frozenset[str]) -> tuple[ImportRow, ...]:
    return tuple(
        ImportRow(
            transaction=p.transaction,
            import_id=p.import_id,
            already_imported=p.import_id in known_ids or p.legacy_import_id in known_ids,
        )
        for p in pending
    )


def commit_import_plan(
    client: Client,
    budget_id: str,
    plan: ImportPlan,
    cleared: TransactionClearedStatus,
    progress: Progress = NO_PROGRESS,
) -> ImportResult:
    """Create the rows YNAB does not hold yet and report the ones it rejected anyway."""
    to_create = plan.new_rows
    if not to_create:
        return ImportResult(created=0, duplicate_import_ids=())

    progress.start("Creating transactions...")
    duplicates = client.create_transactions(
        budget_id=budget_id,
        account_id=plan.account_id,
        # The legacy id only matters to recognise old imports, which the plan already did
        transactions=[PendingImport(row.transaction, row.import_id, "") for row in to_create],
        cleared=cleared,
    )
    progress.done()

    return ImportResult(
        created=len(to_create) - len(duplicates), duplicate_import_ids=tuple(duplicates)
    )

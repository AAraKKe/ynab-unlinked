"""Turn the transactions of a bank export into YNAB transactions."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from ynab import TransactionClearedStatus

from ynab_unlinked.core.progress import NO_PROGRESS, Progress
from ynab_unlinked.models import PendingImport, Transaction, assign_import_ids
from ynab_unlinked.store import Store
from ynab_unlinked.ynab_api.client import Client

IMPORT_BUFFER_DAYS = 15
"""Days before the earliest transaction of a file that YNAB is read from to spot the rows it
already has (`yul load --buffer`, the app's import)."""


class RowStatus(StrEnum):
    NEW = "new"
    """Sent to YNAB on commit."""
    IN_YNAB = "in_ynab"
    """YNAB holds its import id: never sent again."""
    MATCHED = "matched"
    """Matched in YNAB with a transaction entered by hand that did not take the import id (a
    reconciled one): in YNAB too, never sent again."""
    EXCLUDED = "excluded"
    """Left out by the user, saved in the store so later runs leave it out too."""


@dataclass(frozen=True)
class ImportRow:
    transaction: Transaction
    import_id: str
    already_imported: bool
    matched: bool = False
    """YNAB holds it only through a match (`RowStatus.MATCHED`); `already_imported` is True."""
    excluded: bool = False
    """In the store's registry of rows left out of imports."""

    @property
    def status(self) -> RowStatus:
        if self.already_imported:
            return RowStatus.MATCHED if self.matched else RowStatus.IN_YNAB
        return RowStatus.EXCLUDED if self.excluded else RowStatus.NEW


@dataclass(frozen=True)
class ImportPlan:
    entity_name: str
    account_id: str
    input_file: Path
    rows: tuple[ImportRow, ...]
    unknown_matches: int = 0
    """Transactions of the account matched in YNAB to one this computer has no copy of (the
    budget copy is not synced, or older than the match). A row of the file they took may
    show as new although YNAB holds it; the registry is the way out."""

    @property
    def new_rows(self) -> tuple[ImportRow, ...]:
        return self.with_status(RowStatus.NEW)

    @property
    def already_imported_count(self) -> int:
        return sum(1 for row in self.rows if row.already_imported)

    def with_status(self, status: RowStatus) -> tuple[ImportRow, ...]:
        return tuple(row for row in self.rows if row.status is status)

    def include(self, import_ids: Collection[str]) -> ImportPlan:
        """The plan with these rows sent on commit again."""
        return self._change(import_ids, excluded=False)

    def exclude(self, import_ids: Collection[str]) -> ImportPlan:
        """The plan with these rows left out of the commit."""
        return self._change(import_ids, excluded=True)

    def _change(self, import_ids: Collection[str], *, excluded: bool) -> ImportPlan:
        return replace(
            self,
            rows=tuple(
                replace(row, excluded=excluded) if row.import_id in import_ids else row
                for row in self.rows
            ),
        )


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


def build_import_plan(
    client: Client,
    budget_id: str,
    account_id: str,
    entity_name: str,
    input_file: Path,
    transactions: list[Transaction],
    buffer_days: int = IMPORT_BUFFER_DAYS,
    progress: Progress = NO_PROGRESS,
    store: Store | None = None,
) -> ImportPlan:
    """
    Pair every transaction with its import id and give each row its status.

    YNAB is read for the account from `buffer_days` before the earliest transaction, so a row
    YNAB dated a few days off from the export is still recognised.

    `store`, the budget copy, adds what the account listing cannot show:

    - Matches. When the user matches an imported transaction with one entered by hand, YNAB
      keeps the latter and copies the import id onto it, except onto a reconciled one: that
      one only points at the imported transaction (`matched_transaction_id`), which YNAB
      hides from the listing and answers 404 for. Only the copy, filled by the delta, still
      holds that transaction and its import id, so a row with that id is in YNAB.
    - The rows the user left out of imports to the account (`RowStatus.EXCLUDED`).
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
    # Survivors that did not take the import id of the transaction they were matched with
    pointers = {
        t.matched_transaction_id
        for t in ynab_transactions
        if not t.deleted and t.import_id is None and t.matched_transaction_id is not None
    } - {t.id for t in ynab_transactions}
    matched_ids: dict[str, str] = {}
    excluded: frozenset[str] = frozenset()
    if store is not None:
        matched_ids = store.import_ids(budget_id, pointers)
        excluded = frozenset(row.import_id for row in store.excluded(budget_id, account_id))

    rows = _rows(pending, known_ids, frozenset(matched_ids.values()))
    plan = ImportPlan(
        entity_name,
        account_id,
        input_file,
        rows,
        unknown_matches=len(pointers - matched_ids.keys()),
    )
    return plan.exclude(excluded)


def _rows(
    pending: Sequence[PendingImport], known_ids: frozenset[str], matched_ids: frozenset[str]
) -> tuple[ImportRow, ...]:
    rows: list[ImportRow] = []
    for p in pending:
        held = p.import_id in known_ids or p.legacy_import_id in known_ids
        matched = not held and p.import_id in matched_ids
        rows.append(
            ImportRow(
                transaction=p.transaction,
                import_id=p.import_id,
                already_imported=held or matched,
                matched=matched,
            )
        )
    return tuple(rows)


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

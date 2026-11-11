"""Turn the transactions of a bank export into YNAB transactions."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from ynab import TransactionClearedStatus, TransactionDetail

from ynab_unlinked.core.progress import NO_PROGRESS, Progress
from ynab_unlinked.models import PendingImport, Transaction, assign_import_ids, milliunits
from ynab_unlinked.store import Store
from ynab_unlinked.ynab_api.client import Client

IMPORT_BUFFER_DAYS = 15
"""Days before the earliest transaction of a file that YNAB is read from to spot the rows it
already has (`yul load --buffer`, the app's import)."""

MATCH_WINDOW_DAYS = 10
"""How far apart YNAB still matches an imported transaction with one entered by hand of the
same amount."""


class RowStatus(StrEnum):
    NEW = "new"
    """Sent to YNAB on commit."""
    IN_YNAB = "in_ynab"
    """YNAB holds its import id: never sent again."""
    MATCHED = "matched"
    """Matched in YNAB with a transaction entered by hand that did not take the import id (a
    reconciled one): in YNAB too, never sent again."""
    MAYBE_IN_YNAB = "maybe_in_ynab"
    """Probably the import behind a match the budget copy has no record of (`ImportRow.twin`):
    held back until the user sends it anyway or leaves it out."""
    EXCLUDED = "excluded"
    """Left out by the user, saved in the store so later runs leave it out too."""


@dataclass(frozen=True)
class Twin:
    """A transaction entered by hand that YNAB matched with an imported one nobody can name.

    YNAB hides the imported transaction and the budget copy never saw it (it was matched
    before a sync brought it), so its import id is lost. A row of the same amount around
    this date is most likely that import.
    """

    date: dt.date
    payee: str


@dataclass(frozen=True)
class ImportRow:
    transaction: Transaction
    import_id: str
    already_imported: bool
    matched: bool = False
    """YNAB holds it only through a match (`RowStatus.MATCHED`); `already_imported` is True."""
    excluded: bool = False
    """In the store's registry of rows left out of imports."""
    twin: Twin | None = None
    """The transaction in YNAB this row may already be (`RowStatus.MAYBE_IN_YNAB`)."""
    anyway: bool = False
    """The user sends it although it has a `twin`. Only for this plan: once sent, YNAB holds
    its import id."""

    @property
    def status(self) -> RowStatus:
        if self.already_imported:
            return RowStatus.MATCHED if self.matched else RowStatus.IN_YNAB
        if self.excluded:
            return RowStatus.EXCLUDED
        if self.twin is not None and not self.anyway:
            return RowStatus.MAYBE_IN_YNAB
        return RowStatus.NEW


@dataclass(frozen=True)
class ImportPlan:
    entity_name: str
    account_id: str
    input_file: Path
    rows: tuple[ImportRow, ...]

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

    def send_anyway(self, import_ids: Collection[str]) -> ImportPlan:
        """The plan with these rows sent on commit although they may be in YNAB."""
        return self._change(import_ids, anyway=True)

    def _change(self, import_ids: Collection[str], **fields: bool) -> ImportPlan:
        return replace(
            self,
            rows=tuple(
                replace(row, **fields) if row.import_id in import_ids else row for row in self.rows
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

    A match the copy cannot name (it never saw the imported transaction, or there is no
    copy) leaves only the transaction entered by hand. A row YNAB does not hold with the
    same amount, dated within `MATCH_WINDOW_DAYS` of it, gets it as its `twin` and is held
    back (`RowStatus.MAYBE_IN_YNAB`); each such transaction is the twin of one row, the
    closest in date.
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

    unnamed = [
        t
        for t in ynab_transactions
        if not t.deleted
        and t.import_id is None
        and t.matched_transaction_id in pointers - matched_ids.keys()
    ]
    rows = _with_twins(_rows(pending, known_ids, frozenset(matched_ids.values())), unnamed)
    return ImportPlan(entity_name, account_id, input_file, rows).exclude(excluded)


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


def _with_twins(
    rows: tuple[ImportRow, ...], unnamed: Sequence[TransactionDetail]
) -> tuple[ImportRow, ...]:
    """The rows, each one YNAB does not hold paired with the transaction of `unnamed` it may be.

    Closest dates first, each side once: of two rows of the same amount only one is the
    import a transaction was matched with.
    """
    pairs = sorted(
        (abs((survivor.var_date - row.transaction.date).days), index, position)
        for index, row in enumerate(rows)
        if not row.already_imported
        for position, survivor in enumerate(unnamed)
        if survivor.amount == milliunits(row.transaction.amount)
        and abs((survivor.var_date - row.transaction.date).days) <= MATCH_WINDOW_DAYS
    )
    twins: dict[int, Twin] = {}
    taken: set[int] = set()
    for _, index, position in pairs:
        if index in twins or position in taken:
            continue
        taken.add(position)
        survivor = unnamed[position]
        twins[index] = Twin(date=survivor.var_date, payee=survivor.payee_name or "")
    return tuple(
        replace(row, twin=twins[index]) if index in twins else row for index, row in enumerate(rows)
    )


def commit_import_plan(
    client: Client,
    budget_id: str,
    plan: ImportPlan,
    cleared: TransactionClearedStatus,
    progress: Progress = NO_PROGRESS,
    store: Store | None = None,
) -> ImportResult:
    """Create the rows YNAB does not hold yet and report the ones it rejected anyway.

    The transactions YNAB created go into `store`, the budget copy, at once. A match made in
    YNAB before the next sync hides the imported transaction from every later answer: saved
    here, the copy can still name it (`build_import_plan`) the next time the row is in a file.
    """
    to_create = plan.new_rows
    if not to_create:
        return ImportResult(created=0, duplicate_import_ids=())

    progress.start("Creating transactions...")
    created = client.create_transactions(
        budget_id=budget_id,
        account_id=plan.account_id,
        # The legacy id only matters to recognise old imports, which the plan already did
        transactions=[PendingImport(row.transaction, row.import_id, "") for row in to_create],
        cleared=cleared,
    )
    progress.done()

    if store is not None:
        try:
            store.save_transactions(budget_id, created.transactions)
        except Exception as error:
            # YNAB has them: the next sync brings them, unless they are matched before it
            progress.warn(f"The new transactions could not be saved on this computer: {error}")

    duplicates = created.duplicate_import_ids
    return ImportResult(
        created=len(to_create) - len(duplicates), duplicate_import_ids=tuple(duplicates)
    )

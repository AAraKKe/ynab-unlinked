"""Turn the transactions of a bank export into YNAB transactions."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from itertools import islice
from pathlib import Path
from typing import Any

from ynab import TransactionClearedStatus

from ynab_unlinked.context_object import YnabUnlinkedContext
from ynab_unlinked.core.progress import NO_PROGRESS, Progress
from ynab_unlinked.entities import Entity
from ynab_unlinked.models import PendingImport, Transaction, assign_import_ids
from ynab_unlinked.ynab_api.client import Client


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
    known_import_ids: frozenset[str] = field(default=frozenset(), repr=False)
    """The import ids YNAB held for the account when the plan was built."""

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


def parse_transactions(
    entity: Entity, input_file: Path, context: YnabUnlinkedContext[Any]
) -> list[Transaction]:
    """Read the export with the entity's parser. A `ParsingError` reaches the caller."""
    return entity.parse(input_file, context)


def build_import_plan(
    client: Client,
    budget_id: str,
    account_id: str,
    entity_name: str,
    input_file: Path,
    transactions: list[Transaction],
    buffer_days: int = 15,
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
    return ImportPlan(entity_name, account_id, input_file, _rows(pending, known_ids), known_ids)


def share_import_ids(plans: Sequence[ImportPlan]) -> list[ImportPlan]:
    """
    The plans, in the same order, with the import ids numbered over every file of an account.

    Import ids count the occurrence of a date and amount (`YNAB:-5000:2025-05-01:1`). Two
    files that feed one account in the same import (a Cobee page and a card statement) would
    each number a same day, same amount row `:1`, and YNAB would reject the second one as
    already imported. Numbered as if the files were one, they are `:1` and `:2`.
    """
    groups: dict[str, list[ImportPlan]] = {}
    for plan in plans:
        groups.setdefault(plan.account_id, []).append(plan)

    shared: dict[int, ImportPlan] = {}
    for group in groups.values():
        known = frozenset[str]().union(*(plan.known_import_ids for plan in group))
        union = iter(assign_import_ids([row.transaction for plan in group for row in plan.rows]))
        for plan in group:
            # Legacy ids were numbered per file, keep reading them that way
            legacy = assign_import_ids([row.transaction for row in plan.rows])
            pending = [
                replace(own, import_id=numbered.import_id)
                for own, numbered in zip(legacy, islice(union, len(plan.rows)), strict=True)
            ]
            shared[id(plan)] = replace(plan, rows=_rows(pending, known), known_import_ids=known)

    return [shared[id(plan)] for plan in plans]


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

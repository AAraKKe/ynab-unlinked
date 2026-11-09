from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from collections.abc import Generator, Iterable, Mapping, Sequence
from contextlib import closing, contextmanager, suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from urllib3.exceptions import HTTPError
from ynab import (
    Account,
    ApiException,
    CategoryGroupWithCategories,
    MonthSummary,
    TransactionClearedStatus,
    TransactionDetail,
)

from ynab_unlinked.core.progress import NO_PROGRESS, Progress
from ynab_unlinked.store import migrations
from ynab_unlinked.ynab_api import FULL_SYNC_SINCE, Client
from ynab_unlinked.ynab_api.errors import api_status

# What YNAB answers when the server knowledge of a delta request is no longer valid. The only
# way out is a full fetch.
STALE_KNOWLEDGE_STATUS = 409


_UNRECONCILED = (TransactionClearedStatus.CLEARED, TransactionClearedStatus.UNCLEARED)
_BUDGET_TABLES = (
    "transactions",
    "subtransactions",
    "accounts",
    "categories",
    "months",
    "sync_state",
    "ghost_checks",
)

STARTING_BALANCE_PAYEE = "Starting Balance"
"""The payee YNAB gives the first transaction of every account."""

# YNAB allows 200 requests an hour: the ghost repair leaves most of them to the import
GHOST_CHECKS_PER_SYNC = 50

# The CLI and the app share the file: a write waits this long for the other one to finish
BUSY_TIMEOUT_SECONDS = 30


class StoreError(Exception):
    pass


@dataclass(frozen=True)
class StoredTransaction:
    id: str
    account_id: str
    date: dt.date
    amount: int
    cleared: TransactionClearedStatus
    approved: bool
    deleted: bool
    payee_name: str | None
    category_name: str | None
    import_id: str | None
    memo: str | None
    transfer_account_id: str | None
    matched_transaction_id: str | None = None
    """The transaction YNAB matched this one with; the other row is merged away."""
    category_id: str | None = None


@dataclass(frozen=True)
class StoredAccount:
    id: str
    name: str
    type: str
    closed: bool
    on_budget: bool
    balance: int
    cleared_balance: int
    uncleared_balance: int


@dataclass(frozen=True)
class StoredCategory:
    id: str
    name: str
    group_id: str
    group_name: str
    hidden: bool
    internal: bool
    """YNAB's own categories (Inflow: Ready to Assign, Uncategorized), not the user's."""
    balance: int
    """Available this month, milliunits."""
    goal_type: str | None = None
    """YNAB's target type: TB, TBD (a balance to reach), MF, NEED, DEBT."""
    goal_target: int | None = None
    goal_target_date: dt.date | None = None
    note: str | None = None


@dataclass(frozen=True)
class Line:
    """One line of money in an account: a transaction, or one line of a split transaction.

    The lines of a split replace it, so the amounts of an account's lines add up to its
    balance like its transactions do.
    """

    transaction_id: str
    account_id: str
    date: dt.date
    amount: int
    payee_name: str | None
    category_id: str | None
    category_name: str | None
    transfer_account_id: str | None


@dataclass(frozen=True)
class SyncResult:
    full: bool
    transactions_changed: int
    accounts: int
    server_knowledge: int
    categories: int = 0
    ghosts_removed: int = 0
    """Rows YNAB merged away without a tombstone, flagged deleted by the ghost repair."""


@dataclass(frozen=True)
class Activity:
    at: dt.datetime
    kind: str
    message: str
    details: dict[str, Any]


@dataclass(frozen=True)
class ExcludedRow:
    """A row of a bank export the user left out of imports to an account."""

    account_id: str
    import_id: str
    """The registry's key with the account: the same row of a later export has the same id."""
    date: dt.date
    amount: int
    """Milliunits."""
    payee: str
    excluded_at: dt.datetime | None = None
    """When it was left out; None on a row not saved yet."""


@dataclass(frozen=True)
class DailyAmounts:
    """What the balance history of one account is built from."""

    balance: int | None
    """`StoredAccount.balance`, None when the account is not in the store."""
    days: tuple[tuple[dt.date, int], ...]
    """Sum of the account's non deleted transactions per day, oldest first."""


def _timestamp(at: dt.datetime | None = None) -> str:
    # Fixed width and always UTC, so ordering by the text column orders by time
    moment = dt.datetime.now(dt.UTC) if at is None else at.astimezone(dt.UTC)
    return moment.isoformat(timespec="microseconds")


class Store:
    """A local copy of YNAB data in the SQLite file at `path`, created on first use.

    Every method opens its own connection, so one store can be shared across threads. The
    file is in WAL mode and a write waits up to `BUSY_TIMEOUT_SECONDS` for another process
    (the CLI and the app at once), so reads never block and writes rarely fail.
    Timestamps are timezone aware, in UTC.
    """

    def __init__(self, path: Path):
        self.path = path
        self._open()

    def _open(self) -> None:
        """Create the file (for the user only) when missing, and bring its schema up to date."""
        path = self.path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # The budget's transactions are for the user only (SQLite gives its journal the same mode)
        if not path.exists():
            os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
        with suppress(OSError):
            path.chmod(0o600)
            # mkdir's mode does nothing to a folder that already exists (the app made it)
            path.parent.chmod(0o700)
        with closing(sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
            # Readers never wait for a writer. The mode is kept in the file, set once is enough
            conn.execute("PRAGMA journal_mode=WAL")
            conn.row_factory = sqlite3.Row
            with conn:
                self._migrate(conn)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection]:
        if not self.path.exists():
            # Deleted under an open store (`yul config reset` while the app runs): SQLite
            # would create an empty file without tables, so set it up again
            self._open()
        with closing(sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                yield conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        version = migrations.version_of(conn)
        if version > migrations.SCHEMA_VERSION:
            raise StoreError(
                f"The local store at {self.path} was written by a newer version of yul "
                f"(schema {version}, this version knows up to {migrations.SCHEMA_VERSION})."
            )
        try:
            migrations.apply(conn)
        except migrations.MigrationError as error:
            raise StoreError(
                f"The local store at {self.path} could not be updated: {error}"
            ) from error

    def sync(
        self,
        client: Client,
        budget_id: str,
        progress: Progress = NO_PROGRESS,
    ) -> SyncResult:
        """Bring the budget's transactions and accounts up to date with YNAB.

        The first sync of a budget fetches every transaction; later ones only what changed
        since the stored server knowledge. If YNAB rejects that knowledge, the budget is
        forgotten and fetched again from scratch.
        """
        knowledge = self._server_knowledge(budget_id)
        try:
            result, received = self._sync(client, budget_id, knowledge, progress)
        except ApiException as error:
            if knowledge is None or api_status(error) != STALE_KNOWLEDGE_STATUS:
                raise
            progress.warn("YNAB could not send only the changes, fetching everything again")
            with self._connect() as conn:
                self._forget(conn, budget_id)
            result, received = self._sync(client, budget_id, None, progress)
        # On a full sync every row was just received, so every group counts
        ghosts = self._repair_ghosts(client, budget_id, None if result.full else received, progress)
        return replace(result, ghosts_removed=ghosts)

    def _repair_ghosts(
        self,
        client: Client,
        budget_id: str,
        received: set[str] | None,
        progress: Progress,
    ) -> int:
        """Flag deleted the rows YNAB merged away without telling the delta. Returns how many.

        YNAB matches an imported transaction (one with an `import_id`, from yul or from a
        bank's direct import) against a manually entered or scheduled one of the same
        account. When the user approves the match, the manual transaction survives, takes the
        `import_id` and points at the imported one through `matched_transaction_id`, and the
        imported id simply disappears: GET /transactions/{id} answers 404, yet no delta ever
        reports it as deleted. The store keeps both rows, and the ghost shows up as "to
        reconcile" forever. A reconciled transaction takes no import id when matched (YNAB
        leaves a reconciled transaction as it is): then only `matched_transaction_id` ties the
        survivor to the merged import.

        After such a merge the store holds two or more non deleted rows with the same
        `(account_id, import_id)`, counting a row without an import id under the id of the
        non deleted row it points at, and only one of them still exists in YNAB. So every id
        of those groups is checked against YNAB and the missing ones become tombstones, like
        a delete from YNAB. A group where every row exists (a match not approved yet) is left
        alone. Without duplicate groups no request is made, so a normal sync costs nothing.

        The merge always changes the surviving row, so only groups holding a row of
        `received` (the ids this sync brought, None for every row on a full sync) are checked:
        a match waiting for approval costs requests only on the sync that brings it, not on
        every sync after. YNAB allows 200 requests an hour, so one sync checks at most
        `GHOST_CHECKS_PER_SYNC` ids, whole groups only (a single larger group is checked
        whole). The groups left over are kept in `ghost_checks`, a warning says so, and the
        next sync checks them first. The check is best effort: when YNAB refuses or cannot
        be reached it is skipped with a warning (the sync itself already committed) and the
        groups it was going to check are kept for the next sync.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "WITH keyed AS ("
                "  SELECT t.id, t.account_id, COALESCE(t.import_id, m.import_id) AS import_id"
                "  FROM transactions t LEFT JOIN transactions m"
                "    ON m.budget_id = t.budget_id AND m.id = t.matched_transaction_id"
                "    AND m.deleted = 0"
                "  WHERE t.budget_id = ? AND t.deleted = 0"
                ") "
                "SELECT k.id, k.account_id, k.import_id FROM keyed k JOIN ("
                "  SELECT account_id, import_id FROM keyed WHERE import_id IS NOT NULL"
                "  GROUP BY account_id, import_id HAVING COUNT(*) > 1"
                ") d ON k.account_id = d.account_id AND k.import_id = d.import_id "
                "ORDER BY k.id",
                (budget_id,),
            ).fetchall()
            left_over = {
                (row["account_id"], row["import_id"])
                for row in conn.execute(
                    "SELECT account_id, import_id FROM ghost_checks WHERE budget_id = ?",
                    (budget_id,),
                )
            }
        groups: dict[tuple[str, str], list[str]] = {}
        for row in rows:
            groups.setdefault((row["account_id"], row["import_id"]), []).append(row["id"])
        # What an earlier sync left goes first, so every group is checked eventually
        due = sorted(
            (
                key
                for key, group in groups.items()
                if key in left_over or received is None or not received.isdisjoint(group)
            ),
            key=lambda key: key not in left_over,
        )
        checked: list[tuple[str, str]] = []
        candidates: list[str] = []
        for key in due:
            if candidates and len(candidates) + len(groups[key]) > GHOST_CHECKS_PER_SYNC:
                break
            checked.append(key)
            candidates.extend(groups[key])
        waiting = due[len(checked) :]
        if not candidates:
            self._keep_ghost_checks(budget_id, waiting)
            return 0

        progress.start("Checking transactions YNAB may have merged")
        try:
            ghosts = [
                transaction_id
                for transaction_id in candidates
                if not client.transaction_exists(budget_id, transaction_id)
            ]
        except (ApiException, HTTPError, OSError) as error:
            self._keep_ghost_checks(budget_id, due)
            progress.warn(f"Could not check the transactions YNAB may have merged: {error}")
            return 0
        self._keep_ghost_checks(budget_id, waiting)
        with self._connect() as conn:
            conn.executemany(
                "UPDATE transactions SET deleted = 1 WHERE budget_id = ? AND id = ?",
                [(budget_id, ghost) for ghost in ghosts],
            )
        progress.done(f"{len(ghosts)} stale transactions removed")
        if waiting:
            unchecked = sum(len(groups[key]) for key in waiting)
            progress.warn(
                f"{unchecked} more transactions YNAB may have merged will be checked "
                "on the next sync"
            )
        return len(ghosts)

    def _keep_ghost_checks(self, budget_id: str, keys: Sequence[tuple[str, str]]) -> None:
        """Make `keys` the groups the next ghost repair of the budget checks first."""
        with self._connect() as conn:
            conn.execute("DELETE FROM ghost_checks WHERE budget_id = ?", (budget_id,))
            conn.executemany(
                "INSERT INTO ghost_checks (budget_id, account_id, import_id) VALUES (?, ?, ?)",
                [(budget_id, account_id, import_id) for account_id, import_id in keys],
            )

    def _sync(
        self,
        client: Client,
        budget_id: str,
        knowledge: int | None,
        progress: Progress,
    ) -> tuple[SyncResult, set[str]]:
        """Fetch and save one batch. Returns the result and the ids of the rows received."""
        # The copy is as new as the fetch, not the write: a CLI write logged in between must
        # count as newer than the sync, so `fresh()` in the app syncs again
        fetched_at = _timestamp()
        if knowledge is None:
            progress.start("Fetching all transactions from YNAB")
            transactions, new_knowledge = client.transactions_with_knowledge(
                budget_id, since_date=FULL_SYNC_SINCE
            )
        else:
            progress.start("Fetching the transactions changed since the last sync")
            transactions, new_knowledge = client.transactions_delta(budget_id, knowledge)
        progress.done(f"{len(transactions)} transactions received")

        progress.start("Fetching accounts from YNAB")
        accounts = [account for account in client.accounts(budget_id) if not account.deleted]
        progress.done(f"{len(accounts)} accounts received")

        progress.start("Fetching categories from YNAB")
        groups = client.categories(budget_id)
        categories = sum(len(group.categories) for group in groups if not group.deleted)
        progress.done(f"{categories} categories received")

        progress.start("Fetching months from YNAB")
        months = client.months(budget_id)
        progress.done(f"{len(months)} months received")

        progress.start("Saving to the local store")
        with self._connect() as conn:
            self._upsert_transactions(conn, budget_id, transactions)
            self._replace_accounts(conn, budget_id, accounts)
            self._replace_categories(conn, budget_id, groups)
            self._replace_months(conn, budget_id, months)
            # With two app runs on one file, an older delta can be written last: never let
            # the knowledge go back
            conn.execute(
                "INSERT INTO sync_state (budget_id, server_knowledge, synced_at) "
                "VALUES (?, ?, ?) ON CONFLICT (budget_id) DO UPDATE SET "
                "server_knowledge = excluded.server_knowledge, synced_at = excluded.synced_at "
                "WHERE excluded.server_knowledge >= sync_state.server_knowledge",
                (budget_id, new_knowledge, fetched_at),
            )
        progress.done()

        result = SyncResult(
            full=knowledge is None,
            transactions_changed=len(transactions),
            accounts=len(accounts),
            server_knowledge=new_knowledge,
            categories=categories,
        )
        return result, {t.id for t in transactions}

    def _server_knowledge(self, budget_id: str) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT server_knowledge FROM sync_state WHERE budget_id = ?", (budget_id,)
            ).fetchone()
        return None if row is None else int(row["server_knowledge"])

    @staticmethod
    def _upsert_transactions(
        conn: sqlite3.Connection, budget_id: str, transactions: Sequence[TransactionDetail]
    ) -> None:
        conn.executemany(
            "INSERT OR REPLACE INTO transactions (budget_id, id, account_id, date, amount, "
            "cleared, approved, deleted, payee_name, category_name, import_id, memo, "
            "transfer_account_id, matched_transaction_id, category_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    budget_id,
                    t.id,
                    str(t.account_id),
                    t.var_date.isoformat(),
                    t.amount,
                    t.cleared.value,
                    t.approved,
                    t.deleted,
                    t.payee_name,
                    t.category_name,
                    t.import_id,
                    t.memo,
                    None if t.transfer_account_id is None else str(t.transfer_account_id),
                    None if t.matched_transaction_id is None else str(t.matched_transaction_id),
                    _text(t.category_id),
                )
                for t in transactions
            ],
        )
        # A changed split comes back whole, so its lines are replaced, never merged
        conn.executemany(
            "DELETE FROM subtransactions WHERE budget_id = ? AND transaction_id = ?",
            [(budget_id, t.id) for t in transactions],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO subtransactions (budget_id, id, transaction_id, amount, "
            "memo, payee_name, category_id, category_name, transfer_account_id, deleted) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    budget_id,
                    sub.id,
                    t.id,
                    sub.amount,
                    sub.memo,
                    sub.payee_name,
                    _text(sub.category_id),
                    sub.category_name,
                    _text(sub.transfer_account_id),
                    sub.deleted,
                )
                for t in transactions
                for sub in t.subtransactions
            ],
        )

    @staticmethod
    def _replace_months(
        conn: sqlite3.Connection, budget_id: str, months: Sequence[MonthSummary]
    ) -> None:
        conn.execute("DELETE FROM months WHERE budget_id = ?", (budget_id,))
        conn.executemany(
            "INSERT OR REPLACE INTO months (budget_id, month, note, income, budgeted, activity) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (budget_id, m.month.isoformat(), m.note, m.income, m.budgeted, m.activity)
                for m in months
            ],
        )

    @staticmethod
    def _replace_categories(
        conn: sqlite3.Connection, budget_id: str, groups: Sequence[CategoryGroupWithCategories]
    ) -> None:
        conn.execute("DELETE FROM categories WHERE budget_id = ?", (budget_id,))
        live = [
            (group, category)
            for group in groups
            if not group.deleted
            for category in group.categories
            if not category.deleted
        ]
        conn.executemany(
            "INSERT INTO categories (budget_id, id, name, group_id, group_name, position, "
            "hidden, internal, balance, goal_type, goal_target, goal_target_date, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    budget_id,
                    str(category.id),
                    category.name,
                    str(group.id),
                    group.name,
                    position,
                    category.hidden or group.hidden,
                    category.internal or group.internal,
                    category.balance,
                    category.goal_type,
                    category.goal_target,
                    None
                    if category.goal_target_date is None
                    else category.goal_target_date.isoformat(),
                    category.note,
                )
                for position, (group, category) in enumerate(live)
            ],
        )

    @staticmethod
    def _replace_accounts(
        conn: sqlite3.Connection, budget_id: str, accounts: Sequence[Account]
    ) -> None:
        conn.execute("DELETE FROM accounts WHERE budget_id = ?", (budget_id,))
        conn.executemany(
            "INSERT INTO accounts (budget_id, id, name, type, closed, on_budget, balance, "
            "cleared_balance, uncleared_balance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    budget_id,
                    str(a.id),
                    a.name,
                    a.type.value,
                    a.closed,
                    a.on_budget,
                    a.balance,
                    a.cleared_balance,
                    a.uncleared_balance,
                )
                for a in accounts
            ],
        )

    @staticmethod
    def _forget(conn: sqlite3.Connection, budget_id: str | None) -> None:
        for table in _BUDGET_TABLES:
            if budget_id is None:
                conn.execute(f"DELETE FROM {table}")
            else:
                conn.execute(f"DELETE FROM {table} WHERE budget_id = ?", (budget_id,))

    def accounts(self, budget_id: str) -> list[StoredAccount]:
        """Every account of the budget, closed ones included, sorted by name."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM accounts WHERE budget_id = ? ORDER BY name, id", (budget_id,)
            ).fetchall()
        return [
            StoredAccount(
                id=row["id"],
                name=row["name"],
                type=row["type"],
                closed=bool(row["closed"]),
                on_budget=bool(row["on_budget"]),
                balance=row["balance"],
                cleared_balance=row["cleared_balance"],
                uncleared_balance=row["uncleared_balance"],
            )
            for row in rows
        ]

    def categories(self, budget_id: str) -> list[StoredCategory]:
        """Every category of the budget, hidden and internal ones included, in YNAB's order."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM categories WHERE budget_id = ? ORDER BY position", (budget_id,)
            ).fetchall()
        return [
            StoredCategory(
                id=row["id"],
                name=row["name"],
                group_id=row["group_id"],
                group_name=row["group_name"],
                hidden=bool(row["hidden"]),
                internal=bool(row["internal"]),
                balance=row["balance"],
                goal_type=row["goal_type"],
                goal_target=row["goal_target"],
                goal_target_date=None
                if row["goal_target_date"] is None
                else dt.date.fromisoformat(row["goal_target_date"]),
                note=row["note"],
            )
            for row in rows
        ]

    def month_notes(self, budget_id: str) -> dict[dt.date, str]:
        """The note of every month that has one, keyed by the month's first day."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT month, note FROM months WHERE budget_id = ? AND note IS NOT NULL "
                "AND trim(note) != ''",
                (budget_id,),
            ).fetchall()
        return {dt.date.fromisoformat(row["month"]): row["note"].strip() for row in rows}

    def lines(
        self,
        budget_id: str,
        *,
        since: dt.date | None = None,
        until: dt.date | None = None,
    ) -> list[Line]:
        """The lines of every non deleted transaction, oldest first; `since`/`until` inclusive.

        A split transaction is replaced by its lines, which take its date and account (and its
        payee when they name none). A transaction is one line.
        """
        dates = ""
        params: list[str] = []
        if since is not None:
            dates += " AND t.date >= ?"
            params.append(since.isoformat())
        if until is not None:
            dates += " AND t.date <= ?"
            params.append(until.isoformat())
        query = (
            "SELECT t.id AS transaction_id, t.account_id, t.date, t.amount, t.payee_name, "
            "t.category_id, t.category_name, t.transfer_account_id FROM transactions t "
            f"WHERE t.budget_id = ? AND t.deleted = 0{dates} AND NOT EXISTS ("
            "  SELECT 1 FROM subtransactions s WHERE s.budget_id = t.budget_id"
            "  AND s.transaction_id = t.id AND s.deleted = 0) "
            "UNION ALL "
            "SELECT t.id, t.account_id, t.date, s.amount, COALESCE(s.payee_name, t.payee_name), "
            "s.category_id, s.category_name, s.transfer_account_id FROM subtransactions s "
            "JOIN transactions t ON t.budget_id = s.budget_id AND t.id = s.transaction_id "
            f"WHERE t.budget_id = ? AND t.deleted = 0 AND s.deleted = 0{dates} "
            "ORDER BY date, transaction_id"
        )
        with self._connect() as conn:
            rows = conn.execute(query, [budget_id, *params, budget_id, *params]).fetchall()
        return [
            Line(
                transaction_id=row["transaction_id"],
                account_id=row["account_id"],
                date=dt.date.fromisoformat(row["date"]),
                amount=row["amount"],
                payee_name=row["payee_name"],
                category_id=row["category_id"],
                category_name=row["category_name"],
                transfer_account_id=row["transfer_account_id"],
            )
            for row in rows
        ]

    def transactions(
        self,
        budget_id: str,
        *,
        account_id: str | None = None,
        since: dt.date | None = None,
        until: dt.date | None = None,
        cleared: Iterable[TransactionClearedStatus] | None = None,
    ) -> list[StoredTransaction]:
        """Transactions not deleted in YNAB, oldest first. `since` and `until` are inclusive."""
        query = "SELECT * FROM transactions WHERE budget_id = ? AND deleted = 0"
        params: list[str] = [budget_id]

        if account_id is not None:
            query += " AND account_id = ?"
            params.append(account_id)
        if since is not None:
            query += " AND date >= ?"
            params.append(since.isoformat())
        if until is not None:
            query += " AND date <= ?"
            params.append(until.isoformat())
        if cleared is not None:
            statuses = [status.value for status in cleared]
            if not statuses:
                return []
            query += f" AND cleared IN ({', '.join('?' * len(statuses))})"
            params.extend(statuses)

        query += " ORDER BY date, id"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_stored_transaction(row) for row in rows]

    def daily_amounts(
        self, budget_id: str, account_ids: Iterable[str] | None = None
    ) -> dict[str, DailyAmounts]:
        """Per account, its stored balance and what its transactions add up to each day.

        Every account of the budget, or only `account_ids`, in a single query. Accounts with
        neither transactions nor a stored row are left out.
        """
        transactions_filter = accounts_filter = ""
        ids: list[str] = []
        if account_ids is not None:
            ids = list(account_ids)
            if not ids:
                return {}
            placeholders = ", ".join("?" * len(ids))
            transactions_filter = f" AND account_id IN ({placeholders})"
            accounts_filter = f" AND id IN ({placeholders})"

        # The accounts half has no date, which tells the balances apart from the daily sums
        query = (
            "SELECT account_id, date, SUM(amount) AS amount FROM transactions "
            f"WHERE budget_id = ? AND deleted = 0{transactions_filter} GROUP BY account_id, date "
            "UNION ALL "
            f"SELECT id, NULL, balance FROM accounts WHERE budget_id = ?{accounts_filter} "
            "ORDER BY account_id, date"
        )
        with self._connect() as conn:
            rows = conn.execute(query, [budget_id, *ids, budget_id, *ids]).fetchall()

        balances: dict[str, int] = {}
        days: dict[str, list[tuple[dt.date, int]]] = {}
        for row in rows:
            account_id: str = row["account_id"]
            days.setdefault(account_id, [])
            if row["date"] is None:
                balances[account_id] = row["amount"]
            else:
                days[account_id].append((dt.date.fromisoformat(row["date"]), row["amount"]))

        return {
            account_id: DailyAmounts(balance=balances.get(account_id), days=tuple(account_days))
            for account_id, account_days in days.items()
        }

    def unreconciled(self, budget_id: str) -> list[StoredTransaction]:
        """Every transaction not reconciled yet, in any account, oldest first."""
        return self.transactions(budget_id, cleared=_UNRECONCILED)

    def last_sync(self, budget_id: str) -> dt.datetime | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT synced_at FROM sync_state WHERE budget_id = ?", (budget_id,)
            ).fetchone()
        return None if row is None else dt.datetime.fromisoformat(row["synced_at"])

    def clear(self, budget_id: str | None = None, *, activity: bool = False) -> None:
        """Forget the copy of a budget, or of every budget when none is given.

        The next sync of a cleared budget is a full one. The activity log stays (it is what
        yul did, not a copy of YNAB) unless `activity` is True. The rows left out of imports
        always stay: they are the user's choice, deleted with the store file.
        """
        with self._connect() as conn:
            self._forget(conn, budget_id)
            if not activity:
                return
            if budget_id is None:
                conn.execute("DELETE FROM activity")
            else:
                conn.execute("DELETE FROM activity WHERE budget_id = ?", (budget_id,))

    def log(
        self,
        budget_id: str,
        kind: str,
        message: str,
        details: Mapping[str, Any] | None = None,
        *,
        at: dt.datetime | None = None,
    ) -> None:
        """Record something yul did, for the activity feed. `details` must be JSON serialisable.

        `at` (timezone aware) defaults to now.
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO activity (budget_id, at, kind, message, details) "
                "VALUES (?, ?, ?, ?, ?)",
                (budget_id, _timestamp(at), kind, message, json.dumps(dict(details or {}))),
            )

    def last_activity(self, budget_id: str) -> dt.datetime | None:
        """When the newest activity entry of the budget was logged."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT max(at) AS at FROM activity WHERE budget_id = ?", (budget_id,)
            ).fetchone()
        return None if row["at"] is None else dt.datetime.fromisoformat(row["at"])

    def last_import_per_loader(self, budget_id: str) -> dict[str, dt.datetime]:
        """When each bank last imported, keyed by the `loader` of the `import` entries.

        One grouped query, so the log is never read whole. Entries without a `loader`
        string are left out.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT json_extract(details, '$.loader') AS loader, max(at) AS at "
                "FROM activity WHERE budget_id = ? AND kind = 'import' "
                "AND json_type(details, '$.loader') = 'text' GROUP BY loader",
                (budget_id,),
            ).fetchall()
        return {row["loader"]: dt.datetime.fromisoformat(row["at"]) for row in rows}

    def activity(
        self, budget_id: str, limit: int | None = 20, *, kind: str | None = None
    ) -> list[Activity]:
        """The latest `limit` entries (all when None) of the activity log, newest first.

        `kind` keeps only the entries of that kind.
        """
        query = "SELECT at, kind, message, details FROM activity WHERE budget_id = ?"
        params: list[str | int] = [budget_id]
        if kind is not None:
            query += " AND kind = ?"
            params.append(kind)
        # SQLite reads a negative limit as no limit
        query += " ORDER BY at DESC, rowid DESC LIMIT ?"
        params.append(-1 if limit is None else limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            Activity(
                at=dt.datetime.fromisoformat(row["at"]),
                kind=row["kind"],
                message=row["message"],
                details=json.loads(row["details"]),
            )
            for row in rows
        ]

    def import_ids(self, budget_id: str, transaction_ids: Iterable[str]) -> dict[str, str]:
        """The import id of each of these transactions that has one, deleted ones included.

        A transaction YNAB matched away is hidden from its listings and answers 404, but the
        copy still holds it with the import id it was created with.
        """
        ids = list(transaction_ids)
        if not ids:
            return {}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, import_id FROM transactions WHERE budget_id = ? AND "
                f"import_id IS NOT NULL AND id IN ({', '.join('?' * len(ids))})",
                [budget_id, *ids],
            ).fetchall()
        return {row["id"]: row["import_id"] for row in rows}

    def exclude(self, budget_id: str, row: ExcludedRow) -> None:
        """Leave `row` out of every import to its account from now on."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO excluded_rows (budget_id, account_id, import_id, date, "
                "amount, payee, excluded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    budget_id,
                    row.account_id,
                    row.import_id,
                    row.date.isoformat(),
                    row.amount,
                    row.payee,
                    _timestamp(row.excluded_at),
                ),
            )

    def include(self, budget_id: str, account_id: str, import_id: str) -> bool:
        """Import the row again from now on. False when it was not left out."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM excluded_rows WHERE budget_id = ? AND account_id = ? "
                "AND import_id = ?",
                (budget_id, account_id, import_id),
            )
        return cursor.rowcount > 0

    def excluded(self, budget_id: str, account_id: str | None = None) -> list[ExcludedRow]:
        """The rows left out of imports to the budget, or to one account, newest row first."""
        query = "SELECT * FROM excluded_rows WHERE budget_id = ?"
        params = [budget_id]
        if account_id is not None:
            query += " AND account_id = ?"
            params.append(account_id)
        query += " ORDER BY date DESC, payee, import_id"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            ExcludedRow(
                account_id=row["account_id"],
                import_id=row["import_id"],
                date=dt.date.fromisoformat(row["date"]),
                amount=row["amount"],
                payee=row["payee"],
                excluded_at=dt.datetime.fromisoformat(row["excluded_at"]),
            )
            for row in rows
        ]


def _text(value: object | None) -> str | None:
    """An id of the SDK (a UUID) as the store keeps it."""
    return None if value is None else str(value)


def _stored_transaction(row: sqlite3.Row) -> StoredTransaction:
    return StoredTransaction(
        id=row["id"],
        account_id=row["account_id"],
        date=dt.date.fromisoformat(row["date"]),
        amount=row["amount"],
        cleared=TransactionClearedStatus(row["cleared"]),
        approved=bool(row["approved"]),
        deleted=bool(row["deleted"]),
        payee_name=row["payee_name"],
        category_name=row["category_name"],
        import_id=row["import_id"],
        memo=row["memo"],
        transfer_account_id=row["transfer_account_id"],
        matched_transaction_id=row["matched_transaction_id"],
        category_id=row["category_id"],
    )

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ynab import Account, ApiException, TransactionClearedStatus, TransactionDetail

from ynab_unlinked.core.progress import NO_PROGRESS, Progress
from ynab_unlinked.store import migrations
from ynab_unlinked.ynab_api import Client

# YNAB's get_transactions defaults to one year ago without a since_date, so a full sync asks
# for everything explicitly. The balance history needs the starting balance transaction.
FULL_SYNC_SINCE = dt.date(1900, 1, 1)

# What YNAB answers when the server knowledge of a delta request is no longer valid. The only
# way out is a full fetch.
STALE_KNOWLEDGE_STATUS = 409


_UNRECONCILED = (TransactionClearedStatus.CLEARED, TransactionClearedStatus.UNCLEARED)
_BUDGET_TABLES = ("transactions", "accounts", "sync_state")


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
class SyncResult:
    full: bool
    transactions_changed: int
    accounts: int
    server_knowledge: int
    ghosts_removed: int = 0
    """Rows YNAB merged away without a tombstone, flagged deleted by the ghost repair."""


@dataclass(frozen=True)
class Activity:
    at: dt.datetime
    kind: str
    message: str
    details: dict[str, Any]


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

    Every method opens its own connection, so one store can be shared across threads.
    Timestamps are timezone aware, in UTC.
    """

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            self._migrate(conn)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path)) as conn:
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
            result = self._sync(client, budget_id, knowledge, progress)
        except ApiException as error:
            if knowledge is None or error.status != STALE_KNOWLEDGE_STATUS:
                raise
            progress.warn("YNAB could not send only the changes, fetching everything again")
            with self._connect() as conn:
                self._forget(conn, budget_id)
            result = self._sync(client, budget_id, None, progress)
        return replace(result, ghosts_removed=self._repair_ghosts(client, budget_id, progress))

    def _repair_ghosts(self, client: Client, budget_id: str, progress: Progress) -> int:
        """Flag deleted the rows YNAB merged away without telling the delta. Returns how many.

        YNAB matches an imported transaction (one with an `import_id`, from yul or from a
        bank's direct import) against a manually entered or scheduled one of the same
        account. When the user approves the match, the manual transaction survives, takes the
        `import_id` and points at the imported one through `matched_transaction_id`, and the
        imported id simply disappears: GET /transactions/{id} answers 404, yet no delta ever
        reports it as deleted. The store keeps both rows, and the ghost shows up as "to
        reconcile" forever.

        After such a merge the store holds two or more non deleted rows with the same
        `(account_id, import_id)`, and only one of them still exists in YNAB. So every id of
        those groups is checked against YNAB and the missing ones become tombstones, like a
        delete from YNAB. A group where every row exists (a match not approved yet) is left
        alone. Without duplicate groups no request is made, so a normal sync costs nothing.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT t.id FROM transactions t JOIN ("
                "  SELECT account_id, import_id FROM transactions"
                "  WHERE budget_id = ? AND deleted = 0 AND import_id IS NOT NULL"
                "  GROUP BY account_id, import_id HAVING COUNT(*) > 1"
                ") d ON t.account_id = d.account_id AND t.import_id = d.import_id "
                "WHERE t.budget_id = ? AND t.deleted = 0 ORDER BY t.id",
                (budget_id, budget_id),
            ).fetchall()
        if not rows:
            return 0

        progress.start("Checking transactions YNAB may have merged")
        ghosts = [row["id"] for row in rows if not client.transaction_exists(budget_id, row["id"])]
        with self._connect() as conn:
            conn.executemany(
                "UPDATE transactions SET deleted = 1 WHERE budget_id = ? AND id = ?",
                [(budget_id, ghost) for ghost in ghosts],
            )
        progress.done(f"{len(ghosts)} stale transactions removed")
        return len(ghosts)

    def _sync(
        self,
        client: Client,
        budget_id: str,
        knowledge: int | None,
        progress: Progress,
    ) -> SyncResult:
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

        progress.start("Saving to the local store")
        with self._connect() as conn:
            self._upsert_transactions(conn, budget_id, transactions)
            self._replace_accounts(conn, budget_id, accounts)
            conn.execute(
                "INSERT OR REPLACE INTO sync_state (budget_id, server_knowledge, synced_at) "
                "VALUES (?, ?, ?)",
                (budget_id, new_knowledge, _timestamp()),
            )
        progress.done()

        return SyncResult(
            full=knowledge is None,
            transactions_changed=len(transactions),
            accounts=len(accounts),
            server_knowledge=new_knowledge,
        )

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
            "transfer_account_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                )
                for t in transactions
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

    def upsert(
        self,
        budget_id: str,
        *,
        accounts: Iterable[StoredAccount] = (),
        transactions: Iterable[StoredTransaction] = (),
    ) -> None:
        """Insert or replace accounts and transactions, matched by id, in one transaction.

        For writes yul made to YNAB itself (so the store reflects them before the next sync)
        and for tests. The sync state is left alone: the next delta sync still sends them.
        """
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO accounts (budget_id, id, name, type, closed, on_budget, "
                "balance, cleared_balance, uncleared_balance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        budget_id,
                        a.id,
                        a.name,
                        a.type,
                        a.closed,
                        a.on_budget,
                        a.balance,
                        a.cleared_balance,
                        a.uncleared_balance,
                    )
                    for a in accounts
                ],
            )
            conn.executemany(
                "INSERT OR REPLACE INTO transactions (budget_id, id, account_id, date, amount, "
                "cleared, approved, deleted, payee_name, category_name, import_id, memo, "
                "transfer_account_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        budget_id,
                        t.id,
                        t.account_id,
                        t.date.isoformat(),
                        t.amount,
                        t.cleared.value,
                        t.approved,
                        t.deleted,
                        t.payee_name,
                        t.category_name,
                        t.import_id,
                        t.memo,
                        t.transfer_account_id,
                    )
                    for t in transactions
                ],
            )

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

    def clear(self, budget_id: str | None = None) -> None:
        """Forget everything about a budget, or about every budget when none is given.

        The activity log goes too. The next sync of a cleared budget is a full one.
        """
        with self._connect() as conn:
            self._forget(conn, budget_id)
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
    )

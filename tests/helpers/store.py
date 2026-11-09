import sqlite3
from collections.abc import Iterable
from contextlib import closing

from ynab_unlinked.store import Store, StoredAccount, StoredTransaction


def upsert(
    store: Store,
    budget_id: str,
    *,
    accounts: Iterable[StoredAccount] = (),
    transactions: Iterable[StoredTransaction] = (),
) -> None:
    """Seed the store with accounts and transactions, replaced by id, in one transaction.

    The sync state is left alone, so `last_sync` keeps what the last `Store.sync` set.
    """
    with closing(sqlite3.connect(store.path)) as conn, conn:
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
            "transfer_account_id, matched_transaction_id, category_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    t.matched_transaction_id,
                    t.category_id,
                )
                for t in transactions
            ],
        )

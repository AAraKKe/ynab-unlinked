-- Schema 6: what the finance views read. The category id of every transaction, the lines of
-- split transactions (a split's own category is only "Split"), and the budget's categories
-- with their group and goal. The sync state goes, so the next sync is a full one and fills
-- the new columns for the transactions already in the copy.
ALTER TABLE transactions ADD COLUMN category_id TEXT;
CREATE TABLE subtransactions (
    budget_id TEXT NOT NULL,
    id TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    amount INTEGER NOT NULL,
    memo TEXT,
    payee_name TEXT,
    category_id TEXT,
    category_name TEXT,
    transfer_account_id TEXT,
    deleted INTEGER NOT NULL,
    PRIMARY KEY (budget_id, id)
);
CREATE INDEX subtransactions_by_transaction ON subtransactions (budget_id, transaction_id);
CREATE TABLE categories (
    budget_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    group_id TEXT NOT NULL,
    group_name TEXT NOT NULL,
    position INTEGER NOT NULL,
    hidden INTEGER NOT NULL,
    internal INTEGER NOT NULL,
    balance INTEGER NOT NULL,
    goal_type TEXT,
    goal_target INTEGER,
    goal_target_date TEXT,
    note TEXT,
    PRIMARY KEY (budget_id, id)
);
DELETE FROM sync_state;

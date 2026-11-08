-- Schema 1: the budget copy (accounts, transactions, sync state) and the activity log.
CREATE TABLE accounts (
    budget_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    closed INTEGER NOT NULL,
    on_budget INTEGER NOT NULL,
    balance INTEGER NOT NULL,
    cleared_balance INTEGER NOT NULL,
    uncleared_balance INTEGER NOT NULL,
    PRIMARY KEY (budget_id, id)
);
CREATE TABLE transactions (
    budget_id TEXT NOT NULL,
    id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    date TEXT NOT NULL,
    amount INTEGER NOT NULL,
    cleared TEXT NOT NULL,
    approved INTEGER NOT NULL,
    deleted INTEGER NOT NULL,
    payee_name TEXT,
    category_name TEXT,
    import_id TEXT,
    memo TEXT,
    transfer_account_id TEXT,
    PRIMARY KEY (budget_id, id)
);
CREATE INDEX transactions_by_account_date ON transactions (budget_id, account_id, date);
CREATE TABLE sync_state (
    budget_id TEXT PRIMARY KEY,
    server_knowledge INTEGER NOT NULL,
    synced_at TEXT NOT NULL
);
CREATE TABLE activity (
    budget_id TEXT NOT NULL,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    details TEXT NOT NULL
);
CREATE INDEX activity_by_budget_at ON activity (budget_id, at);

-- Schema 5: the rows of bank exports the user left out of imports, by import id, so later
-- imports of the same statement leave them out too. Date, amount and payee are only for
-- showing them. Not a copy of YNAB: a resync keeps them.
CREATE TABLE excluded_rows (
    budget_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    import_id TEXT NOT NULL,
    date TEXT NOT NULL,
    amount INTEGER NOT NULL,
    payee TEXT NOT NULL,
    excluded_at TEXT NOT NULL,
    PRIMARY KEY (budget_id, account_id, import_id)
);

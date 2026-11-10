-- Schema 7: the budget's months as YNAB sums them, with the note the user wrote on each. The
-- note labels a month in the finance views. Replaced on every sync.
CREATE TABLE months (
    budget_id TEXT NOT NULL,
    month TEXT NOT NULL,
    note TEXT,
    income INTEGER NOT NULL,
    budgeted INTEGER NOT NULL,
    activity INTEGER NOT NULL,
    PRIMARY KEY (budget_id, month)
);

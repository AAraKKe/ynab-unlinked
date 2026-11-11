-- Schema 10: what every category held in each past month, as YNAB's month view shows it. The
-- Plan measures how fast the goal grows from it. YNAB sends one month per request, so a sync
-- only asks for the months not in `fetched_months` yet (and the last one again, once a day).
CREATE TABLE category_months (
    budget_id TEXT NOT NULL,
    month TEXT NOT NULL,
    category_id TEXT NOT NULL,
    budgeted INTEGER NOT NULL,
    activity INTEGER NOT NULL,
    balance INTEGER NOT NULL,
    PRIMARY KEY (budget_id, month, category_id)
);

CREATE TABLE fetched_months (
    budget_id TEXT NOT NULL,
    month TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (budget_id, month)
);

-- Schema 2: the duplicate import id groups the ghost repair could not check yet (it checks a
-- limited number per sync), so the next sync checks them first.
CREATE TABLE ghost_checks (
    budget_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    import_id TEXT NOT NULL,
    PRIMARY KEY (budget_id, account_id, import_id)
);

-- Schema 3: the ghost repair groups the budget's rows by (account_id, import_id) on every
-- sync; without an index that reads the whole table.
CREATE INDEX transactions_by_import_id ON transactions (budget_id, account_id, import_id);

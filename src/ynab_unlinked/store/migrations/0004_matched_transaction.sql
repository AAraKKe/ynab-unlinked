-- Schema 4: the transaction a row was matched with in YNAB. After a match, the surviving
-- row points at the one YNAB merged away, and the ghost repair uses that pointer when the
-- survivor kept no import id (a reconciled transaction takes none).
ALTER TABLE transactions ADD COLUMN matched_transaction_id TEXT;

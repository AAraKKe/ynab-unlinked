-- Schema 8: the transaction a split line transfers to. YNAB sends that transaction (the other
-- side of the transfer) without a transfer account: only the split line points at it, so
-- without this column the other side reads as money from nowhere. The sync state goes, so the
-- next sync is a full one that fills it in.
ALTER TABLE subtransactions ADD COLUMN transfer_transaction_id TEXT;
DELETE FROM sync_state;

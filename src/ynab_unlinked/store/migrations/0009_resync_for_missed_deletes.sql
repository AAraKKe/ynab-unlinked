-- Schema 9: one more full sync. A full sync now flags deleted the rows YNAB no longer has, so a
-- delete that a delta missed (seen when transactions were deleted through the API in quick
-- succession) leaves the copy.
DELETE FROM sync_state;

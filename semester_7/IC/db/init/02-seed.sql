-- Initial data (docs/00-common.md §6.4): 200 accounts with 10 000.00 each,
-- an `opening` ledger entry per account, and the scenario row in `normal`.
SET client_encoding = 'UTF8';

BEGIN;

-- Rows are inserted in order of n, so the identity gives account n the id n.
INSERT INTO accounts (owner_name, balance)
SELECT format('Клієнт %s', lpad(n::text, 3, '0')), 10000.00
FROM generate_series(1, 200) AS n
ORDER BY n;

INSERT INTO ledger_entries (account_id, kind, delta)
SELECT id, 'opening', balance
FROM accounts
ORDER BY id;

COMMIT;

INSERT INTO scenario_state (id, scenario, lock_order, lock_gap_ms, sleep_ms)
VALUES (1, 'normal', 'sorted', 0, 0);

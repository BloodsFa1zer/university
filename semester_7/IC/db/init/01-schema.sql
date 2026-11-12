-- Schema of the bank database (docs/00-common.md §6.4).
-- Runs once, on an empty data volume: after a change here use `make clean && make up`.

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

CREATE TABLE accounts (
  id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  owner_name  text NOT NULL,
  balance     numeric(14,2) NOT NULL CHECK (balance >= 0),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE transfers (
  id            uuid PRIMARY KEY,
  from_account  integer NOT NULL REFERENCES accounts(id),
  to_account    integer NOT NULL REFERENCES accounts(id),
  amount        numeric(14,2) NOT NULL CHECK (amount > 0),
  status        text NOT NULL CHECK (status IN ('completed', 'failed')),
  fail_reason   text,
  attempts      smallint NOT NULL DEFAULT 1,
  requested_at  timestamptz NOT NULL,
  processed_at  timestamptz NOT NULL DEFAULT now(),
  CHECK (from_account <> to_account),
  CHECK ((status = 'failed') = (fail_reason IS NOT NULL))
);
CREATE INDEX transfers_from_idx ON transfers (from_account, processed_at DESC);
CREATE INDEX transfers_to_idx   ON transfers (to_account, processed_at DESC);

CREATE TABLE ledger_entries (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id   integer NOT NULL REFERENCES accounts(id),
  transfer_id  uuid REFERENCES transfers(id),
  kind         text NOT NULL CHECK (kind IN ('opening', 'transfer_out', 'transfer_in', 'deposit')),
  delta        numeric(14,2) NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ledger_account_idx ON ledger_entries (account_id, created_at DESC);

CREATE TABLE scenario_state (
  id           smallint PRIMARY KEY CHECK (id = 1),
  scenario     text NOT NULL,
  lock_order   text NOT NULL CHECK (lock_order IN ('sorted', 'naive')),
  lock_gap_ms  integer NOT NULL CHECK (lock_gap_ms >= 0),
  sleep_ms     integer NOT NULL CHECK (sleep_ms >= 0),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

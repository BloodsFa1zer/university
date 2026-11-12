#!/usr/bin/env bash
# Roles of the bank database (docs/00-common.md §6.4):
#   APP_DB_USER     — worker and generator: read and write the four tables, nothing else;
#   MONITOR_DB_USER — exporter and SQL probe: pg_monitor plus read access to accounts.
# Names and passwords come from the environment and are passed to psql as variables,
# which psql quotes itself (:"name" for identifiers, :'name' for literals).
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -v db_name="$POSTGRES_DB" \
  -v app_user="$APP_DB_USER" \
  -v app_password="$APP_DB_PASSWORD" \
  -v monitor_user="$MONITOR_DB_USER" \
  -v monitor_password="$MONITOR_DB_PASSWORD" <<'SQL'
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password';
CREATE ROLE :"monitor_user" LOGIN PASSWORD :'monitor_password';

GRANT CONNECT ON DATABASE :"db_name" TO :"app_user", :"monitor_user";
GRANT USAGE ON SCHEMA public TO :"app_user", :"monitor_user";

GRANT SELECT, INSERT, UPDATE ON accounts, transfers, ledger_entries, scenario_state
  TO :"app_user";

GRANT pg_monitor TO :"monitor_user";
GRANT SELECT ON accounts TO :"monitor_user";
SQL

#!/bin/sh
set -eu

# A one-off job also works when the PostgreSQL volume already exists.
psql -X -v ON_ERROR_STOP=1 -h postgres -U "$POSTGRES_USER" -d postgres \
  -v chat_user="$CHAT_POSTGRES_USER" -v chat_password="$CHAT_POSTGRES_PASSWORD" \
  -v chat_database="$CHAT_POSTGRES_DB" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'chat_user', :'chat_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'chat_user') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'chat_database', :'chat_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'chat_database') \gexec
SQL

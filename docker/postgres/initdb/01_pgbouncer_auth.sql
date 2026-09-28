-- docker/postgres/initdb/01_pgbouncer_auth.sql
--
-- Bootstrap for PgBouncer's auth_query (see docker/pgbouncer/pgbouncer.ini
-- and docs/infra/pgbouncer.md). Creates:
--   1. A dedicated, unprivileged `pgbouncer_auth` role that PgBouncer
--      uses only to run the lookup query below — it is not the
--      application's database user and has no table access.
--   2. A SECURITY DEFINER function that looks up a user's SCRAM
--      verifier from pg_shadow, so PgBouncer never needs its own copy
--      of every app user's password in userlist.txt.
--
-- WHEN THIS RUNS: files under /docker-entrypoint-initdb.d/ are only
-- executed by the official postgres image on a *fresh* data directory
-- (an empty `postgres_data` volume). It will NOT run against an
-- existing database — see docs/infra/pgbouncer.md §Bootstrap for the
-- one-time manual steps to apply this to a database that already has
-- data.
--
-- The password below is a placeholder. Rotate it immediately after
-- first run:
--   ALTER ROLE pgbouncer_auth WITH PASSWORD '<a real secret>';
-- and regenerate docker/pgbouncer/userlist.txt from pg_shadow
-- afterwards (docs/infra/pgbouncer.md).

CREATE ROLE pgbouncer_auth WITH LOGIN PASSWORD 'CHANGE_ME_IMMEDIATELY';

-- Only needs to open a connection to run the lookup function below —
-- no table privileges of any kind.
GRANT CONNECT ON DATABASE stock_db TO pgbouncer_auth;

CREATE OR REPLACE FUNCTION public.user_lookup(in_username text, OUT username text, OUT password text)
RETURNS record
LANGUAGE sql
SECURITY DEFINER
STABLE
AS $$
    SELECT usename::text, passwd::text
    FROM pg_catalog.pg_shadow
    WHERE usename = in_username;
$$;

-- SECURITY DEFINER functions run with the privileges of their owner
-- (the role that created them, typically POSTGRES_USER here) unless
-- locked down — without this REVOKE/GRANT pair, any role that can
-- connect to the database could call user_lookup() and read every
-- other user's password verifier.
REVOKE ALL ON FUNCTION public.user_lookup(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.user_lookup(text) TO pgbouncer_auth;

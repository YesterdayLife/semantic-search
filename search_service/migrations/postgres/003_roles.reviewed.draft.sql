-- DEPLOY-01C.2E.1 reviewed draft. Do not execute this file in DEPLOY-01C.2E.1.
-- Execute it only after a separate owner approval for DEPLOY-01C.2E.2.
--
-- Create the role with SQL. Do not use the Neon Console "Add role" button,
-- the Neon API, or `neon roles create` without `--access`. Those paths make
-- the role a member of neon_superuser, which inherits pg_write_all_data.
--
-- The password is not in this file. The approved runner must bind a generated
-- password as the psql variable app_password, or as a driver parameter.
-- A password must have at least 60 bits of entropy. Neon stores it as SCRAM.
--
-- This script is one transaction. A failure rolls the role back with it.
-- It does not change 001_schema.sql, 002_pgvector.sql, table data, or the
-- existing neondb_owner connection string.

BEGIN;

CREATE ROLE s1g14_staging_app
  LOGIN
  PASSWORD :'app_password'
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE
  NOINHERIT
  NOREPLICATION
  NOBYPASSRLS
  CONNECTION LIMIT 20;

REVOKE ALL PRIVILEGES ON DATABASE s1g14_staging FROM s1g14_staging_app;
GRANT CONNECT ON DATABASE s1g14_staging TO s1g14_staging_app;

-- PUBLIC currently has TEMPORARY on this database. The owner and
-- neon_superuser already have their own TEMPORARY grant, so this revoke
-- does not remove their access. It removes the remaining way for the
-- application role to create a temporary table.
REVOKE TEMPORARY ON DATABASE s1g14_staging FROM PUBLIC;

-- PostgreSQL 18 on this branch already grants PUBLIC only USAGE on public.
-- Repeat the revoke so a later restore cannot silently restore CREATE.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO s1g14_staging_app;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM s1g14_staging_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO s1g14_staging_app;

-- Existing tables are owned by neondb_owner. The earlier draft targeted
-- s1g14_staging_migrator, which does not exist and does not own these tables.
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA public
  GRANT SELECT ON TABLES TO s1g14_staging_app;

ALTER ROLE s1g14_staging_app SET default_transaction_read_only = on;
ALTER ROLE s1g14_staging_app SET statement_timeout = '5s';

COMMIT;

-- Privilege audit, after commit, still as neondb_owner and still read-only.
-- Expect no rows from the membership query.
--
-- SELECT rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolreplication, rolbypassrls, rolconnlimit
-- FROM pg_roles WHERE rolname = 's1g14_staging_app';
--
-- SELECT granted.rolname
-- FROM pg_auth_members AS link
-- JOIN pg_roles AS member ON member.oid = link.member
-- JOIN pg_roles AS granted ON granted.oid = link.roleid
-- WHERE member.rolname = 's1g14_staging_app';
--
-- SELECT has_table_privilege('s1g14_staging_app', relation.oid, 'SELECT') AS can_select,
--        has_table_privilege('s1g14_staging_app', relation.oid, 'INSERT') AS can_insert,
--        has_table_privilege('s1g14_staging_app', relation.oid, 'UPDATE') AS can_update,
--        has_table_privilege('s1g14_staging_app', relation.oid, 'DELETE') AS can_delete,
--        has_table_privilege('s1g14_staging_app', relation.oid, 'TRUNCATE') AS can_truncate
-- FROM pg_class AS relation
-- JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
-- WHERE namespace.nspname = 'public' AND relation.relkind = 'r'
-- ORDER BY relation.relname;

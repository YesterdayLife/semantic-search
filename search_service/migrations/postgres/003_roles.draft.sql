-- DEPLOY-01C.1 role draft. Do not execute this file until the owner approves a Neon write.
-- Create the passwords in the Neon console or a client session. Do not commit them.
-- The application role is not a member of the migration role and does not inherit its grants.

-- CREATE ROLE s1g14_staging_migrator LOGIN PASSWORD '<set outside this file>' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
-- The migration role owns the empty staging database for the load window only.
-- After validation, revoke its LOGIN or drop it. Do not use it as the application role.
-- Do not grant the application role membership in the migration role.

-- CREATE ROLE s1g14_staging_app LOGIN PASSWORD '<set outside this file>' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;

-- Run the following only after 001_schema.sql, 002_pgvector.sql, and the data load.
-- Replace s1g14_staging with the approved staging database name before execution.
-- The migration role must own the schema, so revoking CREATE from PUBLIC does not remove its owner rights.
-- Do not point this file at a populated database.

GRANT CONNECT ON DATABASE s1g14_staging TO s1g14_staging_app;
GRANT USAGE ON SCHEMA public TO s1g14_staging_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO s1g14_staging_app;
ALTER DEFAULT PRIVILEGES FOR ROLE s1g14_staging_migrator IN SCHEMA public GRANT SELECT ON TABLES TO s1g14_staging_app;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM s1g14_staging_app;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public FROM s1g14_staging_app;

ALTER ROLE s1g14_staging_app SET default_transaction_read_only = on;
ALTER ROLE s1g14_staging_app SET statement_timeout = '5s';

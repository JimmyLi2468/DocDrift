-- Runs once, when the PostgreSQL container first creates its data volume.
-- Two login roles: the loader owns and writes the records; the reader (used by the
-- API) can only SELECT them, plus append to the audit table. Passwords here are for a
-- local demo; change them for anything shared.

CREATE ROLE docdrift_loader LOGIN PASSWORD 'docdrift_loader';
CREATE ROLE docdrift_reader LOGIN PASSWORD 'docdrift_reader';

CREATE SCHEMA docdrift AUTHORIZATION docdrift_loader;
GRANT USAGE ON SCHEMA docdrift TO docdrift_reader;
-- Tables the loader creates later are readable, and only readable, by the reader.
ALTER DEFAULT PRIVILEGES FOR ROLE docdrift_loader IN SCHEMA docdrift
    GRANT SELECT ON TABLES TO docdrift_reader;

-- Audit: append-only for the API. No UPDATE or DELETE is granted to anyone but the owner.
CREATE SCHEMA docdrift_audit AUTHORIZATION docdrift_loader;
CREATE TABLE docdrift_audit.conversation_turns (
    turn_id         TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    asked_at        TEXT NOT NULL,
    question        TEXT NOT NULL,
    governance_mode TEXT NOT NULL,
    equipment       TEXT,
    status          TEXT NOT NULL,
    answered        INTEGER NOT NULL,
    pending_change  TEXT,
    decision        TEXT NOT NULL
);
ALTER TABLE docdrift_audit.conversation_turns OWNER TO docdrift_loader;
GRANT USAGE ON SCHEMA docdrift_audit TO docdrift_reader;
GRANT SELECT, INSERT ON docdrift_audit.conversation_turns TO docdrift_reader;

-- Nobody but the owners may create objects in the public schema.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

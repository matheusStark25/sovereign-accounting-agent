-- Migration: create append-only audit_log table and trigger
-- Run this DDL against your Postgres instance referenced by POSTGRES_DSN

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    event_type TEXT NOT NULL,
    user_id TEXT,
    audit_id TEXT,
    payload JSONB
);

-- Prevent DELETE/UPDATE to keep table append-only
CREATE OR REPLACE FUNCTION prevent_audit_modification()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_prevent_mods ON audit_log;
CREATE TRIGGER audit_prevent_mods
BEFORE UPDATE OR DELETE ON audit_log
FOR EACH ROW EXECUTE FUNCTION prevent_audit_modification();

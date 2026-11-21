-- VINTO OFF-04.8D - PROPOSAL ONLY. Never automatically migrated or deployed.
-- Requires the existing isolated vinto_offline schema from OFF-04.4.
-- Do NOT put this file in backend/migrations without an independent rollout gate.
-- No FKs to operational tables and no grants outside the isolated schema.

DO $$
BEGIN
    IF to_regclass('vinto_offline.capture_receipt') IS NULL THEN
        RAISE EXCEPTION 'OFF-04.8D requires OFF-04.4 schema';
    END IF;
    IF to_regclass('vinto_offline.capture_scope_authority') IS NOT NULL THEN
        RAISE EXCEPTION 'capture scope authority table already exists; refuse unreviewed replacement';
    END IF;
END $$;

CREATE TABLE vinto_offline.capture_scope_authority (
    snapshot_id        uuid PRIMARY KEY,
    subject_user_id    uuid NOT NULL,
    device_key         uuid NOT NULL,
    payload_sha256     text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    envelope           jsonb NOT NULL,
    issued_at          timestamptz NOT NULL,
    expires_at         timestamptz NOT NULL,
    revoked_at         timestamptz,
    created_at         timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (expires_at > issued_at AND expires_at <= issued_at + INTERVAL '24 hours'),
    CHECK (revoked_at IS NULL OR revoked_at >= issued_at)
);
CREATE INDEX capture_scope_subject_idx
    ON vinto_offline.capture_scope_authority(subject_user_id, expires_at)
    WHERE revoked_at IS NULL;

-- Immutable signed identity. Only one-way revocation is allowed; never delete.
CREATE FUNCTION vinto_offline.guard_capture_scope_authority() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'capture scope authority is append-only except revocation';
    END IF;
    IF OLD.snapshot_id <> NEW.snapshot_id
       OR OLD.subject_user_id <> NEW.subject_user_id
       OR OLD.device_key <> NEW.device_key
       OR OLD.payload_sha256 <> NEW.payload_sha256
       OR OLD.envelope <> NEW.envelope
       OR OLD.issued_at <> NEW.issued_at
       OR OLD.expires_at <> NEW.expires_at
       OR OLD.created_at <> NEW.created_at
       OR OLD.revoked_at IS NOT NULL
       OR NEW.revoked_at IS NULL THEN
        RAISE EXCEPTION 'capture scope fields are immutable; only initial revocation allowed';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER capture_scope_authority_guard
BEFORE UPDATE OR DELETE ON vinto_offline.capture_scope_authority
FOR EACH ROW EXECUTE FUNCTION vinto_offline.guard_capture_scope_authority();

REVOKE ALL ON vinto_offline.capture_scope_authority FROM PUBLIC;
GRANT SELECT, INSERT ON vinto_offline.capture_scope_authority TO vinto_app;
GRANT UPDATE (revoked_at) ON vinto_offline.capture_scope_authority TO vinto_app;

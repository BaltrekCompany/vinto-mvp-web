-- VINTO authentication domain. No users, passwords, hashes or tokens are seeded here.
--
-- Secrets (password_hash, token_hash) live ONLY in vinto_auth. No table in this
-- schema has the vinto_audit.record_change trigger, because that trigger copies
-- the whole row (to_jsonb) into vinto_audit.audit_event. Security events are
-- recorded in vinto_auth.auth_event, which carries no secret columns.

CREATE SCHEMA vinto_auth;

-- One credential per user. password_hash is an Argon2id encoded string produced
-- by the application; the database never sees the plain password.
CREATE TABLE vinto_auth."credential" (
 user_id uuid PRIMARY KEY,
 username text NOT NULL,
 password_hash text NOT NULL,
 hash_algorithm text NOT NULL,
 failed_attempts integer NOT NULL DEFAULT 0,
 locked_until timestamptz,
 must_change boolean NOT NULL DEFAULT false,
 password_changed_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid,
 CONSTRAINT credential_username_shape CHECK (username = btrim(username) AND char_length(username) BETWEEN 1 AND 64),
 CONSTRAINT credential_password_hash_present CHECK (password_hash <> ''),
 CONSTRAINT credential_hash_algorithm_known CHECK (hash_algorithm IN ('argon2id')),
 CONSTRAINT credential_failed_attempts_nonnegative CHECK (failed_attempts >= 0)
);

-- Case-insensitive uniqueness without an extension (no citext).
CREATE UNIQUE INDEX credential_username_lower_key ON vinto_auth."credential" (lower(username));

-- Server-side sessions. The client holds an opaque random token; only its
-- SHA-256 (64 lowercase hex characters) is stored. Sessions have no
-- created_by/updated_by: the session owner is user_id, so an actor column
-- would be redundant.
CREATE TABLE vinto_auth."session" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL,
 token_hash text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 expires_at timestamptz NOT NULL,
 last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 revoked_at timestamptz,
 CONSTRAINT session_token_hash_key UNIQUE (token_hash),
 CONSTRAINT session_token_hash_sha256_hex CHECK (token_hash ~ '^[a-f0-9]{64}$'),
 CONSTRAINT session_expires_after_creation CHECK (expires_at > created_at),
 CONSTRAINT session_revoked_not_before_creation CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);

-- Append-only security events. No password, token or hash columns by design.
-- user_id is NULL when the attempted username does not exist. The attempted
-- username is deliberately NOT stored: users sometimes type a password into the
-- username field, which would leak a secret into the log.
CREATE TABLE vinto_auth."auth_event" (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 user_id uuid,
 event text NOT NULL,
 occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 request_id text,
 CONSTRAINT auth_event_event_known CHECK (event IN ('login_ok','login_fail','logout','lockout','password_change'))
);

ALTER TABLE vinto_auth."credential" ADD CONSTRAINT credential_user_fk FOREIGN KEY (user_id) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;
ALTER TABLE vinto_auth."credential" ADD CONSTRAINT credential_created_by_fk FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;
ALTER TABLE vinto_auth."credential" ADD CONSTRAINT credential_updated_by_fk FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;
ALTER TABLE vinto_auth."session" ADD CONSTRAINT session_user_fk FOREIGN KEY (user_id) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;
ALTER TABLE vinto_auth."auth_event" ADD CONSTRAINT auth_event_user_fk FOREIGN KEY (user_id) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

CREATE INDEX credential_created_by_idx ON vinto_auth."credential" (created_by);
CREATE INDEX credential_updated_by_idx ON vinto_auth."credential" (updated_by);
CREATE INDEX session_user_idx ON vinto_auth."session" (user_id);
CREATE INDEX session_active_expiry_idx ON vinto_auth."session" (expires_at) WHERE revoked_at IS NULL;
CREATE INDEX auth_event_user_time_idx ON vinto_auth."auth_event" (user_id, occurred_at);

-- credential reuses vinto_audit.touch_row: it only sets created_at/updated_at and
-- created_by/updated_by (all present here) and never reads password_hash.
CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_auth."credential" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

-- A credential cannot be reassigned to another user.
CREATE FUNCTION vinto_auth.guard_credential_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.user_id <> OLD.user_id THEN
   RAISE EXCEPTION 'Credential owner is immutable' USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER guard_identity BEFORE UPDATE ON vinto_auth."credential" FOR EACH ROW EXECUTE FUNCTION vinto_auth.guard_credential_identity();

-- Only last_seen_at, expires_at and revoked_at may change; a revoked session
-- cannot be revived.
CREATE FUNCTION vinto_auth.guard_session_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.id <> OLD.id OR NEW.user_id <> OLD.user_id OR NEW.token_hash <> OLD.token_hash OR NEW.created_at <> OLD.created_at THEN
   RAISE EXCEPTION 'Session identity is immutable' USING ERRCODE = '23514';
 END IF;
 IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
   RAISE EXCEPTION 'A revoked session cannot be changed' USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER guard_update BEFORE UPDATE ON vinto_auth."session" FOR EACH ROW EXECUTE FUNCTION vinto_auth.guard_session_update();

-- auth_event is append-only (same statement-level pattern as vinto_audit.audit_event).
CREATE TRIGGER immutable_event BEFORE UPDATE OR DELETE OR TRUNCATE ON vinto_auth."auth_event" FOR EACH STATEMENT EXECUTE FUNCTION vinto_audit.reject_mutation();

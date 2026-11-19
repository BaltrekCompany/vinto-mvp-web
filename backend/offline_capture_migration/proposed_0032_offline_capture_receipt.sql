-- OFF-04.4 / OFF-04.5B-03 PROPOSED migration (NOT numbered, NOT applied, NOT in backend/migrations/ so migrate.py never picks it up).
-- Promote to backend/migrations/0032_offline_capture_receipt.sql only with explicit authorization, after review
-- (see promote_0032.py and docs/OFF-04-5B-03-*.md). migrate.py wraps every migration in ONE transaction: this file therefore has no
-- BEGIN/COMMIT of its own, and runs as the schema owner (vinto_migrator in QA).
-- Isolated schema: it touches no operational schema and links to no operational table. It FAILS if the schema already exists.
CREATE SCHEMA vinto_offline;

CREATE TABLE vinto_offline.capture_receipt (
    capture_id        uuid PRIMARY KEY,
    author_user_id    uuid        NOT NULL,
    device_key        uuid        NOT NULL,
    form_code         text        NOT NULL CHECK (form_code ~ '^VINTO-[A-Z0-9-]{2,40}$'),
    form_version      integer     NOT NULL CHECK (form_version >= 1),
    machine_code      text        NOT NULL CHECK (machine_code ~ '^[A-Za-z0-9_.-]{1,48}$'),
    scope_snapshot_id uuid,
    context_version   text        NOT NULL CHECK (char_length(context_version) BETWEEN 1 AND 64),
    payload_sha256    text        NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    payload           jsonb       NOT NULL,
    outcome           text        NOT NULL CHECK (outcome IN ('received', 'accepted', 'accepted_warning', 'review', 'conflict')),
    reason            text,
    warnings          jsonb       NOT NULL DEFAULT '[]'::jsonb,
    server_seq        bigint      GENERATED ALWAYS AS IDENTITY,
    response_status   integer,
    response_body     jsonb,
    received_at       timestamptz NOT NULL DEFAULT now(),
    industrial_approval boolean   NOT NULL DEFAULT false CHECK (industrial_approval = false),
    -- 'received' exists only inside the inserting transaction: a committed row is always final and carries its reusable response
    CHECK ((outcome = 'received') = (response_status IS NULL AND response_body IS NULL))
);
CREATE INDEX capture_receipt_author_idx ON vinto_offline.capture_receipt (author_user_id, received_at);

CREATE TABLE vinto_offline.capture_event (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    capture_id     uuid        NOT NULL,
    kind           text        NOT NULL,
    payload_sha256 text,
    author_user_id uuid,
    detail         text,
    at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX capture_event_capture_idx ON vinto_offline.capture_event (capture_id, at);

-- Write-once identity, final-once result, no deletes, append-only events.
CREATE FUNCTION vinto_offline.guard_capture_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'capture_receipt rows are never deleted'; END IF;
    IF OLD.outcome <> 'received' THEN RAISE EXCEPTION 'capture_receipt result is final'; END IF;
    IF NEW.capture_id <> OLD.capture_id OR NEW.author_user_id <> OLD.author_user_id OR NEW.device_key <> OLD.device_key
       OR NEW.form_code <> OLD.form_code OR NEW.form_version <> OLD.form_version OR NEW.machine_code <> OLD.machine_code
       OR NEW.scope_snapshot_id IS DISTINCT FROM OLD.scope_snapshot_id OR NEW.context_version <> OLD.context_version
       OR NEW.payload_sha256 <> OLD.payload_sha256 OR NEW.payload <> OLD.payload OR NEW.server_seq <> OLD.server_seq THEN
        RAISE EXCEPTION 'capture_receipt identity is immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER capture_receipt_guard BEFORE UPDATE OR DELETE ON vinto_offline.capture_receipt
    FOR EACH ROW EXECUTE FUNCTION vinto_offline.guard_capture_receipt();

CREATE FUNCTION vinto_offline.guard_capture_event() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'capture_event is append-only'; END $$;
CREATE TRIGGER capture_event_guard BEFORE UPDATE OR DELETE ON vinto_offline.capture_event
    FOR EACH ROW EXECUTE FUNCTION vinto_offline.guard_capture_event();

-- Least privilege for the application role (backend/roles model: nothing by default, everything explicit). No DELETE, TRUNCATE, foreign-key or
-- trigger privilege, no DDL, no sequence grants needed (identity columns), and nothing outside this schema. The role must already exist: a missing role
-- aborts the whole migration (fail closed).
REVOKE ALL ON SCHEMA vinto_offline FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA vinto_offline FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA vinto_offline FROM PUBLIC;
GRANT USAGE ON SCHEMA vinto_offline TO vinto_app;
GRANT SELECT, INSERT, UPDATE ON vinto_offline.capture_receipt TO vinto_app;
GRANT SELECT, INSERT ON vinto_offline.capture_event TO vinto_app;

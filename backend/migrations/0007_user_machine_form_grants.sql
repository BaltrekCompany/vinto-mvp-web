-- Per-user, per-machine, per-form grants: persistence only (MF-13-01B.1).
--
-- Forward-only and additive: one new table, one trigger function and four triggers on that table, plus (only where the role exists) one
-- GRANT on the new table. No change to any existing table, function, row or grant of 0001-0006, and no data is inserted: every existing
-- user keeps exactly the access they have today.
--
-- vinto_master.user_machine_form_grant is an EXPLICIT grant list. No row means no grant: the absence of a row never widens access,
-- and nothing is derived from profiles or sectors. A grant only NARROWS where the user may work (as foreseen in 0006: "a separate,
-- narrowing table that is only consulted for sectors the user already holds"); it never creates an authorization on its own.
-- It is NOT consulted by any endpoint yet: wiring it into authorization is a later, separate change.
--
-- One row per (user, machine, form). The same form on two machines is two independent rows (VINTO-P1-01 on MP1 and on MP3):
-- revoking one never touches the other. The form is referenced by vinto_config.form.id (not by a version), so publishing a new
-- version of a form needs no new grant and the official form catalog is not modified.
--
-- History is kept. A grant is never deleted or edited: revoking sets revoked_at and revoked_by on the row, and a later grant of the
-- same triple is a NEW row. At most one ACTIVE (not revoked) row exists per triple (partial unique index); revoked rows accumulate.
-- The trigger below rejects DELETE, TRUNCATE, any change of the identity columns and any change to an already revoked row.
-- Every INSERT and UPDATE is also recorded in vinto_audit.audit_event with the actor, request_id and reason of the session.

CREATE TABLE vinto_master."user_machine_form_grant" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL,
 machine_id uuid NOT NULL,
 form_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid,
 revoked_at timestamptz,
 revoked_by uuid,
 CONSTRAINT "user_machine_form_grant_revocation_ck" CHECK ((revoked_at IS NULL) = (revoked_by IS NULL)),
 CONSTRAINT "user_machine_form_grant_revoked_after_created_ck" CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);

ALTER TABLE vinto_master."user_machine_form_grant" ADD CONSTRAINT "user_machine_form_grant_user_fk" FOREIGN KEY (user_id) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."user_machine_form_grant" ADD CONSTRAINT "user_machine_form_grant_machine_fk" FOREIGN KEY (machine_id) REFERENCES vinto_master."machine" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."user_machine_form_grant" ADD CONSTRAINT "user_machine_form_grant_form_fk" FOREIGN KEY (form_id) REFERENCES vinto_config."form" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."user_machine_form_grant" ADD CONSTRAINT "user_machine_form_grant_created_by_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."user_machine_form_grant" ADD CONSTRAINT "user_machine_form_grant_updated_by_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."user_machine_form_grant" ADD CONSTRAINT "user_machine_form_grant_revoked_by_fk" FOREIGN KEY (revoked_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

CREATE UNIQUE INDEX "user_machine_form_grant_active_uq" ON vinto_master."user_machine_form_grant" (user_id, machine_id, form_id) WHERE revoked_at IS NULL;

CREATE INDEX "user_machine_form_grant_user_fk_idx" ON vinto_master."user_machine_form_grant" (user_id);

CREATE INDEX "user_machine_form_grant_machine_fk_idx" ON vinto_master."user_machine_form_grant" (machine_id);

CREATE INDEX "user_machine_form_grant_form_fk_idx" ON vinto_master."user_machine_form_grant" (form_id);

CREATE FUNCTION vinto_audit.guard_user_machine_form_grant() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN
   RAISE EXCEPTION 'Immutable history: %.% rows are never deleted; revoke the grant instead', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = '23514';
 END IF;
 IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.machine_id IS DISTINCT FROM OLD.machine_id
    OR NEW.form_id IS DISTINCT FROM OLD.form_id THEN
   RAISE EXCEPTION 'Immutable grant identity: %.% (user, machine, form) never changes', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = '23514';
 END IF;
 IF OLD.revoked_at IS NOT NULL AND (NEW.revoked_at IS DISTINCT FROM OLD.revoked_at OR NEW.revoked_by IS DISTINCT FROM OLD.revoked_by) THEN
   RAISE EXCEPTION 'A revocation is final: %.%; grant again to create a new row', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER a_guard BEFORE UPDATE OR DELETE ON vinto_master."user_machine_form_grant" FOR EACH ROW EXECUTE FUNCTION vinto_audit.guard_user_machine_form_grant();

CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON vinto_master."user_machine_form_grant" FOR EACH STATEMENT EXECUTE FUNCTION vinto_audit.reject_mutation();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_master."user_machine_form_grant" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_master."user_machine_form_grant" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

-- Least-privilege provisioning (backend/migrations/README.md, "CLOUD-01B-2"): a table added from 0007 on declares its own explicit GRANT.
-- vinto_app gets SELECT, INSERT and UPDATE only, never DELETE: a grant is revoked by UPDATE and its history is kept. The role exists only in
-- clusters provisioned with backend/roles; elsewhere (legacy, local and *_test databases) the block does nothing. No GRANT is issued to any
-- other role, and nothing in the application reads or writes this table yet.
DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app') THEN
   GRANT SELECT, INSERT, UPDATE ON vinto_master."user_machine_form_grant" TO vinto_app;
 END IF;
END $$;

-- A revocation must carry the session actor (MF-13-01B.4). Forward-only; 0007 and 0008 are not modified.
--
-- 0008 required revoked_by to equal vinto.actor_id only when the session had an actor. With no actor, a direct UPDATE could still revoke a grant
-- naming ANY user as revoked_by (and, through this guard, as updated_by): reproduced on 0008 both as the table owner and as a role with exactly the
-- privileges of vinto_app (SELECT, INSERT, UPDATE). The audit event of such an UPDATE carries actor_id NULL, so it was detectable but not prevented,
-- and the header of 0008 ("raw SQL without an actor cannot attribute a row to someone else") only held for INSERT.
--
-- The check constraint of 0007, (revoked_at IS NULL) = (revoked_by IS NULL), makes an UNATTRIBUTED revocation impossible to store: a revocation always
-- names a user. So refusing the no-actor case removes no representable use. An operator revoking by hand states who is responsible for it in the same
-- transaction: SELECT set_config('vinto.actor_id', '<their own vinto_master."user".id>', true), plus vinto.request_id and vinto.reason.
--
-- What this does NOT do, and cannot do inside the database: vinto.actor_id is a session setting written by the client, so a session with UPDATE privilege
-- can still set it to someone else's id. The row and the audit event would then agree on that id; what stays truthful is vinto_audit.audit_event
-- (immutable) with database_actor = session_user, request_id and reason. Proving WHO asked needs authentication outside PostgreSQL (the future
-- administrative API takes the actor from the authenticated session, never from the request).
--
-- Only the body of the guard function changes (one added check). No table, column, constraint, index, trigger, privilege, row or audit event is
-- created, changed or removed: every stored grant keeps exactly the values it has, including any revocation already recorded without an actor, which is
-- left untouched (history is never rewritten; see docs/MF-13-01B4-atribucion-revocaciones.md for the query that lists them).

CREATE OR REPLACE FUNCTION vinto_audit.guard_user_machine_form_grant() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor uuid := nullif(current_setting('vinto.actor_id', true), '')::uuid;
BEGIN
 IF TG_OP = 'DELETE' THEN
   RAISE EXCEPTION 'Immutable history: %.% rows are never deleted; revoke the grant instead', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = '23514';
 END IF;
 IF TG_OP = 'INSERT' THEN
   IF NEW.revoked_at IS NOT NULL OR NEW.revoked_by IS NOT NULL THEN
     RAISE EXCEPTION 'A grant is created active: %.% cannot be inserted already revoked', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = '23514';
   END IF;
   IF (NEW.created_by IS NOT NULL AND NEW.created_by IS DISTINCT FROM actor) OR (NEW.updated_by IS NOT NULL AND NEW.updated_by IS DISTINCT FROM actor) THEN
     RAISE EXCEPTION 'created_by and updated_by are stamped from the session actor: %.% cannot be attributed to someone else', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = '23514';
   END IF;
   RETURN NEW;
 END IF;
 IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.machine_id IS DISTINCT FROM OLD.machine_id
    OR NEW.form_id IS DISTINCT FROM OLD.form_id THEN
   RAISE EXCEPTION 'Immutable grant identity: %.% (user, machine, form) never changes', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = '23514';
 END IF;
 IF OLD.revoked_at IS NOT NULL THEN
   RAISE EXCEPTION 'A revocation is final: %.% row cannot change at all; grant again to create a new row', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = '23514';
 END IF;
 IF NEW.revoked_at IS NULL OR NEW.revoked_by IS NULL THEN
   RAISE EXCEPTION 'An active grant only changes by being revoked: %.% (revoked_at and revoked_by are both required)', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = '23514';
 END IF;
 IF actor IS NULL THEN
   RAISE EXCEPTION 'A revocation must carry the session actor: %.% needs vinto.actor_id set to the user who revokes', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = '23514';
 END IF;
 IF NEW.revoked_by IS DISTINCT FROM actor THEN
   RAISE EXCEPTION 'revoked_by must be the session actor: %.% cannot be revoked in the name of someone else', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = '23514';
 END IF;
 NEW.revoked_at := clock_timestamp();
 NEW.updated_by := NEW.revoked_by;
 RETURN NEW;
END $$;

-- Integrity hardening of vinto_master.user_machine_form_grant (MF-13-01B.3). Forward-only; 0007 is not modified.
--
-- It only replaces the body of the guard trigger function created in 0007 and adds one BEFORE INSERT trigger that runs the same function.
-- No table, column, constraint, index, grant, row or audit event is created, changed or removed, so every grant already stored (active or
-- revoked) keeps exactly the values it has today. The existing grant, revoke, idempotency and audit behaviour is unchanged.
--
-- Gaps closed (each one reproduced against 0007 on an isolated PostgreSQL 17):
--   1. A revoked row could still be UPDATEd: updated_at / updated_by (audit stamps) changed after the revocation. A revoked row is now frozen.
--   2. A revocation took revoked_at from the caller (a future or past instant) and revoked_by from any user. revoked_at is now the server clock,
--      and when the session carries an actor (vinto.actor_id) revoked_by must be that actor.
--   3. An active row accepted UPDATEs that were not a revocation (for instance forging updated_by). The only valid change of an active row is
--      to revoke it; updated_by of that change is the revoker.
--   4. A row could be INSERTed already revoked (only a timing accident in the CHECK of 0007 stopped it), and created_by / updated_by could be
--      forged when the session had no actor. A grant is born active and its created_by / updated_by can only be the session actor (or NULL).
--
-- vinto.actor_id is the same session setting the touch_row() and record_change() triggers already read; the service always sets it. Raw SQL
-- without an actor keeps working, but cannot attribute a row to someone else: the stamps stay NULL.

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
 IF actor IS NOT NULL AND NEW.revoked_by IS DISTINCT FROM actor THEN
   RAISE EXCEPTION 'revoked_by must be the session actor: %.% cannot be revoked in the name of someone else', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = '23514';
 END IF;
 NEW.revoked_at := clock_timestamp();
 NEW.updated_by := NEW.revoked_by;
 RETURN NEW;
END $$;

CREATE TRIGGER a_guard_insert BEFORE INSERT ON vinto_master."user_machine_form_grant" FOR EACH ROW EXECUTE FUNCTION vinto_audit.guard_user_machine_form_grant();

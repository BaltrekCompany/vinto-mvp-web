-- Sector authorization: which sectors a user may work in (M1-C1).
--
-- Forward-only and additive: one new table, no change to any existing table, function or row of 0001-0005.
--
-- vinto_master.user_sector is an EXPLICIT grant list. No row means no access to any sector: the absence of a grant never
-- widens access. A grant says nothing about WHAT the user may do (that stays in the profile -> permission matrix of
-- app/auth/permissions.py); it only bounds WHERE. The backend intersects the grants with the operational sectors of
-- app/sectors.py, so granting REBOBINADO or CONVERSION has no effect until the product enables the sector in code.
--
-- Machine-level restrictions are deliberately NOT modelled yet. They can be added later as a separate, narrowing table
-- (user_machine -> machine) that is only consulted for sectors the user already holds, without touching this one.
--
-- Backfill (compatibility): every EXISTING active user holding an active profile of the five known ones (JEFATURA,
-- SUPERVISION, OPERACION, CALIDAD, DATA_BALTREK) receives a BOBINAS grant, so today's users keep exactly the access they have:
-- the read access of DATA_BALTREK included. This does not touch the permission matrix: DATA_BALTREK keeps only its read
-- permissions (work_order.read, assignment.read, catalog.read) plus its catalog/user administration, and never gains
-- work_order.manage, assignment.manage, production.capture, quality.capture or quality.release. New users always start with no
-- grant and need an explicit one. Nothing is granted for sectors other than BOBINAS, and only if that sector exists: in a
-- database without BOBINAS (an empty template) the backfill inserts nothing. Every inserted row is traceable in
-- vinto_audit.audit_event (request_id 'migration:0006_user_sector_grants', reason below). The whole file runs in the single
-- transaction of the migration runner (all or nothing).

CREATE TABLE vinto_master."user_sector" (
 user_id uuid NOT NULL, sector_id uuid NOT NULL, PRIMARY KEY (user_id, sector_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

ALTER TABLE vinto_master."user_sector" ADD CONSTRAINT "user_sector_user_fk" FOREIGN KEY (user_id) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."user_sector" ADD CONSTRAINT "user_sector_sector_fk" FOREIGN KEY (sector_id) REFERENCES vinto_master."sector" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."user_sector" ADD CONSTRAINT "user_sector_created_by_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."user_sector" ADD CONSTRAINT "user_sector_updated_by_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

CREATE INDEX "user_sector_sector_fk_idx" ON vinto_master."user_sector" (sector_id);

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_master."user_sector" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_master."user_sector" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

SELECT set_config('vinto.request_id', 'migration:0006_user_sector_grants', true);
SELECT set_config('vinto.reason', 'backfill: BOBINAS grant for existing users of the five profiles', true);

INSERT INTO vinto_master."user_sector" (user_id, sector_id)
SELECT DISTINCT up.user_id, s.id
FROM vinto_master."user_profile" up
JOIN vinto_master."profile" p ON p.id = up.profile_id AND p.active
JOIN vinto_master."user" u ON u.id = up.user_id AND u.active
JOIN vinto_master."sector" s ON s.code = 'BOBINAS'
WHERE p.code IN ('JEFATURA', 'SUPERVISION', 'OPERACION', 'CALIDAD', 'DATA_BALTREK');

-- OFF-04.5B-03 PROPOSED rollback (NOT applied; run by hand by the schema owner, never by migrate.py).
-- It PRESERVES the evidence: no DROP, no CASCADE, no row is touched. It (1) refuses to act if anything outside the schema depends on it,
-- (2) revokes every privilege of the application role, and (3) renames the schema to vinto_offline_archived. The migration history row is left
-- as it is (append-only history); the pilot refuses to start without the schema, and a later purge of the archived schema is a separate,
-- explicitly authorised step. Run inside ONE transaction (this file has its own, because it is not a migrate.py migration).
BEGIN;
DO $$
DECLARE dependents integer;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'vinto_offline') THEN
        RAISE EXCEPTION 'rollback refused: schema vinto_offline does not exist';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'vinto_offline_archived') THEN
        RAISE EXCEPTION 'rollback refused: vinto_offline_archived already exists (evidence of an earlier rollback must be handled first)';
    END IF;
    IF NOT pg_has_role(current_user, (SELECT nspowner FROM pg_namespace WHERE nspname = 'vinto_offline'), 'USAGE') THEN
        RAISE EXCEPTION 'rollback refused: the current role does not own schema vinto_offline';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'vinto_offline' AND c.relkind NOT IN ('r', 'i', 'S')) THEN
        RAISE EXCEPTION 'rollback refused: unexpected object kinds in vinto_offline';
    END IF;
    -- foreign keys from other schemas, views/rules over these tables, and triggers elsewhere that run this schema's functions
    SELECT (SELECT count(*) FROM pg_constraint k JOIN pg_class t ON t.oid = k.confrelid JOIN pg_namespace n ON n.oid = t.relnamespace
             WHERE n.nspname = 'vinto_offline' AND k.contype = 'f' AND k.conrelid NOT IN (SELECT oid FROM pg_class WHERE relnamespace = n.oid))
         + (SELECT count(*) FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid AND d.classid = 'pg_rewrite'::regclass
             JOIN pg_class v ON v.oid = r.ev_class JOIN pg_class t ON t.oid = d.refobjid AND d.refclassid = 'pg_class'::regclass
             JOIN pg_namespace tn ON tn.oid = t.relnamespace JOIN pg_namespace vn ON vn.oid = v.relnamespace
             WHERE tn.nspname = 'vinto_offline' AND vn.nspname <> 'vinto_offline')
         + (SELECT count(*) FROM pg_trigger g JOIN pg_proc p ON p.oid = g.tgfoid JOIN pg_namespace pn ON pn.oid = p.pronamespace
             JOIN pg_class gc ON gc.oid = g.tgrelid JOIN pg_namespace gn ON gn.oid = gc.relnamespace
             WHERE pn.nspname = 'vinto_offline' AND gn.nspname <> 'vinto_offline' AND NOT g.tgisinternal)
      INTO dependents;
    IF dependents > 0 THEN
        RAISE EXCEPTION 'rollback refused: % object(s) outside vinto_offline depend on it', dependents;
    END IF;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA vinto_offline FROM vinto_app;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA vinto_offline FROM vinto_app;
REVOKE ALL ON SCHEMA vinto_offline FROM vinto_app;
ALTER SCHEMA vinto_offline RENAME TO vinto_offline_archived;
COMMIT;

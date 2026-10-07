-- F3 (VINTO-P1-03) bobbin production: structured article grammage, per-machine/per-management bobbin numbering and
-- the evolution of vinto_txn.bobbin (which already exists since 0001; no second Bobbin entity is created).
--
-- Forward-only and non-destructive: no DELETE/TRUNCATE/UPDATE of existing rows. 0001-0003 are untouched.
--
-- 1. vinto_master.article_version_spec: structured specification attached to an article_version. article_version stays
--    the immutable authority (its immutable_article_version trigger is not touched); the spec is a sibling table keyed
--    by article_version_id so a version that already exists can receive its grammage without being modified.
--    grammage_g_m2 is NULL when the article has no grammage (e.g. "SEGUNDA" products): it never blocks F3.
-- 2. vinto_txn.management_start_year(date): the management (gestión) runs 01/04 -> 31/03 and is identified by the year
--    in which it starts. Single source of truth for both the service and the database guards.
-- 3. vinto_txn.bobbin_sequence: per (machine, management) counter. Allocation is a single
--    INSERT .. ON CONFLICT DO UPDATE .. RETURNING inside the F3 transaction: the row lock serialises concurrent
--    allocations and a rollback also rolls the increment back (no consumed numbers on failure).
-- 4. vinto_txn.bobbin gains the F3 columns. Legacy rows (all new columns NULL, sequence_number NULL) are preserved;
--    every new constraint is written so it only binds rows that carry a sequence_number.
-- 5. The global UNIQUE (code) of 0001 cannot hold ("1" exists on MP1 and MP3 and in every management): it is dropped
--    and replaced by UNIQUE (machine_id, management_start_year, sequence_number) for new rows, plus the old global
--    uniqueness restricted to legacy rows so history keeps its original guarantee.

-- ---------------------------------------------------------------------------------------------------------------
-- 1. article specification (grammage)
-- ---------------------------------------------------------------------------------------------------------------
CREATE TABLE vinto_master."article_version_spec" (
 article_version_id uuid PRIMARY KEY,
 grammage_g_m2 numeric CONSTRAINT article_version_spec_grammage_positive CHECK (grammage_g_m2 > 0),
 source_batch_id uuid,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

ALTER TABLE vinto_master."article_version_spec" ADD CONSTRAINT "article_version_spec_av_fk" FOREIGN KEY (article_version_id) REFERENCES vinto_master."article_version" (id) ON DELETE RESTRICT;
ALTER TABLE vinto_master."article_version_spec" ADD CONSTRAINT "article_version_spec_batch_fk" FOREIGN KEY (source_batch_id) REFERENCES vinto_audit."import_batch" (id) ON DELETE RESTRICT;
ALTER TABLE vinto_master."article_version_spec" ADD CONSTRAINT "article_version_spec_created_by_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;
ALTER TABLE vinto_master."article_version_spec" ADD CONSTRAINT "article_version_spec_updated_by_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;
CREATE INDEX "article_version_spec_batch_fk_idx" ON vinto_master."article_version_spec" (source_batch_id);
CREATE INDEX "article_version_spec_created_by_fk_idx" ON vinto_master."article_version_spec" (created_by);
CREATE INDEX "article_version_spec_updated_by_fk_idx" ON vinto_master."article_version_spec" (updated_by);

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_master."article_version_spec" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();
CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_master."article_version_spec" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();
-- Same immutability as article_version: a published specification is history, a change is a new article version.
CREATE TRIGGER immutable_article_version_spec BEFORE UPDATE OR DELETE ON vinto_master."article_version_spec" FOR EACH ROW EXECUTE FUNCTION vinto_audit.reject_mutation();

-- ---------------------------------------------------------------------------------------------------------------
-- 2. management (gestión) rule
-- ---------------------------------------------------------------------------------------------------------------
CREATE FUNCTION vinto_txn.management_start_year(operating_date date) RETURNS integer LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT EXTRACT(YEAR FROM operating_date)::integer - CASE WHEN EXTRACT(MONTH FROM operating_date) < 4 THEN 1 ELSE 0 END
$$;

-- ---------------------------------------------------------------------------------------------------------------
-- 3. per-machine / per-management counter
-- ---------------------------------------------------------------------------------------------------------------
CREATE TABLE vinto_txn."bobbin_sequence" (
 machine_id uuid NOT NULL,
 management_start_year integer NOT NULL CHECK (management_start_year > 0),
 last_value integer NOT NULL CHECK (last_value > 0),
 PRIMARY KEY (machine_id, management_start_year),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

ALTER TABLE vinto_txn."bobbin_sequence" ADD CONSTRAINT "bobbin_sequence_machine_fk" FOREIGN KEY (machine_id) REFERENCES vinto_master."machine" (id) ON DELETE RESTRICT;
ALTER TABLE vinto_txn."bobbin_sequence" ADD CONSTRAINT "bobbin_sequence_created_by_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;
ALTER TABLE vinto_txn."bobbin_sequence" ADD CONSTRAINT "bobbin_sequence_updated_by_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;
CREATE INDEX "bobbin_sequence_created_by_fk_idx" ON vinto_txn."bobbin_sequence" (created_by);
CREATE INDEX "bobbin_sequence_updated_by_fk_idx" ON vinto_txn."bobbin_sequence" (updated_by);

-- A counter only moves forward by exactly one and is never deleted: nobody can "reset" or skip a management's numbering.
CREATE FUNCTION vinto_txn.guard_bobbin_sequence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN
   RAISE EXCEPTION 'Bobbin sequence cannot be deleted' USING ERRCODE = '23514';
 END IF;
 IF NEW.machine_id <> OLD.machine_id OR NEW.management_start_year <> OLD.management_start_year OR NEW.last_value <> OLD.last_value + 1 THEN
   RAISE EXCEPTION 'Bobbin sequence can only advance by one' USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER guard_sequence BEFORE UPDATE OR DELETE ON vinto_txn."bobbin_sequence" FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_bobbin_sequence();
CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_txn."bobbin_sequence" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();
CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_txn."bobbin_sequence" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

-- ---------------------------------------------------------------------------------------------------------------
-- 4. bobbin evolution
-- ---------------------------------------------------------------------------------------------------------------
-- OT/PV/line/shift/operating date/operator are NOT duplicated: they derive from source_capture -> assignment.
-- machine_id is kept because it is part of the numbering scope (and the capture's machine must equal it: see guard).
ALTER TABLE vinto_txn."bobbin"
 ADD COLUMN machine_id uuid,
 ADD COLUMN management_start_year integer,
 ADD COLUMN sequence_number integer,
 ADD COLUMN start_time time,
 ADD COLUMN end_time time,
 ADD COLUMN diameter_mm numeric,
 ADD COLUMN grammage_g_m2 numeric,
 ADD COLUMN number_of_cuts text,
 ADD COLUMN notes text;

ALTER TABLE vinto_txn."bobbin" ADD CONSTRAINT "bobbin_machine_fk" FOREIGN KEY (machine_id) REFERENCES vinto_master."machine" (id) ON DELETE RESTRICT;
CREATE INDEX "bobbin_machine_fk_idx" ON vinto_txn."bobbin" (machine_id);

-- start_time / end_time are two manual wall-clock times: no ordering rule (a bobbin can cross midnight).
-- weight_kg >= 0 already comes from 0001. Every constraint is vacuous for legacy rows (sequence_number IS NULL).
ALTER TABLE vinto_txn."bobbin"
 ADD CONSTRAINT bobbin_grammage_positive CHECK (grammage_g_m2 IS NULL OR grammage_g_m2 > 0),
 ADD CONSTRAINT bobbin_sequence_scope_together CHECK ((sequence_number IS NULL) = (management_start_year IS NULL)),
 ADD CONSTRAINT bobbin_f3_row_complete CHECK (sequence_number IS NULL OR (
   sequence_number > 0 AND management_start_year > 0
   AND machine_id IS NOT NULL AND source_capture_id IS NOT NULL AND article_version_id IS NOT NULL
   AND weight_kg IS NOT NULL AND start_time IS NOT NULL AND end_time IS NOT NULL
   AND diameter_mm IS NOT NULL
   AND number_of_cuts IS NOT NULL AND btrim(number_of_cuts) <> ''
   AND code = sequence_number::text));

-- 5. code is no longer globally unique.
ALTER TABLE vinto_txn."bobbin" DROP CONSTRAINT bobbin_code_key;
CREATE UNIQUE INDEX bobbin_legacy_code_uidx ON vinto_txn."bobbin" (code) WHERE sequence_number IS NULL;
CREATE INDEX bobbin_code_idx ON vinto_txn."bobbin" (code);
CREATE UNIQUE INDEX bobbin_machine_management_sequence_uidx ON vinto_txn."bobbin" (machine_id, management_start_year, sequence_number) WHERE sequence_number IS NOT NULL;
CREATE UNIQUE INDEX bobbin_source_capture_uidx ON vinto_txn."bobbin" (source_capture_id) WHERE sequence_number IS NOT NULL;

-- Context coherence for numbered bobbins: the machine, management and article must agree with the source capture.
-- The identity of a numbered bobbin is immutable.
CREATE FUNCTION vinto_txn.validate_bobbin() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE cap record;
BEGIN
 IF TG_OP = 'UPDATE' AND OLD.sequence_number IS NOT NULL AND (
    NEW.code IS DISTINCT FROM OLD.code OR NEW.machine_id IS DISTINCT FROM OLD.machine_id
    OR NEW.management_start_year IS DISTINCT FROM OLD.management_start_year OR NEW.sequence_number IS DISTINCT FROM OLD.sequence_number
    OR NEW.source_capture_id IS DISTINCT FROM OLD.source_capture_id OR NEW.article_version_id IS DISTINCT FROM OLD.article_version_id) THEN
   RAISE EXCEPTION 'Numbered bobbin identity is immutable' USING ERRCODE = '23514';
 END IF;
 IF NEW.sequence_number IS NOT NULL AND (TG_OP = 'INSERT' OR OLD.sequence_number IS NULL) THEN
   SELECT c.machine_id, c.operating_date, l.article_version_id INTO cap
   FROM vinto_txn.capture c
   LEFT JOIN vinto_txn.assignment a ON a.id = c.assignment_id
   LEFT JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
   WHERE c.id = NEW.source_capture_id;
   IF NOT FOUND THEN
     RAISE EXCEPTION 'Bobbin requires its source capture' USING ERRCODE = '23514';
   END IF;
   IF cap.machine_id <> NEW.machine_id THEN
     RAISE EXCEPTION 'Bobbin machine must match its capture machine' USING ERRCODE = '23514';
   END IF;
   IF vinto_txn.management_start_year(cap.operating_date) <> NEW.management_start_year THEN
     RAISE EXCEPTION 'Bobbin management must derive from the capture operating date' USING ERRCODE = '23514';
   END IF;
   IF cap.article_version_id IS DISTINCT FROM NEW.article_version_id THEN
     RAISE EXCEPTION 'Bobbin article must match the assignment article' USING ERRCODE = '23514';
   END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER bobbin_guard BEFORE INSERT OR UPDATE ON vinto_txn."bobbin" FOR EACH ROW EXECUTE FUNCTION vinto_txn.validate_bobbin();

-- Every numbered bobbin must reach COMMIT with its quality_release row (Calidad's inbox is built on it).
CREATE FUNCTION vinto_txn.require_quality_release() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.sequence_number IS NOT NULL AND NOT EXISTS (SELECT 1 FROM vinto_txn.quality_release WHERE bobbin_id = NEW.id) THEN
   RAISE EXCEPTION 'Numbered bobbin requires a quality_release row' USING ERRCODE = '23514';
 END IF;
 RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER require_quality_release AFTER INSERT ON vinto_txn."bobbin" DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vinto_txn.require_quality_release();

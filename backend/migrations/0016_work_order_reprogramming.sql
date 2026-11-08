-- E2-B: aditive metadata for controlled revisions of already published work orders.
-- Existing baseline and operational snapshots remain untouched. No backfill.
-- A revised operational version is a NEW immutable complete snapshot, not an
-- UPDATE of a published line, capture or assignment.
ALTER TABLE vinto_txn.work_order_version
  ADD COLUMN based_on_version_id uuid REFERENCES vinto_txn.work_order_version(id) ON DELETE RESTRICT,
  ADD COLUMN reprogram_line_code text,
  ADD COLUMN reprogram_reason text;

ALTER TABLE vinto_txn.work_order_version
  ADD CONSTRAINT work_order_reprogram_metadata_check CHECK (
    (based_on_version_id IS NULL AND reprogram_line_code IS NULL AND reprogram_reason IS NULL)
    OR
    (kind = 'operational' AND version_number >= 2
     AND based_on_version_id IS NOT NULL AND based_on_version_id <> id
     AND reprogram_line_code ~ '^L[1-9][0-9]*$'
     AND reprogram_reason IS NOT NULL
     AND length(btrim(reprogram_reason)) BETWEEN 10 AND 300)
  );

CREATE INDEX work_order_reprogram_history_idx
  ON vinto_txn.work_order_version(work_order_id, version_number DESC)
  WHERE reprogram_reason IS NOT NULL;

-- The existing 0001 triggers still provide immutable published versions/lines
-- and full audit (actor, timestamp, before/after, reason). The current vinto_app
-- privileges already cover INSERT/SELECT on this table. No changes to grants,
-- assignment pointers, E1 execution, captures, bobbins or their histories.

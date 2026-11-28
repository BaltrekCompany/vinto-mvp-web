-- RBE-04: persistencia, clasificación positiva de OT, reservas transaccionales y trazabilidad.
-- Forward-only. No backfill de capturas, madres, crías ni clasificaciones.
-- La generación consume bytes PDF producidos por RBE-05; esta migración instala el contrato
-- y las invariantes de almacenamiento, pero no crea un renderer ni habilita despliegues.

CREATE TABLE vinto_txn.rewinding_export_work_order_classification (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  work_order_id uuid NOT NULL,
  sequence_no integer NOT NULL CHECK (sequence_no > 0),
  classification text NOT NULL CHECK (classification IN ('production_confirmed','qa')),
  recorded_by uuid NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 10 AND 300),
  supersedes_id uuid,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  created_by uuid,
  updated_by uuid,
  CONSTRAINT rewinding_export_classification_order_uq UNIQUE (work_order_id, sequence_no),
  CONSTRAINT rewinding_export_classification_identity_uq UNIQUE (id, work_order_id),
  CONSTRAINT rewinding_export_classification_supersedes_ck
    CHECK ((sequence_no = 1 AND supersedes_id IS NULL) OR (sequence_no > 1 AND supersedes_id IS NOT NULL)),
  CONSTRAINT rewinding_export_classification_work_order_fk
    FOREIGN KEY (work_order_id) REFERENCES vinto_txn.work_order(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_classification_actor_fk
    FOREIGN KEY (recorded_by) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_classification_supersedes_fk
    FOREIGN KEY (supersedes_id, work_order_id)
    REFERENCES vinto_txn.rewinding_export_work_order_classification(id, work_order_id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX rewinding_export_classification_supersedes_uidx
  ON vinto_txn.rewinding_export_work_order_classification(supersedes_id)
  WHERE supersedes_id IS NOT NULL;
CREATE INDEX rewinding_export_classification_latest_idx
  ON vinto_txn.rewinding_export_work_order_classification(work_order_id, sequence_no DESC);

CREATE TABLE vinto_txn.rewinding_export_report (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','generated','observed','annulled','discarded')),
  pv_reference text NOT NULL CHECK (length(btrim(pv_reference)) BETWEEN 1 AND 100),
  article_id uuid NOT NULL,
  article_code_snapshot text NOT NULL CHECK (length(btrim(article_code_snapshot)) BETWEEN 1 AND 64),
  machine_id uuid,
  sector_id uuid,
  destination_snapshot text,
  truck_number text NOT NULL DEFAULT '' CHECK (length(truck_number) <= 80),
  order_number text NOT NULL DEFAULT '' CHECK (length(order_number) <= 80),
  observations text NOT NULL DEFAULT '' CHECK (length(observations) <= 2000),
  report_snapshot jsonb,
  snapshot_version integer,
  generation_idempotency_key uuid,
  generation_request_sha256 text,
  generated_by uuid,
  generated_at timestamptz,
  annulled_by uuid,
  annulled_at timestamptz,
  annulled_reason text,
  discarded_by uuid,
  discarded_at timestamptz,
  discarded_reason text,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  created_by uuid NOT NULL,
  updated_by uuid,
  CONSTRAINT rewinding_export_report_context_ck
    CHECK ((machine_id IS NULL AND sector_id IS NOT NULL AND destination_snapshot IS NULL)
        OR (machine_id IS NOT NULL AND sector_id IS NOT NULL AND destination_snapshot IS NOT NULL
            AND length(btrim(destination_snapshot)) > 0)),
  CONSTRAINT rewinding_export_report_idempotency_ck
    CHECK ((generation_idempotency_key IS NULL AND generation_request_sha256 IS NULL)
        OR (generation_idempotency_key IS NOT NULL AND generation_request_sha256 ~ '^[a-f0-9]{64}$')),
  CONSTRAINT rewinding_export_report_snapshot_ck
    CHECK ((report_snapshot IS NULL AND snapshot_version IS NULL)
        OR (report_snapshot IS NOT NULL AND jsonb_typeof(report_snapshot) = 'object'
            AND snapshot_version IS NOT NULL AND snapshot_version > 0)),
  CONSTRAINT rewinding_export_report_state_ck CHECK (
    (status = 'draft' AND generated_by IS NULL AND generated_at IS NULL
      AND generation_idempotency_key IS NULL AND generation_request_sha256 IS NULL
      AND report_snapshot IS NULL AND snapshot_version IS NULL
      AND annulled_by IS NULL AND annulled_at IS NULL AND annulled_reason IS NULL
      AND discarded_by IS NULL AND discarded_at IS NULL AND discarded_reason IS NULL)
    OR
    (status = 'discarded' AND generated_by IS NULL AND generated_at IS NULL
      AND generation_idempotency_key IS NULL AND generation_request_sha256 IS NULL
      AND report_snapshot IS NULL AND snapshot_version IS NULL
      AND annulled_by IS NULL AND annulled_at IS NULL AND annulled_reason IS NULL
      AND discarded_by IS NOT NULL AND discarded_at IS NOT NULL
      AND length(btrim(coalesce(discarded_reason,''))) BETWEEN 1 AND 300)
    OR
    (status IN ('generated','observed') AND generated_by IS NOT NULL AND generated_at IS NOT NULL
      AND generation_idempotency_key IS NOT NULL AND generation_request_sha256 ~ '^[a-f0-9]{64}$'
      AND report_snapshot IS NOT NULL AND snapshot_version > 0
      AND machine_id IS NOT NULL AND sector_id IS NOT NULL AND destination_snapshot IS NOT NULL
      AND annulled_by IS NULL AND annulled_at IS NULL AND annulled_reason IS NULL
      AND discarded_by IS NULL AND discarded_at IS NULL AND discarded_reason IS NULL)
    OR
    (status = 'annulled' AND generated_by IS NOT NULL AND generated_at IS NOT NULL
      AND generation_idempotency_key IS NOT NULL AND generation_request_sha256 ~ '^[a-f0-9]{64}$'
      AND report_snapshot IS NOT NULL AND snapshot_version > 0
      AND machine_id IS NOT NULL AND sector_id IS NOT NULL AND destination_snapshot IS NOT NULL
      AND annulled_by IS NOT NULL AND annulled_at IS NOT NULL
      AND length(btrim(coalesce(annulled_reason,''))) BETWEEN 10 AND 300
      AND discarded_by IS NULL AND discarded_at IS NULL AND discarded_reason IS NULL)
  ),
  CONSTRAINT rewinding_export_report_article_fk
    FOREIGN KEY (article_id) REFERENCES vinto_master.article(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_report_machine_fk
    FOREIGN KEY (machine_id) REFERENCES vinto_master.machine(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_report_sector_fk
    FOREIGN KEY (sector_id) REFERENCES vinto_master.sector(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_report_creator_fk
    FOREIGN KEY (created_by) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_report_updater_fk
    FOREIGN KEY (updated_by) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_report_generator_fk
    FOREIGN KEY (generated_by) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_report_annuller_fk
    FOREIGN KEY (annulled_by) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_report_discarder_fk
    FOREIGN KEY (discarded_by) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX rewinding_export_report_generation_actor_key_uidx
  ON vinto_txn.rewinding_export_report(generated_by, generation_idempotency_key)
  WHERE generation_idempotency_key IS NOT NULL;
CREATE INDEX rewinding_export_report_owner_idx
  ON vinto_txn.rewinding_export_report(created_by, created_at DESC, id);
CREATE INDEX rewinding_export_report_sector_idx
  ON vinto_txn.rewinding_export_report(sector_id, status, created_at DESC);

CREATE TABLE vinto_txn.rewinding_export_package (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id uuid NOT NULL,
  package_number integer NOT NULL CHECK (package_number > 0),
  mother_capture_id uuid NOT NULL,
  mother_bobbin_id uuid,
  mother_label_snapshot text NOT NULL CHECK (length(btrim(mother_label_snapshot)) BETWEEN 1 AND 255),
  source_capture_revision integer NOT NULL CHECK (source_capture_revision > 0),
  source_form_version_id uuid NOT NULL,
  work_order_id uuid NOT NULL,
  work_order_line_id uuid NOT NULL,
  source_work_order_classification_id uuid NOT NULL,
  article_version_id uuid NOT NULL,
  source_fields_snapshot jsonb NOT NULL CHECK (jsonb_typeof(source_fields_snapshot) = 'object'),
  source_operator_user_id uuid,
  operator_display_name_snapshot text,
  machine_code_snapshot text NOT NULL,
  machine_name_snapshot text NOT NULL,
  work_order_number_snapshot text NOT NULL,
  article_code_snapshot text NOT NULL,
  article_description_snapshot text NOT NULL,
  removed_at timestamptz,
  removed_by uuid,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  created_by uuid NOT NULL,
  updated_by uuid,
  CONSTRAINT rewinding_export_package_identity_uq UNIQUE (id, report_id),
  CONSTRAINT rewinding_export_package_removed_ck
    CHECK ((removed_at IS NULL AND removed_by IS NULL) OR (removed_at IS NOT NULL AND removed_by IS NOT NULL)),
  CONSTRAINT rewinding_export_package_report_fk
    FOREIGN KEY (report_id) REFERENCES vinto_txn.rewinding_export_report(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_package_capture_fk
    FOREIGN KEY (mother_capture_id) REFERENCES vinto_txn.capture(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_package_mother_fk
    FOREIGN KEY (mother_bobbin_id) REFERENCES vinto_txn.bobbin(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_package_form_version_fk
    FOREIGN KEY (source_form_version_id) REFERENCES vinto_config.form_version(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_package_work_order_fk
    FOREIGN KEY (work_order_id) REFERENCES vinto_txn.work_order(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_package_work_order_line_fk
    FOREIGN KEY (work_order_line_id, article_version_id)
    REFERENCES vinto_txn.work_order_line(id, article_version_id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_package_classification_fk
    FOREIGN KEY (source_work_order_classification_id, work_order_id)
    REFERENCES vinto_txn.rewinding_export_work_order_classification(id, work_order_id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_package_article_version_fk
    FOREIGN KEY (article_version_id) REFERENCES vinto_master.article_version(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_package_operator_fk
    FOREIGN KEY (source_operator_user_id) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_package_remover_fk
    FOREIGN KEY (removed_by) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_package_creator_fk
    FOREIGN KEY (created_by) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_package_updater_fk
    FOREIGN KEY (updated_by) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX rewinding_export_package_number_active_uidx
  ON vinto_txn.rewinding_export_package(report_id, package_number) WHERE removed_at IS NULL;
CREATE INDEX rewinding_export_package_report_idx
  ON vinto_txn.rewinding_export_package(report_id, package_number, id);

CREATE TABLE vinto_txn.rewinding_export_package_child (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id uuid NOT NULL,
  package_id uuid NOT NULL,
  child_bobbin_id uuid NOT NULL,
  package_slot text NOT NULL CHECK (package_slot IN ('A','B','C','D','E')),
  source_position smallint NOT NULL CHECK (source_position BETWEEN 1 AND 22 AND source_position <> 12),
  weight_kg_snapshot numeric NOT NULL CHECK (weight_kg_snapshot > 0),
  removed_at timestamptz,
  removed_by uuid,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  created_by uuid NOT NULL,
  updated_by uuid,
  CONSTRAINT rewinding_export_package_child_identity_uq UNIQUE (id, report_id, package_id),
  CONSTRAINT rewinding_export_package_child_reservation_uq UNIQUE (id, child_bobbin_id),
  CONSTRAINT rewinding_export_package_child_removed_ck
    CHECK ((removed_at IS NULL AND removed_by IS NULL) OR (removed_at IS NOT NULL AND removed_by IS NOT NULL)),
  CONSTRAINT rewinding_export_package_child_package_fk
    FOREIGN KEY (package_id, report_id)
    REFERENCES vinto_txn.rewinding_export_package(id, report_id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_package_child_bobbin_fk
    FOREIGN KEY (child_bobbin_id) REFERENCES vinto_txn.bobbin(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_package_child_remover_fk
    FOREIGN KEY (removed_by) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_package_child_creator_fk
    FOREIGN KEY (created_by) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_package_child_updater_fk
    FOREIGN KEY (updated_by) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX rewinding_export_package_child_slot_active_uidx
  ON vinto_txn.rewinding_export_package_child(package_id, package_slot) WHERE removed_at IS NULL;
CREATE UNIQUE INDEX rewinding_export_package_child_report_bobbin_active_uidx
  ON vinto_txn.rewinding_export_package_child(report_id, child_bobbin_id) WHERE removed_at IS NULL;
CREATE INDEX rewinding_export_package_child_bobbin_idx
  ON vinto_txn.rewinding_export_package_child(child_bobbin_id, report_id);

CREATE TABLE vinto_txn.rewinding_export_pdf (
  report_id uuid PRIMARY KEY,
  file_name text NOT NULL CHECK (length(btrim(file_name)) BETWEEN 1 AND 255),
  mime_type text NOT NULL CHECK (mime_type = 'application/pdf'),
  pdf_bytes bytea NOT NULL,
  sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
  size_bytes integer NOT NULL CHECK (size_bytes BETWEEN 1 AND 26214400),
  page_count integer NOT NULL CHECK (page_count > 0),
  generated_at timestamptz NOT NULL,
  CONSTRAINT rewinding_export_pdf_size_ck CHECK (size_bytes = octet_length(pdf_bytes)),
  CONSTRAINT rewinding_export_pdf_report_fk
    FOREIGN KEY (report_id) REFERENCES vinto_txn.rewinding_export_report(id) ON DELETE RESTRICT,
);

CREATE TABLE vinto_txn.rewinding_export_reservation (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  package_child_id uuid NOT NULL,
  child_bobbin_id uuid NOT NULL,
  reserved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  reserved_by uuid NOT NULL,
  released_at timestamptz,
  released_by uuid,
  release_reason text,
  CONSTRAINT rewinding_export_reservation_package_child_uq UNIQUE (package_child_id),
  CONSTRAINT rewinding_export_reservation_package_child_fk
    FOREIGN KEY (package_child_id, child_bobbin_id)
    REFERENCES vinto_txn.rewinding_export_package_child(id, child_bobbin_id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_reservation_bobbin_fk
    FOREIGN KEY (child_bobbin_id) REFERENCES vinto_txn.bobbin(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_reservation_actor_fk
    FOREIGN KEY (reserved_by) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_reservation_releaser_fk
    FOREIGN KEY (released_by) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_reservation_release_ck
    CHECK ((released_at IS NULL AND released_by IS NULL AND release_reason IS NULL)
        OR (released_at IS NOT NULL AND released_by IS NOT NULL
            AND length(btrim(coalesce(release_reason,''))) BETWEEN 1 AND 300))
);
CREATE UNIQUE INDEX rewinding_export_reservation_active_bobbin_uidx
  ON vinto_txn.rewinding_export_reservation(child_bobbin_id) WHERE released_at IS NULL;
CREATE INDEX rewinding_export_reservation_active_child_idx
  ON vinto_txn.rewinding_export_reservation(package_child_id) WHERE released_at IS NULL;

CREATE TABLE vinto_txn.rewinding_export_report_event (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id uuid NOT NULL,
  event_type text NOT NULL CHECK (event_type IN
    ('draft_created','package_added','package_updated','package_removed','child_added','child_removed','draft_discarded',
     'report_generated','report_annulled','reservation_created','reservation_released')),
  actor_id uuid NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  reason text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
  CONSTRAINT rewinding_export_report_event_report_fk
    FOREIGN KEY (report_id) REFERENCES vinto_txn.rewinding_export_report(id) ON DELETE RESTRICT,
  CONSTRAINT rewinding_export_report_event_actor_fk
    FOREIGN KEY (actor_id) REFERENCES vinto_master."user"(id) ON DELETE RESTRICT
);
CREATE INDEX rewinding_export_report_event_history_idx
  ON vinto_txn.rewinding_export_report_event(report_id, occurred_at, id);

-- Positive classification is append-only. The work-order row is the serialization point shared with
-- generation (FOR SHARE) and QA retirement (FOR UPDATE).
CREATE FUNCTION vinto_txn.guard_rewinding_export_classification()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  actor uuid := nullif(current_setting('vinto.actor_id',true),'')::uuid;
  active_user boolean;
  has_jefatura boolean;
  has_sector boolean;
  wo_status text;
  archived timestamptz;
  qa_retired boolean;
  sector_code text;
  sector_active boolean;
  machine_active boolean;
  latest_id uuid;
  latest_sequence integer;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'Work-order classification is append-only' USING ERRCODE='23514';
  END IF;
  IF actor IS NULL OR NEW.recorded_by IS DISTINCT FROM actor
     OR length(btrim(coalesce(NEW.reason,''))) NOT BETWEEN 10 AND 300 THEN
    RAISE EXCEPTION 'Classification requires the authenticated Jefatura actor and a valid reason' USING ERRCODE='23514';
  END IF;
  SELECT active INTO active_user FROM vinto_master."user" WHERE id=actor FOR SHARE;
  IF active_user IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'Classification actor is inactive or missing' USING ERRCODE='23514';
  END IF;
  SELECT EXISTS (
    SELECT 1 FROM vinto_master.user_profile up
    JOIN vinto_master.profile p ON p.id=up.profile_id
    WHERE up.user_id=actor AND p.code='JEFATURA' AND p.active
  ) INTO has_jefatura;
  SELECT EXISTS (
    SELECT 1 FROM vinto_master.user_sector us
    JOIN vinto_master.sector s ON s.id=us.sector_id
    WHERE us.user_id=actor AND s.code='REBOBINADO' AND s.active
  ) INTO has_sector;
  IF NOT has_jefatura OR NOT has_sector THEN
    RAISE EXCEPTION 'Classification actor lacks Jefatura or REBOBINADO scope' USING ERRCODE='23514';
  END IF;

  SELECT wo.status, wo.archived_at, wo.qa_retired, s.code, s.active, m.active
    INTO wo_status, archived, qa_retired, sector_code, sector_active, machine_active
    FROM vinto_txn.work_order wo
    JOIN vinto_master.machine m ON m.id=wo.machine_id
    JOIN vinto_master.sector s ON s.id=m.sector_id
    WHERE wo.id=NEW.work_order_id
    FOR UPDATE OF wo;
  IF NOT FOUND OR wo_status NOT IN ('published','in_progress','closed')
     OR archived IS NOT NULL OR qa_retired OR sector_code <> 'REBOBINADO'
     OR NOT sector_active OR NOT machine_active THEN
    RAISE EXCEPTION 'Work order is not classifiable in REBOBINADO' USING ERRCODE='23514';
  END IF;

  SELECT id, sequence_no INTO latest_id, latest_sequence
    FROM vinto_txn.rewinding_export_work_order_classification
    WHERE work_order_id=NEW.work_order_id ORDER BY sequence_no DESC LIMIT 1;
  IF NEW.sequence_no <> coalesce(latest_sequence,0)+1
     OR NEW.supersedes_id IS DISTINCT FROM latest_id THEN
    RAISE EXCEPTION 'Classification sequence or supersedes link is not the current successor' USING ERRCODE='23514';
  END IF;
  IF latest_sequence IS NOT NULL AND EXISTS (
    SELECT 1 FROM vinto_txn.rewinding_export_work_order_classification
    WHERE work_order_id=NEW.work_order_id AND classification=NEW.classification
    ORDER BY sequence_no DESC LIMIT 1
  ) AND (SELECT classification FROM vinto_txn.rewinding_export_work_order_classification
         WHERE id=latest_id) = NEW.classification THEN
    RAISE EXCEPTION 'Duplicate effective classification' USING ERRCODE='23514';
  END IF;
  IF NEW.classification='qa' AND EXISTS (
    SELECT 1 FROM vinto_txn.rewinding_export_package p
    JOIN vinto_txn.rewinding_export_report r ON r.id=p.report_id
    WHERE p.work_order_id=NEW.work_order_id AND p.removed_at IS NULL
      AND r.status IN ('generated','observed')
  ) THEN
    RAISE EXCEPTION 'Generated or observed RBE reports must be annulled before QA classification' USING ERRCODE='23514';
  END IF;
  NEW.recorded_at := clock_timestamp();
  RETURN NEW;
END $$;

CREATE FUNCTION vinto_txn.guard_rewinding_export_report()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor uuid := nullif(current_setting('vinto.actor_id',true),'')::uuid;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'RBE report history cannot be deleted' USING ERRCODE='23514';
  ELSIF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'draft' OR actor IS NULL OR NEW.created_by IS DISTINCT FROM actor
       OR NEW.generated_by IS NOT NULL OR NEW.annulled_by IS NOT NULL OR NEW.discarded_by IS NOT NULL THEN
      RAISE EXCEPTION 'RBE report must be created as a draft by the authenticated actor' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;

  IF OLD.status='draft' THEN
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.pv_reference IS DISTINCT FROM OLD.pv_reference
       OR NEW.article_id IS DISTINCT FROM OLD.article_id THEN
      RAISE EXCEPTION 'RBE draft identity and source context are immutable' USING ERRCODE='23514';
    END IF;
    IF OLD.machine_id IS NOT NULL AND (
      NEW.machine_id IS DISTINCT FROM OLD.machine_id OR NEW.sector_id IS DISTINCT FROM OLD.sector_id
      OR NEW.destination_snapshot IS DISTINCT FROM OLD.destination_snapshot
    ) THEN
      RAISE EXCEPTION 'RBE draft source context cannot be changed after the first package' USING ERRCODE='23514';
    END IF;
    IF NEW.status='draft' THEN
      RETURN NEW;
    ELSIF NEW.status='discarded' THEN
      IF actor IS NULL OR NEW.discarded_by IS DISTINCT FROM actor OR NEW.discarded_at IS NULL
         OR length(btrim(coalesce(NEW.discarded_reason,''))) NOT BETWEEN 1 AND 300
         OR NEW.generated_by IS NOT NULL OR NEW.report_snapshot IS NOT NULL THEN
        RAISE EXCEPTION 'Discard requires the draft creator and a reason' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    ELSIF NEW.status='generated' THEN
      IF actor IS NULL OR NEW.generated_by IS DISTINCT FROM actor OR NEW.generated_at IS NULL
         OR NEW.generation_idempotency_key IS NULL OR NEW.generation_request_sha256 !~ '^[a-f0-9]{64}$'
         OR NEW.report_snapshot IS NULL OR NEW.snapshot_version IS NULL
         OR NEW.machine_id IS NULL OR NEW.sector_id IS NULL OR NEW.destination_snapshot IS NULL
         OR NEW.discarded_by IS NOT NULL OR NEW.annulled_by IS NOT NULL THEN
        RAISE EXCEPTION 'Generation metadata is incomplete or actor mismatched' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Invalid RBE draft transition' USING ERRCODE='23514';
  ELSIF OLD.status IN ('generated','observed') AND NEW.status='annulled' THEN
    IF actor IS NULL OR NEW.annulled_by IS DISTINCT FROM actor OR NEW.annulled_at IS NULL
       OR length(btrim(coalesce(NEW.annulled_reason,''))) NOT BETWEEN 10 AND 300
       OR (to_jsonb(NEW) - ARRAY['status','annulled_by','annulled_at','annulled_reason','updated_at','updated_by'])
          IS DISTINCT FROM
          (to_jsonb(OLD) - ARRAY['status','annulled_by','annulled_at','annulled_reason','updated_at','updated_by']) THEN
      RAISE EXCEPTION 'RBE annulment requires Jefatura actor and preserves generated snapshot' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  ELSIF OLD.status='generated' AND NEW.status='observed'
        AND current_setting('vinto.rewinding_export_observe',true)='approved' THEN
    IF actor IS NULL OR (to_jsonb(NEW) - ARRAY['status','updated_at','updated_by'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status','updated_at','updated_by']) THEN
      RAISE EXCEPTION 'RBE observation must preserve report data' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'RBE report state is immutable' USING ERRCODE='23514';
END $$;

CREATE FUNCTION vinto_txn.guard_rewinding_export_package()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  actor uuid := nullif(current_setting('vinto.actor_id',true),'')::uuid;
  r record;
  latest_classification uuid;
  latest_value text;
  source_label text;
  source_destination text;
  source_operator uuid;
  source_operator_name text;
  source_article_id uuid;
  source_article_code text;
  source_article_description text;
  source_machine_code text;
  source_machine_name text;
  source_work_order_number text;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'RBE packages are removed logically, never deleted' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' THEN
    IF actor IS NULL OR NEW.created_by IS DISTINCT FROM actor THEN
      RAISE EXCEPTION 'RBE package requires the authenticated creator' USING ERRCODE='23514';
    END IF;
    SELECT r.status, r.pv_reference, r.article_id, r.machine_id, r.sector_id, r.destination_snapshot
      INTO r FROM vinto_txn.rewinding_export_report r WHERE r.id=NEW.report_id;
    IF NOT FOUND OR r.status <> 'draft' THEN
      RAISE EXCEPTION 'Packages can only be added to a draft' USING ERRCODE='23514';
    END IF;

    SELECT c.machine_id, c.revision, c.form_version_id, c.created_by,
           f.code, fv.version_number, c.status,
           s.id AS sector_id, s.code AS sector_code,
           m.code AS machine_code, m.name AS machine_name,
           wo.id AS work_order_id, wo.number AS work_order_number,
           wo.archived_at, wo.qa_retired, wo.status AS work_order_status,
           wol.id AS work_order_line_id, wol.pv_reference, wol.article_version_id,
           av.article_id, ar.code AS article_code, av.description AS article_description,
           label.value_text AS mother_label, destination.value_text AS destination,
           mother.id AS mother_bobbin_id
      INTO source_label, source_destination, source_operator, source_operator_name,
           source_article_id, source_article_code, source_article_description,
           source_machine_code, source_machine_name, source_work_order_number,
           r
      FROM vinto_txn.capture c
      JOIN vinto_config.form_version fv ON fv.id=c.form_version_id
      JOIN vinto_config.form f ON f.id=fv.form_id
      JOIN vinto_txn.assignment a ON a.id=c.assignment_id
      JOIN vinto_txn.work_order_line wol ON wol.id=a.work_order_line_id
      JOIN vinto_txn.work_order_version wov ON wov.id=wol.work_order_version_id
      JOIN vinto_txn.work_order wo ON wo.id=wov.work_order_id
      JOIN vinto_master.machine m ON m.id=c.machine_id
      JOIN vinto_master.sector s ON s.id=m.sector_id
      JOIN vinto_master.article_version av ON av.id=wol.article_version_id
      JOIN vinto_master.article ar ON ar.id=av.article_id
      LEFT JOIN vinto_txn.bobbin mother ON mother.rewind_mother_capture_id=c.id
      LEFT JOIN LATERAL (
        SELECT d.value_text FROM vinto_txn.capture_detail d
        JOIN vinto_config.field_definition fd ON fd.id=d.field_definition_id
        WHERE d.capture_id=c.id AND fd.key='etiqueta_numero_de_bobina' LIMIT 1
      ) label ON true
      LEFT JOIN LATERAL (
        SELECT d.value_text FROM vinto_txn.capture_detail d
        JOIN vinto_config.field_definition fd ON fd.id=d.field_definition_id
        WHERE d.capture_id=c.id AND fd.key='destino' LIMIT 1
      ) destination ON true
      WHERE c.id=NEW.mother_capture_id;
    IF NOT FOUND OR f.code <> 'VINTO-P1-07' OR fv.version_number < 3
       OR r.status NOT IN ('submitted','closed') OR r.sector_code <> 'REBOBINADO'
       OR r.archived_at IS NOT NULL OR r.qa_retired
       OR r.work_order_status NOT IN ('published','in_progress','closed')
       OR r.work_order_id IS DISTINCT FROM NEW.work_order_id
       OR r.work_order_line_id IS DISTINCT FROM NEW.work_order_line_id
       OR r.article_version_id IS DISTINCT FROM NEW.article_version_id
       OR r.machine_id IS DISTINCT FROM r.machine_id
       OR r.revision IS DISTINCT FROM NEW.source_capture_revision
       OR r.form_version_id IS DISTINCT FROM NEW.source_form_version_id
       OR r.created_by IS DISTINCT FROM NEW.source_operator_user_id
       OR r.sector_id IS DISTINCT FROM r.sector_id
       OR r.pv_reference IS DISTINCT FROM (SELECT pv_reference FROM vinto_txn.work_order_line WHERE id=NEW.work_order_line_id)
       OR r.article_id IS DISTINCT FROM (SELECT article_id FROM vinto_master.article_version WHERE id=NEW.article_version_id)
       OR r.machine_id IS DISTINCT FROM (SELECT machine_id FROM vinto_txn.capture WHERE id=NEW.mother_capture_id)
       OR r.sector_id IS DISTINCT FROM (SELECT s.id FROM vinto_master.sector s JOIN vinto_master.machine m ON m.sector_id=s.id WHERE m.id=r.machine_id)
       OR source_label IS DISTINCT FROM NEW.mother_label_snapshot
       OR source_label IS NULL OR btrim(source_label)=''
       OR source_destination IS DISTINCT FROM r.destination_snapshot
       OR source_destination IS NULL OR btrim(source_destination)=''
       OR source_operator IS DISTINCT FROM NEW.source_operator_user_id
       OR source_operator_name IS DISTINCT FROM NEW.operator_display_name_snapshot
       OR source_article_id IS DISTINCT FROM r.article_id
       OR source_article_code IS DISTINCT FROM NEW.article_code_snapshot
       OR source_article_description IS DISTINCT FROM NEW.article_description_snapshot
       OR source_machine_code IS DISTINCT FROM NEW.machine_code_snapshot
       OR source_machine_name IS DISTINCT FROM NEW.machine_name_snapshot
       OR source_work_order_number IS DISTINCT FROM NEW.work_order_number_snapshot
       OR mother.id IS DISTINCT FROM NEW.mother_bobbin_id THEN
      RAISE EXCEPTION 'RBE package source chain does not match the P1-07 capture' USING ERRCODE='23514';
    END IF;

    SELECT c.id, c.classification INTO latest_classification, latest_value
      FROM vinto_txn.rewinding_export_work_order_classification c
      WHERE c.work_order_id=NEW.work_order_id ORDER BY c.sequence_no DESC LIMIT 1;
    IF latest_classification IS NULL OR latest_value <> 'production_confirmed'
       OR latest_classification IS DISTINCT FROM NEW.source_work_order_classification_id THEN
      RAISE EXCEPTION 'RBE package requires the latest production_confirmed OT classification' USING ERRCODE='23514';
    END IF;
    IF r.machine_id IS DISTINCT FROM r.machine_id THEN
      RAISE EXCEPTION 'RBE report machine context mismatch' USING ERRCODE='23514';
    END IF;
    IF NEW.source_fields_snapshot IS NULL OR jsonb_typeof(NEW.source_fields_snapshot) <> 'object' THEN
      RAISE EXCEPTION 'RBE package source fields snapshot is invalid' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;

  SELECT status INTO latest_value FROM vinto_txn.rewinding_export_report WHERE id=OLD.report_id;
  IF latest_value <> 'draft' THEN
    RAISE EXCEPTION 'Generated RBE packages are immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.report_id IS DISTINCT FROM OLD.report_id
     OR NEW.package_number IS DISTINCT FROM OLD.package_number
     OR NEW.mother_capture_id IS DISTINCT FROM OLD.mother_capture_id
     OR NEW.mother_bobbin_id IS DISTINCT FROM OLD.mother_bobbin_id
     OR NEW.mother_label_snapshot IS DISTINCT FROM OLD.mother_label_snapshot
     OR NEW.source_capture_revision IS DISTINCT FROM OLD.source_capture_revision
     OR NEW.source_form_version_id IS DISTINCT FROM OLD.source_form_version_id
     OR NEW.work_order_id IS DISTINCT FROM OLD.work_order_id
     OR NEW.work_order_line_id IS DISTINCT FROM OLD.work_order_line_id
     OR NEW.article_version_id IS DISTINCT FROM OLD.article_version_id
     OR NEW.source_fields_snapshot IS DISTINCT FROM OLD.source_fields_snapshot
     OR NEW.source_operator_user_id IS DISTINCT FROM OLD.source_operator_user_id
     OR NEW.operator_display_name_snapshot IS DISTINCT FROM OLD.operator_display_name_snapshot
     OR NEW.machine_code_snapshot IS DISTINCT FROM OLD.machine_code_snapshot
     OR NEW.machine_name_snapshot IS DISTINCT FROM OLD.machine_name_snapshot
     OR NEW.work_order_number_snapshot IS DISTINCT FROM OLD.work_order_number_snapshot
     OR NEW.article_code_snapshot IS DISTINCT FROM OLD.article_code_snapshot
     OR NEW.article_description_snapshot IS DISTINCT FROM OLD.article_description_snapshot
     OR NEW.created_by IS DISTINCT FROM OLD.created_by
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'RBE package source identity and snapshots are immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.source_work_order_classification_id IS DISTINCT FROM OLD.source_work_order_classification_id THEN
    IF OLD.removed_at IS NOT NULL OR NEW.removed_at IS NOT NULL OR NEW.removed_by IS DISTINCT FROM OLD.removed_by THEN
      RAISE EXCEPTION 'RBE package classification refresh cannot be combined with removal' USING ERRCODE='23514';
    END IF;
    SELECT classification INTO latest_value
      FROM vinto_txn.rewinding_export_work_order_classification
      WHERE id=NEW.source_work_order_classification_id AND work_order_id=OLD.work_order_id;
    IF latest_value <> 'production_confirmed' OR NEW.source_work_order_classification_id IS DISTINCT FROM (
      SELECT id FROM vinto_txn.rewinding_export_work_order_classification
      WHERE work_order_id=OLD.work_order_id ORDER BY sequence_no DESC LIMIT 1
    ) THEN
      RAISE EXCEPTION 'RBE package classification refresh must use the latest positive decision' USING ERRCODE='23514';
    END IF;
  END IF;
  IF NEW.removed_at IS DISTINCT FROM OLD.removed_at OR NEW.removed_by IS DISTINCT FROM OLD.removed_by THEN
    IF OLD.removed_at IS NOT NULL OR NEW.removed_at IS NULL OR NEW.removed_by IS DISTINCT FROM actor
       OR actor IS NULL OR NEW.source_work_order_classification_id IS DISTINCT FROM OLD.source_work_order_classification_id THEN
      RAISE EXCEPTION 'RBE package logical removal requires the creator actor' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION vinto_txn.guard_rewinding_export_package_child()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  actor uuid := nullif(current_setting('vinto.actor_id',true),'')::uuid;
  report_status text;
  package_mother uuid;
  bobbin_capture uuid;
  bobbin_position integer;
  bobbin_weight numeric;
  quality_status text;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'RBE child selections are removed logically, never deleted' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' THEN
    IF actor IS NULL OR NEW.created_by IS DISTINCT FROM actor THEN
      RAISE EXCEPTION 'RBE child selection requires the authenticated actor' USING ERRCODE='23514';
    END IF;
    SELECT r.status, p.mother_capture_id INTO report_status, package_mother
      FROM vinto_txn.rewinding_export_package p
      JOIN vinto_txn.rewinding_export_report r ON r.id=p.report_id
      WHERE p.id=NEW.package_id AND p.report_id=NEW.report_id AND p.removed_at IS NULL;
    IF report_status IS DISTINCT FROM 'draft' THEN
      RAISE EXCEPTION 'RBE child selections can only be added to active draft packages' USING ERRCODE='23514';
    END IF;
    SELECT b.source_capture_id, b.rewind_child_position, b.weight_kg, q.status
      INTO bobbin_capture, bobbin_position, bobbin_weight, quality_status
      FROM vinto_txn.bobbin b
      JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id
      WHERE b.id=NEW.child_bobbin_id;
    IF NOT FOUND OR bobbin_capture IS DISTINCT FROM package_mother
       OR bobbin_position IS DISTINCT FROM NEW.source_position
       OR bobbin_weight IS DISTINCT FROM NEW.weight_kg_snapshot
       OR quality_status <> 'released'
       OR bobbin_position IS NULL OR bobbin_position=12 OR bobbin_position NOT BETWEEN 1 AND 22 THEN
      RAISE EXCEPTION 'RBE child must be a released child of the selected mother with unchanged position and weight' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;

  SELECT status INTO report_status FROM vinto_txn.rewinding_export_report WHERE id=OLD.report_id;
  IF report_status <> 'draft' THEN
    RAISE EXCEPTION 'Generated RBE child selections are immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.report_id IS DISTINCT FROM OLD.report_id
     OR NEW.package_id IS DISTINCT FROM OLD.package_id
     OR NEW.child_bobbin_id IS DISTINCT FROM OLD.child_bobbin_id
     OR NEW.package_slot IS DISTINCT FROM OLD.package_slot
     OR NEW.source_position IS DISTINCT FROM OLD.source_position
     OR NEW.weight_kg_snapshot IS DISTINCT FROM OLD.weight_kg_snapshot
     OR NEW.created_by IS DISTINCT FROM OLD.created_by
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'RBE child identity and source snapshot are immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.removed_at IS DISTINCT FROM OLD.removed_at OR NEW.removed_by IS DISTINCT FROM OLD.removed_by THEN
    IF OLD.removed_at IS NOT NULL OR NEW.removed_at IS NULL OR NEW.removed_by IS DISTINCT FROM actor OR actor IS NULL THEN
      RAISE EXCEPTION 'RBE child logical removal requires the authenticated actor' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION vinto_txn.guard_rewinding_export_pdf()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  actor uuid := nullif(current_setting('vinto.actor_id',true),'')::uuid;
  status text;
  generated_by uuid;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'Original RBE PDF is immutable' USING ERRCODE='23514';
  END IF;
  SELECT r.status, r.generated_by INTO status, generated_by
    FROM vinto_txn.rewinding_export_report r WHERE r.id=NEW.report_id;
  IF status NOT IN ('generated','observed','annulled') OR actor IS NULL
     OR generated_by IS DISTINCT FROM actor
     OR NEW.generated_at IS DISTINCT FROM (SELECT generated_at FROM vinto_txn.rewinding_export_report WHERE id=NEW.report_id) THEN
    RAISE EXCEPTION 'RBE PDF must be inserted by the report generator after the state transition' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION vinto_txn.guard_rewinding_export_reservation()
RETURNS trigger LANGUAGE plpgsql AS $rbe$
DECLARE
  actor uuid := nullif(current_setting('vinto.actor_id',true),'')::uuid;
  report_status text;
  report_generator uuid;
  report_annuller uuid;
  annulment_reason text;
  child_active boolean;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'RBE reservation history cannot be deleted' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' THEN
    SELECT r.status, r.generated_by, (c.removed_at IS NULL AND p.removed_at IS NULL)
      INTO report_status, report_generator, child_active
      FROM vinto_txn.rewinding_export_package_child c
      JOIN vinto_txn.rewinding_export_package p ON p.id=c.package_id AND p.report_id=c.report_id
      JOIN vinto_txn.rewinding_export_report r ON r.id=p.report_id
      WHERE c.id=NEW.package_child_id AND c.child_bobbin_id=NEW.child_bobbin_id;
    IF NOT FOUND OR report_status NOT IN ('generated','observed') OR NOT child_active
       OR actor IS NULL OR report_generator IS DISTINCT FROM actor
       OR NEW.reserved_by IS DISTINCT FROM actor THEN
      RAISE EXCEPTION 'RBE reservation must match an active generated package selection' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;

  SELECT r.status, r.annulled_by, r.annulled_reason
    INTO report_status, report_annuller, annulment_reason
    FROM vinto_txn.rewinding_export_package_child c
    JOIN vinto_txn.rewinding_export_package p ON p.id=c.package_id AND p.report_id=c.report_id
    JOIN vinto_txn.rewinding_export_report r ON r.id=p.report_id
    WHERE c.id=OLD.package_child_id AND c.child_bobbin_id=OLD.child_bobbin_id;
  IF report_status <> 'annulled' OR actor IS NULL OR report_annuller IS DISTINCT FROM actor
     OR NEW.id IS DISTINCT FROM OLD.id
     OR NEW.package_child_id IS DISTINCT FROM OLD.package_child_id
     OR NEW.child_bobbin_id IS DISTINCT FROM OLD.child_bobbin_id
     OR NEW.reserved_at IS DISTINCT FROM OLD.reserved_at
     OR NEW.reserved_by IS DISTINCT FROM OLD.reserved_by
     OR OLD.released_at IS NOT NULL OR NEW.released_at IS NULL
     OR NEW.released_by IS DISTINCT FROM actor
     OR NEW.release_reason IS DISTINCT FROM annulment_reason THEN
    RAISE EXCEPTION 'RBE reservations are released only by the authenticated annulment transaction' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $rbe$;

CREATE FUNCTION vinto_txn.guard_rewinding_export_event()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor uuid := nullif(current_setting('vinto.actor_id',true),'')::uuid;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'RBE report events are append-only' USING ERRCODE='23514';
  END IF;
  IF actor IS NULL OR NEW.actor_id IS DISTINCT FROM actor THEN
    RAISE EXCEPTION 'RBE event actor must match the authenticated session' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION vinto_txn.assert_rewinding_export_integrity()
RETURNS trigger LANGUAGE plpgsql AS $rbe$
DECLARE
  rid uuid;
  report_status text;
  active_children bigint;
  active_reservations bigint;
BEGIN
  IF TG_TABLE_NAME='rewinding_export_report' THEN
    rid := CASE WHEN TG_OP='DELETE' THEN OLD.id ELSE NEW.id END;
  ELSIF TG_TABLE_NAME='rewinding_export_reservation' THEN
    SELECT p.report_id INTO rid
      FROM vinto_txn.rewinding_export_package_child c
      JOIN vinto_txn.rewinding_export_package p ON p.id=c.package_id AND p.report_id=c.report_id
      WHERE c.id=CASE WHEN TG_OP='DELETE' THEN OLD.package_child_id ELSE NEW.package_child_id END;
  ELSE
    rid := CASE WHEN TG_OP='DELETE' THEN OLD.report_id ELSE NEW.report_id END;
  END IF;
  SELECT status INTO report_status FROM vinto_txn.rewinding_export_report WHERE id=rid;
  IF NOT FOUND THEN RETURN NULL; END IF;

  IF EXISTS (
    SELECT 1 FROM vinto_txn.rewinding_export_package p
    WHERE p.report_id=rid AND p.removed_at IS NOT NULL
      AND EXISTS (SELECT 1 FROM vinto_txn.rewinding_export_package_child c
                  WHERE c.package_id=p.id AND c.removed_at IS NULL)
  ) THEN
    RAISE EXCEPTION 'Removed RBE package retains active child selections' USING ERRCODE='23514';
  END IF;
  IF report_status IN ('generated','observed','annulled') AND (
    EXISTS (
      SELECT 1 FROM vinto_txn.rewinding_export_package p
      WHERE p.report_id=rid AND p.removed_at IS NULL
        AND (SELECT count(*) FROM vinto_txn.rewinding_export_package_child c
             WHERE c.package_id=p.id AND c.removed_at IS NULL) NOT BETWEEN 1 AND 5
    ) OR EXISTS (
      SELECT 1 FROM vinto_txn.rewinding_export_package p
      WHERE p.report_id=rid AND p.removed_at IS NULL
        AND NOT EXISTS (SELECT 1 FROM vinto_txn.rewinding_export_package_child c
                        WHERE c.package_id=p.id AND c.removed_at IS NULL AND c.package_slot='A')
    )
  ) THEN
    RAISE EXCEPTION 'Generated RBE packages require one to five active children and slot A' USING ERRCODE='23514';
  END IF;

  SELECT count(*) INTO active_children
    FROM vinto_txn.rewinding_export_package_child c
    JOIN vinto_txn.rewinding_export_package p ON p.id=c.package_id
    WHERE c.report_id=rid AND c.removed_at IS NULL AND p.removed_at IS NULL;
  SELECT count(*) INTO active_reservations
    FROM vinto_txn.rewinding_export_reservation r
    JOIN vinto_txn.rewinding_export_package_child c ON c.id=r.package_child_id
    JOIN vinto_txn.rewinding_export_package p ON p.id=c.package_id AND p.report_id=c.report_id
    WHERE p.report_id=rid AND r.released_at IS NULL;

  IF report_status IN ('draft','discarded') THEN
    IF active_reservations <> 0 OR EXISTS (SELECT 1 FROM vinto_txn.rewinding_export_pdf WHERE report_id=rid) THEN
      RAISE EXCEPTION 'Draft/discarded RBE reports cannot have reservations or a final PDF' USING ERRCODE='23514';
    END IF;
  ELSIF report_status IN ('generated','observed') THEN
    IF NOT EXISTS (SELECT 1 FROM vinto_txn.rewinding_export_pdf WHERE report_id=rid)
       OR active_children=0 OR active_reservations <> active_children
       OR EXISTS (
         SELECT 1 FROM vinto_txn.rewinding_export_package_child c
         JOIN vinto_txn.rewinding_export_package p ON p.id=c.package_id
         WHERE c.report_id=rid AND c.removed_at IS NULL AND p.removed_at IS NULL
           AND NOT EXISTS (SELECT 1 FROM vinto_txn.rewinding_export_reservation r
                           WHERE r.package_child_id=c.id AND r.released_at IS NULL)
       ) THEN
      RAISE EXCEPTION 'Generated/observed RBE report requires an original PDF and one active reservation per child' USING ERRCODE='23514';
    END IF;
  ELSIF report_status='annulled' THEN
    IF NOT EXISTS (SELECT 1 FROM vinto_txn.rewinding_export_pdf WHERE report_id=rid)
       OR active_reservations <> 0 THEN
      RAISE EXCEPTION 'Annulled RBE report keeps its PDF and has no active reservations' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NULL;
END $rbe$;


CREATE FUNCTION vinto_txn.guard_rewinding_export_report_v2()
RETURNS trigger LANGUAGE plpgsql AS $rbe$
DECLARE
  actor uuid := nullif(current_setting('vinto.actor_id',true),'')::uuid;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'RBE report history cannot be deleted' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' THEN
    IF NEW.status <> 'draft' OR actor IS NULL OR NEW.created_by IS DISTINCT FROM actor
       OR NEW.generated_by IS NOT NULL OR NEW.annulled_by IS NOT NULL OR NEW.discarded_by IS NOT NULL THEN
      RAISE EXCEPTION 'RBE report must be created as a draft by the authenticated actor' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;

  IF OLD.status='draft' THEN
    IF actor IS NULL OR actor IS DISTINCT FROM OLD.created_by THEN
      RAISE EXCEPTION 'Only the draft creator may edit or generate this RBE report' USING ERRCODE='23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.pv_reference IS DISTINCT FROM OLD.pv_reference
       OR NEW.article_id IS DISTINCT FROM OLD.article_id
       OR NEW.article_code_snapshot IS DISTINCT FROM OLD.article_code_snapshot THEN
      RAISE EXCEPTION 'RBE draft identity and source context are immutable' USING ERRCODE='23514';
    END IF;
    IF OLD.machine_id IS NOT NULL AND (
      NEW.machine_id IS DISTINCT FROM OLD.machine_id OR NEW.sector_id IS DISTINCT FROM OLD.sector_id
      OR NEW.destination_snapshot IS DISTINCT FROM OLD.destination_snapshot
    ) THEN
      RAISE EXCEPTION 'RBE draft source context cannot be changed after the first package' USING ERRCODE='23514';
    END IF;
    IF NEW.status='draft' THEN
      IF (to_jsonb(NEW) - ARRAY['truck_number','order_number','observations','machine_id','sector_id',
                                'destination_snapshot','updated_at','updated_by'])
         IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['truck_number','order_number','observations','machine_id','sector_id',
                                'destination_snapshot','updated_at','updated_by']) THEN
        RAISE EXCEPTION 'Only RBE draft header fields may be edited' USING ERRCODE='23514';
      END IF;
      IF NEW.machine_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM vinto_master.machine m JOIN vinto_master.sector s ON s.id=m.sector_id
        WHERE m.id=NEW.machine_id AND s.id=NEW.sector_id AND s.code='REBOBINADO'
          AND s.active AND m.active
      ) THEN
        RAISE EXCEPTION 'RBE draft machine must belong to the active REBOBINADO sector' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    ELSIF NEW.status='discarded' THEN
      IF actor IS NULL OR NEW.discarded_by IS DISTINCT FROM actor
         OR NEW.discarded_by IS DISTINCT FROM OLD.created_by OR NEW.discarded_at IS NULL
         OR length(btrim(coalesce(NEW.discarded_reason,''))) NOT BETWEEN 1 AND 300
         OR NEW.generated_by IS NOT NULL OR NEW.report_snapshot IS NOT NULL
         OR (to_jsonb(NEW) - ARRAY['status','discarded_by','discarded_at','discarded_reason','updated_at','updated_by'])
            IS DISTINCT FROM
            (to_jsonb(OLD) - ARRAY['status','discarded_by','discarded_at','discarded_reason','updated_at','updated_by']) THEN
        RAISE EXCEPTION 'Discard requires the draft creator and preserves draft history' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    ELSIF NEW.status='generated' THEN
      IF actor IS NULL OR NEW.generated_by IS DISTINCT FROM actor
         OR NEW.generated_by IS DISTINCT FROM OLD.created_by OR NEW.generated_at IS NULL
         OR NEW.generation_idempotency_key IS NULL OR NEW.generation_request_sha256 !~ '^[a-f0-9]{64}$'
         OR NEW.report_snapshot IS NULL OR NEW.snapshot_version IS NULL
         OR NEW.machine_id IS NULL OR NEW.sector_id IS NULL OR NEW.destination_snapshot IS NULL
         OR NEW.discarded_by IS NOT NULL OR NEW.annulled_by IS NOT NULL
         OR (to_jsonb(NEW) - ARRAY['status','generated_by','generated_at','generation_idempotency_key',
                                   'generation_request_sha256','report_snapshot','snapshot_version','updated_at','updated_by'])
            IS DISTINCT FROM
            (to_jsonb(OLD) - ARRAY['status','generated_by','generated_at','generation_idempotency_key',
                                   'generation_request_sha256','report_snapshot','snapshot_version','updated_at','updated_by']) THEN
        RAISE EXCEPTION 'Generation metadata is incomplete or actor mismatched' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Invalid RBE draft transition' USING ERRCODE='23514';
  ELSIF OLD.status IN ('generated','observed') AND NEW.status='annulled' THEN
    IF actor IS NULL OR NEW.annulled_by IS DISTINCT FROM actor OR NEW.annulled_at IS NULL
       OR length(btrim(coalesce(NEW.annulled_reason,''))) NOT BETWEEN 10 AND 300
       OR NOT EXISTS (SELECT 1 FROM vinto_master."user" u WHERE u.id=actor AND u.active)
       OR NOT EXISTS (
         SELECT 1 FROM vinto_master.user_profile up
         JOIN vinto_master.profile p ON p.id=up.profile_id
         WHERE up.user_id=actor AND p.code='JEFATURA' AND p.active
       )
       OR NOT EXISTS (
         SELECT 1 FROM vinto_master.user_sector us
         JOIN vinto_master.sector s ON s.id=us.sector_id
         WHERE us.user_id=actor AND s.code='REBOBINADO' AND s.active
       )
       OR (to_jsonb(NEW) - ARRAY['status','annulled_by','annulled_at','annulled_reason','updated_at','updated_by'])
          IS DISTINCT FROM
          (to_jsonb(OLD) - ARRAY['status','annulled_by','annulled_at','annulled_reason','updated_at','updated_by']) THEN
      RAISE EXCEPTION 'RBE annulment requires Jefatura actor and preserves generated snapshot' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  ELSIF OLD.status='generated' AND NEW.status='observed'
        AND current_setting('vinto.rewinding_export_observe',true)='approved' THEN
    IF actor IS NULL OR (to_jsonb(NEW) - ARRAY['status','updated_at','updated_by'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status','updated_at','updated_by']) THEN
      RAISE EXCEPTION 'RBE observation must preserve report data' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'RBE report state is immutable' USING ERRCODE='23514';
END $rbe$;

CREATE FUNCTION vinto_txn.guard_rewinding_export_package_v2()
RETURNS trigger LANGUAGE plpgsql AS $rbe$
DECLARE
  actor uuid := nullif(current_setting('vinto.actor_id',true),'')::uuid;
  report_row record;
  src record;
  report_creator uuid;
  latest_classification uuid;
  latest_value text;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'RBE packages are removed logically, never deleted' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' THEN
    IF actor IS NULL OR NEW.created_by IS DISTINCT FROM actor THEN
      RAISE EXCEPTION 'RBE package requires the authenticated creator' USING ERRCODE='23514';
    END IF;
    SELECT r.status, r.created_by, r.pv_reference, r.article_id, r.article_code_snapshot,
           r.machine_id, r.sector_id, r.destination_snapshot
      INTO report_row FROM vinto_txn.rewinding_export_report r WHERE r.id=NEW.report_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'RBE report not found' USING ERRCODE='23514';
    END IF;
    IF report_row.status <> 'draft' OR report_row.created_by IS DISTINCT FROM actor THEN
      RAISE EXCEPTION 'Only the creator may add packages to their RBE draft' USING ERRCODE='23514';
    END IF;

    SELECT c.machine_id, c.revision, c.form_version_id, c.created_by,
           f.code AS form_code, fv.version_number, c.status AS capture_status,
           s.id AS sector_id, s.code AS sector_code, s.active AS sector_active,
           m.code AS machine_code, m.name AS machine_name, m.active AS machine_active,
           wo.id AS work_order_id, wo.number AS work_order_number,
           wo.archived_at, wo.qa_retired, wo.status AS work_order_status,
           wol.id AS work_order_line_id, wol.machine_id AS line_machine_id,
           wol.pv_reference, wol.article_version_id,
           av.article_id, ar.code AS article_code, av.description AS article_description,
           label.value_text AS mother_label, destination.value_text AS destination,
           mother.id AS mother_bobbin_id, u.display_name AS operator_name
      INTO src
      FROM vinto_txn.capture c
      JOIN vinto_config.form_version fv ON fv.id=c.form_version_id
      JOIN vinto_config.form f ON f.id=fv.form_id
      JOIN vinto_txn.assignment a ON a.id=c.assignment_id
      JOIN vinto_txn.work_order_line wol ON wol.id=a.work_order_line_id
      JOIN vinto_txn.work_order_version wov ON wov.id=wol.work_order_version_id
      JOIN vinto_txn.work_order wo ON wo.id=wov.work_order_id
      JOIN vinto_master.machine m ON m.id=c.machine_id
      JOIN vinto_master.sector s ON s.id=m.sector_id
      JOIN vinto_master.article_version av ON av.id=wol.article_version_id
      JOIN vinto_master.article ar ON ar.id=av.article_id
      LEFT JOIN vinto_master."user" u ON u.id=c.created_by
      LEFT JOIN vinto_txn.bobbin mother ON mother.rewind_mother_capture_id=c.id
      LEFT JOIN LATERAL (
        SELECT d.value_text FROM vinto_txn.capture_detail d
        JOIN vinto_config.field_definition fd ON fd.id=d.field_definition_id
        WHERE d.capture_id=c.id AND fd.key='etiqueta_numero_de_bobina' LIMIT 1
      ) label ON true
      LEFT JOIN LATERAL (
        SELECT d.value_text FROM vinto_txn.capture_detail d
        JOIN vinto_config.field_definition fd ON fd.id=d.field_definition_id
        WHERE d.capture_id=c.id AND fd.key='destino' LIMIT 1
      ) destination ON true
      WHERE c.id=NEW.mother_capture_id;

    IF NOT FOUND THEN
      RAISE EXCEPTION 'P1-07 mother capture not found or source chain incomplete' USING ERRCODE='23514';
    END IF;
    IF src.form_code <> 'VINTO-P1-07' OR src.version_number < 3
       OR src.capture_status NOT IN ('submitted','closed')
       OR src.sector_code <> 'REBOBINADO' OR NOT src.sector_active OR NOT src.machine_active
       OR src.archived_at IS NOT NULL OR src.qa_retired
       OR src.work_order_status NOT IN ('published','in_progress','closed')
       OR src.work_order_id IS DISTINCT FROM NEW.work_order_id
       OR src.work_order_line_id IS DISTINCT FROM NEW.work_order_line_id
       OR src.article_version_id IS DISTINCT FROM NEW.article_version_id
       OR src.line_machine_id IS DISTINCT FROM src.machine_id
       OR src.revision IS DISTINCT FROM NEW.source_capture_revision
       OR src.form_version_id IS DISTINCT FROM NEW.source_form_version_id
       OR src.created_by IS DISTINCT FROM NEW.source_operator_user_id
       OR src.pv_reference IS DISTINCT FROM report_row.pv_reference
       OR src.article_id IS DISTINCT FROM report_row.article_id
       OR src.article_code IS DISTINCT FROM report_row.article_code_snapshot
       OR src.machine_id IS DISTINCT FROM report_row.machine_id
       OR src.sector_id IS DISTINCT FROM report_row.sector_id
       OR src.destination IS DISTINCT FROM report_row.destination_snapshot
       OR src.mother_label IS DISTINCT FROM NEW.mother_label_snapshot
       OR src.mother_label IS NULL OR btrim(src.mother_label)=''
       OR src.destination IS NULL OR btrim(src.destination)=''
       OR src.operator_name IS DISTINCT FROM NEW.operator_display_name_snapshot
       OR src.article_code IS DISTINCT FROM NEW.article_code_snapshot
       OR src.article_description IS DISTINCT FROM NEW.article_description_snapshot
       OR src.machine_code IS DISTINCT FROM NEW.machine_code_snapshot
       OR src.machine_name IS DISTINCT FROM NEW.machine_name_snapshot
       OR src.work_order_number IS DISTINCT FROM NEW.work_order_number_snapshot
       OR src.mother_bobbin_id IS DISTINCT FROM NEW.mother_bobbin_id THEN
      RAISE EXCEPTION 'RBE package source chain does not match the P1-07 capture' USING ERRCODE='23514';
    END IF;

    SELECT c.id, c.classification INTO latest_classification, latest_value
      FROM vinto_txn.rewinding_export_work_order_classification c
      WHERE c.work_order_id=NEW.work_order_id ORDER BY c.sequence_no DESC LIMIT 1;
    IF latest_classification IS NULL OR latest_value <> 'production_confirmed'
       OR latest_classification IS DISTINCT FROM NEW.source_work_order_classification_id THEN
      RAISE EXCEPTION 'RBE package requires the latest production_confirmed OT classification' USING ERRCODE='23514';
    END IF;
    IF NEW.source_fields_snapshot IS NULL OR jsonb_typeof(NEW.source_fields_snapshot) <> 'object' THEN
      RAISE EXCEPTION 'RBE package source fields snapshot is invalid' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;

  SELECT r.status, r.created_by INTO latest_value, report_creator
    FROM vinto_txn.rewinding_export_report r WHERE r.id=OLD.report_id;
  IF latest_value <> 'draft' OR actor IS NULL OR actor IS DISTINCT FROM report_creator THEN
    RAISE EXCEPTION 'Generated RBE packages are immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.report_id IS DISTINCT FROM OLD.report_id
     OR NEW.package_number IS DISTINCT FROM OLD.package_number
     OR NEW.mother_capture_id IS DISTINCT FROM OLD.mother_capture_id
     OR NEW.mother_bobbin_id IS DISTINCT FROM OLD.mother_bobbin_id
     OR NEW.mother_label_snapshot IS DISTINCT FROM OLD.mother_label_snapshot
     OR NEW.source_capture_revision IS DISTINCT FROM OLD.source_capture_revision
     OR NEW.source_form_version_id IS DISTINCT FROM OLD.source_form_version_id
     OR NEW.work_order_id IS DISTINCT FROM OLD.work_order_id
     OR NEW.work_order_line_id IS DISTINCT FROM OLD.work_order_line_id
     OR NEW.article_version_id IS DISTINCT FROM OLD.article_version_id
     OR NEW.source_fields_snapshot IS DISTINCT FROM OLD.source_fields_snapshot
     OR NEW.source_operator_user_id IS DISTINCT FROM OLD.source_operator_user_id
     OR NEW.operator_display_name_snapshot IS DISTINCT FROM OLD.operator_display_name_snapshot
     OR NEW.machine_code_snapshot IS DISTINCT FROM OLD.machine_code_snapshot
     OR NEW.machine_name_snapshot IS DISTINCT FROM OLD.machine_name_snapshot
     OR NEW.work_order_number_snapshot IS DISTINCT FROM OLD.work_order_number_snapshot
     OR NEW.article_code_snapshot IS DISTINCT FROM OLD.article_code_snapshot
     OR NEW.article_description_snapshot IS DISTINCT FROM OLD.article_description_snapshot
     OR NEW.created_by IS DISTINCT FROM OLD.created_by
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'RBE package source identity and snapshots are immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.source_work_order_classification_id IS DISTINCT FROM OLD.source_work_order_classification_id THEN
    IF OLD.removed_at IS NOT NULL OR NEW.removed_at IS NOT NULL OR NEW.removed_by IS DISTINCT FROM OLD.removed_by THEN
      RAISE EXCEPTION 'RBE package classification refresh cannot be combined with removal' USING ERRCODE='23514';
    END IF;
    SELECT classification INTO latest_value
      FROM vinto_txn.rewinding_export_work_order_classification
      WHERE id=NEW.source_work_order_classification_id AND work_order_id=OLD.work_order_id;
    IF latest_value <> 'production_confirmed' OR NEW.source_work_order_classification_id IS DISTINCT FROM (
      SELECT id FROM vinto_txn.rewinding_export_work_order_classification
      WHERE work_order_id=OLD.work_order_id ORDER BY sequence_no DESC LIMIT 1
    ) THEN
      RAISE EXCEPTION 'RBE package classification refresh must use the latest positive decision' USING ERRCODE='23514';
    END IF;
  END IF;
  IF NEW.removed_at IS DISTINCT FROM OLD.removed_at OR NEW.removed_by IS DISTINCT FROM OLD.removed_by THEN
    IF OLD.removed_at IS NOT NULL OR NEW.removed_at IS NULL OR NEW.removed_by IS DISTINCT FROM actor
       OR actor IS NULL OR actor IS DISTINCT FROM (SELECT created_by FROM vinto_txn.rewinding_export_report WHERE id=OLD.report_id)
       OR NEW.source_work_order_classification_id IS DISTINCT FROM OLD.source_work_order_classification_id THEN
      RAISE EXCEPTION 'RBE package logical removal requires the creator actor' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $rbe$;

CREATE FUNCTION vinto_txn.guard_rewinding_export_package_child_v2()
RETURNS trigger LANGUAGE plpgsql AS $rbe$
DECLARE
  actor uuid := nullif(current_setting('vinto.actor_id',true),'')::uuid;
  report_status text;
  report_creator uuid;
  package_mother uuid;
  bobbin_capture uuid;
  bobbin_position integer;
  bobbin_weight numeric;
  quality_status text;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'RBE child selections are removed logically, never deleted' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' THEN
    IF actor IS NULL OR NEW.created_by IS DISTINCT FROM actor THEN
      RAISE EXCEPTION 'RBE child selection requires the authenticated actor' USING ERRCODE='23514';
    END IF;
    SELECT r.status, r.created_by, p.mother_capture_id
      INTO report_status, report_creator, package_mother
      FROM vinto_txn.rewinding_export_package p
      JOIN vinto_txn.rewinding_export_report r ON r.id=p.report_id
      WHERE p.id=NEW.package_id AND p.report_id=NEW.report_id AND p.removed_at IS NULL;
    IF NOT FOUND OR report_status <> 'draft' OR report_creator IS DISTINCT FROM actor THEN
      RAISE EXCEPTION 'RBE child selection requires the owner of an active draft package' USING ERRCODE='23514';
    END IF;
    SELECT b.source_capture_id, b.rewind_child_position, b.weight_kg, q.status
      INTO bobbin_capture, bobbin_position, bobbin_weight, quality_status
      FROM vinto_txn.bobbin b
      JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id
      WHERE b.id=NEW.child_bobbin_id;
    IF NOT FOUND OR bobbin_capture IS DISTINCT FROM package_mother
       OR bobbin_position IS DISTINCT FROM NEW.source_position
       OR bobbin_weight IS DISTINCT FROM NEW.weight_kg_snapshot
       OR quality_status <> 'released'
       OR bobbin_position IS NULL OR bobbin_position=12 OR bobbin_position NOT BETWEEN 1 AND 22 THEN
      RAISE EXCEPTION 'RBE child must be a released child of the selected mother with unchanged position and weight' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;

  SELECT r.status, r.created_by INTO report_status, report_creator
    FROM vinto_txn.rewinding_export_report r WHERE r.id=OLD.report_id;
  IF report_status <> 'draft' THEN
    RAISE EXCEPTION 'Generated RBE child selections are immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.report_id IS DISTINCT FROM OLD.report_id
     OR NEW.package_id IS DISTINCT FROM OLD.package_id
     OR NEW.child_bobbin_id IS DISTINCT FROM OLD.child_bobbin_id
     OR NEW.package_slot IS DISTINCT FROM OLD.package_slot
     OR NEW.source_position IS DISTINCT FROM OLD.source_position
     OR NEW.weight_kg_snapshot IS DISTINCT FROM OLD.weight_kg_snapshot
     OR NEW.created_by IS DISTINCT FROM OLD.created_by
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'RBE child identity and source snapshot are immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.removed_at IS DISTINCT FROM OLD.removed_at OR NEW.removed_by IS DISTINCT FROM OLD.removed_by THEN
    IF OLD.removed_at IS NOT NULL OR NEW.removed_at IS NULL OR NEW.removed_by IS DISTINCT FROM actor
       OR actor IS NULL OR actor IS DISTINCT FROM report_creator THEN
      RAISE EXCEPTION 'RBE child logical removal requires the report creator' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $rbe$;

-- Row-level audit for mutable business tables. The PDF bytes are deliberately excluded from generic audit payloads.
CREATE TRIGGER a_guard_rewinding_export_classification
  BEFORE INSERT OR UPDATE OR DELETE ON vinto_txn.rewinding_export_work_order_classification
  FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_rewinding_export_classification();
CREATE TRIGGER z_touch_rewinding_export_classification
  BEFORE INSERT ON vinto_txn.rewinding_export_work_order_classification
  FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();
CREATE TRIGGER audit_rewinding_export_classification
  AFTER INSERT ON vinto_txn.rewinding_export_work_order_classification
  FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();
CREATE TRIGGER reject_rewinding_export_classification_truncate
  BEFORE TRUNCATE ON vinto_txn.rewinding_export_work_order_classification
  FOR EACH STATEMENT EXECUTE FUNCTION vinto_audit.reject_mutation();

CREATE TRIGGER a_guard_rewinding_export_report
  BEFORE INSERT OR UPDATE OR DELETE ON vinto_txn.rewinding_export_report
  FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_rewinding_export_report_v2();
CREATE TRIGGER z_touch_rewinding_export_report
  BEFORE INSERT OR UPDATE ON vinto_txn.rewinding_export_report
  FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();
CREATE TRIGGER audit_rewinding_export_report
  AFTER INSERT OR UPDATE ON vinto_txn.rewinding_export_report
  FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();
DROP FUNCTION vinto_txn.guard_rewinding_export_report();
CREATE TRIGGER reject_rewinding_export_report_truncate
  BEFORE TRUNCATE ON vinto_txn.rewinding_export_report
  FOR EACH STATEMENT EXECUTE FUNCTION vinto_audit.reject_mutation();

CREATE TRIGGER a_guard_rewinding_export_package
  BEFORE INSERT OR UPDATE OR DELETE ON vinto_txn.rewinding_export_package
  FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_rewinding_export_package_v2();
CREATE TRIGGER z_touch_rewinding_export_package
  BEFORE INSERT OR UPDATE ON vinto_txn.rewinding_export_package
  FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();
CREATE TRIGGER audit_rewinding_export_package
  AFTER INSERT OR UPDATE ON vinto_txn.rewinding_export_package
  FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();
DROP FUNCTION vinto_txn.guard_rewinding_export_package();
CREATE TRIGGER reject_rewinding_export_package_truncate
  BEFORE TRUNCATE ON vinto_txn.rewinding_export_package
  FOR EACH STATEMENT EXECUTE FUNCTION vinto_audit.reject_mutation();

CREATE TRIGGER a_guard_rewinding_export_package_child
  BEFORE INSERT OR UPDATE OR DELETE ON vinto_txn.rewinding_export_package_child
  FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_rewinding_export_package_child_v2();
CREATE TRIGGER z_touch_rewinding_export_package_child
  BEFORE INSERT OR UPDATE ON vinto_txn.rewinding_export_package_child
  FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();
CREATE TRIGGER audit_rewinding_export_package_child
  AFTER INSERT OR UPDATE ON vinto_txn.rewinding_export_package_child
  FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();
DROP FUNCTION vinto_txn.guard_rewinding_export_package_child();
CREATE TRIGGER reject_rewinding_export_package_child_truncate
  BEFORE TRUNCATE ON vinto_txn.rewinding_export_package_child
  FOR EACH STATEMENT EXECUTE FUNCTION vinto_audit.reject_mutation();

CREATE TRIGGER a_guard_rewinding_export_pdf
  BEFORE INSERT OR UPDATE OR DELETE ON vinto_txn.rewinding_export_pdf
  FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_rewinding_export_pdf();
CREATE TRIGGER reject_rewinding_export_pdf_truncate
  BEFORE TRUNCATE ON vinto_txn.rewinding_export_pdf
  FOR EACH STATEMENT EXECUTE FUNCTION vinto_audit.reject_mutation();

CREATE TRIGGER a_guard_rewinding_export_reservation
  BEFORE INSERT OR UPDATE OR DELETE ON vinto_txn.rewinding_export_reservation
  FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_rewinding_export_reservation();
CREATE TRIGGER audit_rewinding_export_reservation
  AFTER INSERT OR UPDATE ON vinto_txn.rewinding_export_reservation
  FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();
CREATE TRIGGER reject_rewinding_export_reservation_truncate
  BEFORE TRUNCATE ON vinto_txn.rewinding_export_reservation
  FOR EACH STATEMENT EXECUTE FUNCTION vinto_audit.reject_mutation();

CREATE TRIGGER a_guard_rewinding_export_event
  BEFORE INSERT OR UPDATE OR DELETE ON vinto_txn.rewinding_export_report_event
  FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_rewinding_export_event();
CREATE TRIGGER reject_rewinding_export_event_truncate
  BEFORE TRUNCATE ON vinto_txn.rewinding_export_report_event
  FOR EACH STATEMENT EXECUTE FUNCTION vinto_audit.reject_mutation();

-- Cross-table invariants are deferred: generation inserts status, PDF, reservations and events in one transaction.
CREATE CONSTRAINT TRIGGER assert_rewinding_export_report_integrity
  AFTER INSERT OR UPDATE ON vinto_txn.rewinding_export_report
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
  EXECUTE FUNCTION vinto_txn.assert_rewinding_export_integrity();
CREATE CONSTRAINT TRIGGER assert_rewinding_export_package_integrity
  AFTER INSERT OR UPDATE ON vinto_txn.rewinding_export_package
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
  EXECUTE FUNCTION vinto_txn.assert_rewinding_export_integrity();
CREATE CONSTRAINT TRIGGER assert_rewinding_export_package_child_integrity
  AFTER INSERT OR UPDATE ON vinto_txn.rewinding_export_package_child
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
  EXECUTE FUNCTION vinto_txn.assert_rewinding_export_integrity();
CREATE CONSTRAINT TRIGGER assert_rewinding_export_pdf_integrity
  AFTER INSERT ON vinto_txn.rewinding_export_pdf
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
  EXECUTE FUNCTION vinto_txn.assert_rewinding_export_integrity();
CREATE CONSTRAINT TRIGGER assert_rewinding_export_reservation_integrity
  AFTER INSERT OR UPDATE ON vinto_txn.rewinding_export_reservation
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
  EXECUTE FUNCTION vinto_txn.assert_rewinding_export_integrity();

-- PUBLIC receives no privileges. Minimum application grants are added separately in roles/03_table_grants.sql.
REVOKE ALL ON vinto_txn.rewinding_export_work_order_classification,
  vinto_txn.rewinding_export_report,
  vinto_txn.rewinding_export_package,
  vinto_txn.rewinding_export_package_child,
  vinto_txn.rewinding_export_pdf,
  vinto_txn.rewinding_export_reservation,
  vinto_txn.rewinding_export_report_event
FROM PUBLIC;

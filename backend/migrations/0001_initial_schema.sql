-- VINTO initial schema. Authoritative DDL; no business/catalog seed data.

CREATE SCHEMA vinto_master;

CREATE SCHEMA vinto_config;

CREATE SCHEMA vinto_txn;

CREATE SCHEMA vinto_audit;

CREATE TABLE vinto_master."user" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), external_subject text UNIQUE, display_name text NOT NULL, active boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_master."profile" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text NOT NULL UNIQUE, name text NOT NULL, active boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_master."user_profile" (
 user_id uuid NOT NULL, profile_id uuid NOT NULL, PRIMARY KEY (user_id, profile_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_master."sector" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text NOT NULL UNIQUE, name text NOT NULL, active boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_master."machine" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), sector_id uuid NOT NULL, code text NOT NULL UNIQUE, name text NOT NULL, active boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_master."machine_alias" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), machine_id uuid NOT NULL, source text NOT NULL, alias text NOT NULL, UNIQUE (source, alias),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_master."device" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), external_key text NOT NULL UNIQUE, machine_id uuid, active boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_master."unit" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text NOT NULL UNIQUE, label text NOT NULL, active boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_master."material_class" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text NOT NULL UNIQUE, name text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_master."article" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text NOT NULL UNIQUE, is_product boolean NOT NULL DEFAULT false, is_material boolean NOT NULL DEFAULT false, active boolean NOT NULL DEFAULT true, CHECK (is_product OR is_material),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_master."article_version" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), article_id uuid NOT NULL, version_number integer NOT NULL CHECK (version_number > 0), description text NOT NULL, unit_id uuid NOT NULL, material_class_id uuid, nominal_weight_kg numeric CHECK (nominal_weight_kg >= 0), source_batch_id uuid, effective_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE (article_id, version_number), UNIQUE (id, article_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_master."article_machine" (
 article_id uuid NOT NULL, machine_id uuid NOT NULL, PRIMARY KEY (article_id, machine_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_config."shift" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text NOT NULL UNIQUE, name text NOT NULL, active boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_config."shift_schedule" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), shift_id uuid NOT NULL, sector_id uuid NOT NULL, starts_at time NOT NULL, ends_at time NOT NULL, timezone text NOT NULL, valid_from date NOT NULL, valid_to date, CHECK (starts_at <> ends_at), CHECK (valid_to IS NULL OR valid_to >= valid_from), UNIQUE (shift_id, sector_id, valid_from),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_config."workflow_definition" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text NOT NULL UNIQUE, name text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_config."form" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), legacy_key text NOT NULL UNIQUE, code text NOT NULL UNIQUE, legacy_number integer, active boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_config."form_version" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), form_id uuid NOT NULL, version_number integer NOT NULL CHECK (version_number > 0), name text NOT NULL, area text NOT NULL CHECK (area IN ('production','quality')), workflow_id uuid NOT NULL, status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','retired')), definition_checksum text NOT NULL CHECK (definition_checksum ~ '^[a-f0-9]{64}$'), source_batch_id uuid, published_at timestamptz, CHECK ((status = 'draft' AND published_at IS NULL) OR (status IN ('published','retired') AND published_at IS NOT NULL)), UNIQUE (form_id, version_number),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_config."form_version_machine" (
 form_version_id uuid NOT NULL, machine_id uuid NOT NULL, PRIMARY KEY (form_version_id, machine_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_config."field_group" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), form_version_id uuid NOT NULL, code text NOT NULL, label text NOT NULL, display_order integer NOT NULL CHECK (display_order >= 0), repeatable boolean NOT NULL DEFAULT false, min_rows integer NOT NULL DEFAULT 0 CHECK (min_rows >= 0), max_rows integer, CHECK (max_rows IS NULL OR max_rows >= min_rows), UNIQUE (form_version_id, code), UNIQUE (id, form_version_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_config."field_definition" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), form_version_id uuid NOT NULL, field_group_id uuid, legacy_id text, key text NOT NULL, label text NOT NULL, description text NOT NULL DEFAULT '', value_type text NOT NULL CHECK (value_type IN ('text','textarea','decimal','integer','boolean','date','time')), source text NOT NULL CHECK (source IN ('manual','automatic','calculated')), required boolean NOT NULL DEFAULT false, unit_id uuid, classification text, proposal text, needs_validation boolean NOT NULL DEFAULT false, display_order integer NOT NULL CHECK (display_order >= 0), calculation_rule text, UNIQUE NULLS NOT DISTINCT (form_version_id, field_group_id, key), UNIQUE (id, form_version_id), UNIQUE (id, form_version_id, value_type),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_config."field_option" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), form_version_id uuid NOT NULL, field_definition_id uuid NOT NULL, option_key text NOT NULL, label text NOT NULL, display_order integer NOT NULL CHECK (display_order >= 0), UNIQUE (field_definition_id, option_key), UNIQUE (id, form_version_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_config."field_option_dependency" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), form_version_id uuid NOT NULL, parent_option_id uuid NOT NULL, child_option_id uuid NOT NULL, CHECK (parent_option_id <> child_option_id), UNIQUE (parent_option_id, child_option_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_config."workflow_step" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workflow_id uuid NOT NULL, form_version_id uuid NOT NULL, display_order integer NOT NULL CHECK (display_order >= 0), label text NOT NULL, UNIQUE (workflow_id, form_version_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_config."recipe_version" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), article_id uuid NOT NULL, version_number integer NOT NULL CHECK (version_number > 0), status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','retired')), source_batch_id uuid, valid_from date, valid_to date, published_at timestamptz, CHECK (valid_to IS NULL OR valid_from IS NOT NULL AND valid_to >= valid_from), CHECK ((status = 'draft' AND published_at IS NULL) OR (status IN ('published','retired') AND published_at IS NOT NULL)), UNIQUE (article_id, version_number), UNIQUE (id, article_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_config."recipe_component" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), recipe_version_id uuid NOT NULL, article_version_id uuid NOT NULL, unit_id uuid NOT NULL, standard_quantity numeric NOT NULL CHECK (standard_quantity >= 0), usage text NOT NULL, display_order integer NOT NULL CHECK (display_order >= 0), UNIQUE (recipe_version_id, display_order), UNIQUE (id, recipe_version_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_config."report_definition" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), legacy_key text NOT NULL UNIQUE, name text NOT NULL, source_description text NOT NULL, description text NOT NULL, active boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_txn."work_order" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), number text NOT NULL UNIQUE, machine_id uuid NOT NULL, status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','in_progress','closed')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_txn."work_order_version" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), work_order_id uuid NOT NULL, version_number integer NOT NULL CHECK (version_number > 0), kind text NOT NULL CHECK (kind IN ('baseline','operational')), published_at timestamptz, UNIQUE (work_order_id, version_number),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_txn."work_order_line" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), work_order_version_id uuid NOT NULL, line_code text NOT NULL, pv_reference text NOT NULL, article_version_id uuid NOT NULL, unit_id uuid NOT NULL, quantity numeric NOT NULL CHECK (quantity > 0), due_date date NOT NULL, UNIQUE (work_order_version_id, line_code), UNIQUE (id, article_version_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_txn."assignment" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), work_order_line_id uuid NOT NULL, machine_id uuid NOT NULL, shift_schedule_id uuid NOT NULL, operating_date date NOT NULL, status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','finished')), assigned_by uuid NOT NULL, finished_at timestamptz, CHECK ((status = 'active' AND finished_at IS NULL) OR (status = 'finished' AND finished_at IS NOT NULL)), UNIQUE (id, machine_id, shift_schedule_id, operating_date),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_txn."capture" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), form_version_id uuid NOT NULL, machine_id uuid NOT NULL, shift_schedule_id uuid NOT NULL, device_id uuid NOT NULL, assignment_id uuid, operating_date date NOT NULL, status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','submitted','blocked','closed')), revision integer NOT NULL DEFAULT 1 CHECK (revision > 0), captured_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT clock_timestamp(), submitted_at timestamptz, closed_at timestamptz, recipe_version_id uuid, correction_reason text, CHECK (status NOT IN ('submitted','closed') OR submitted_at IS NOT NULL), CHECK ((status = 'closed') = (closed_at IS NOT NULL)), CHECK (closed_at IS NULL OR closed_at >= submitted_at), UNIQUE (id, form_version_id), UNIQUE (id, recipe_version_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_txn."capture_group_row" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), capture_id uuid NOT NULL, form_version_id uuid NOT NULL, field_group_id uuid NOT NULL, row_number integer NOT NULL CHECK (row_number > 0), article_version_id uuid, recipe_version_id uuid, recipe_component_id uuid, CHECK (recipe_component_id IS NULL OR recipe_version_id IS NOT NULL), UNIQUE (capture_id, field_group_id, row_number), UNIQUE (id, capture_id, form_version_id, field_group_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_txn."capture_detail" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), capture_id uuid NOT NULL, form_version_id uuid NOT NULL, field_definition_id uuid NOT NULL, field_group_id uuid, group_row_id uuid, value_type text NOT NULL, value_text text, value_decimal numeric, value_integer bigint, value_boolean boolean, value_date date, value_time time, CHECK ((field_group_id IS NULL) = (group_row_id IS NULL)), CHECK (num_nonnulls(value_text,value_decimal,value_integer,value_boolean,value_date,value_time) = 1), CHECK ((value_type IN ('text','textarea') AND value_text IS NOT NULL) OR (value_type = 'decimal' AND value_decimal IS NOT NULL) OR (value_type = 'integer' AND value_integer IS NOT NULL) OR (value_type = 'boolean' AND value_boolean IS NOT NULL) OR (value_type = 'date' AND value_date IS NOT NULL) OR (value_type = 'time' AND value_time IS NOT NULL)), UNIQUE NULLS NOT DISTINCT (capture_id, field_definition_id, group_row_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_txn."bobbin" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text NOT NULL UNIQUE, source_capture_id uuid, article_version_id uuid, weight_kg numeric CHECK (weight_kg >= 0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_txn."bobbin_relation" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), mother_bobbin_id uuid NOT NULL, daughter_bobbin_id uuid NOT NULL, capture_id uuid NOT NULL, CHECK (mother_bobbin_id <> daughter_bobbin_id), UNIQUE (mother_bobbin_id, daughter_bobbin_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_txn."quality_release" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), bobbin_id uuid NOT NULL UNIQUE, status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','released','rejected')), decided_by uuid, decided_at timestamptz, decision_reason text, CHECK ((status = 'pending' AND decided_by IS NULL AND decided_at IS NULL) OR (status IN ('released','rejected') AND decided_by IS NOT NULL AND decided_at IS NOT NULL)),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid,
 updated_by uuid
);

CREATE TABLE vinto_audit."import_batch" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source text NOT NULL, source_checksum text NOT NULL CHECK (source_checksum ~ '^[a-f0-9]{64}$'), status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','completed','failed')), imported_at timestamptz NOT NULL DEFAULT clock_timestamp(), completed_at timestamptz, imported_by uuid, summary jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE vinto_audit."import_record" (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), batch_id uuid NOT NULL, source_key text NOT NULL, raw_payload jsonb NOT NULL, target_schema text, target_table text, target_id uuid, status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','unresolved','rejected')), issues jsonb NOT NULL DEFAULT '[]'::jsonb, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE (batch_id, source_key)
);

CREATE TABLE vinto_audit."audit_event" (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, entity_schema text NOT NULL, entity_table text NOT NULL, entity_key jsonb NOT NULL, action text NOT NULL CHECK (action IN ('INSERT','UPDATE','DELETE')), actor_id uuid, database_actor text NOT NULL, occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(), request_id text, reason text, old_data jsonb, new_data jsonb
);

ALTER TABLE vinto_master."user_profile" ADD CONSTRAINT "user_profile_c6fb3f1944_fk" FOREIGN KEY (user_id) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."user_profile" ADD CONSTRAINT "user_profile_31fee0f720_fk" FOREIGN KEY (profile_id) REFERENCES vinto_master."profile" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."machine" ADD CONSTRAINT "machine_67047c7b2e_fk" FOREIGN KEY (sector_id) REFERENCES vinto_master."sector" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."machine_alias" ADD CONSTRAINT "machine_alias_588e409014_fk" FOREIGN KEY (machine_id) REFERENCES vinto_master."machine" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."device" ADD CONSTRAINT "device_588e409014_fk" FOREIGN KEY (machine_id) REFERENCES vinto_master."machine" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."article_version" ADD CONSTRAINT "article_version_042ff47ae5_fk" FOREIGN KEY (article_id) REFERENCES vinto_master."article" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."article_version" ADD CONSTRAINT "article_version_9e35e6473d_fk" FOREIGN KEY (unit_id) REFERENCES vinto_master."unit" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."article_version" ADD CONSTRAINT "article_version_a98e92fcc7_fk" FOREIGN KEY (material_class_id) REFERENCES vinto_master."material_class" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."article_machine" ADD CONSTRAINT "article_machine_042ff47ae5_fk" FOREIGN KEY (article_id) REFERENCES vinto_master."article" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."article_machine" ADD CONSTRAINT "article_machine_588e409014_fk" FOREIGN KEY (machine_id) REFERENCES vinto_master."machine" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."article_version" ADD CONSTRAINT "article_version_df9e2fd663_fk" FOREIGN KEY (source_batch_id) REFERENCES vinto_audit."import_batch" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."shift_schedule" ADD CONSTRAINT "shift_schedule_a1d8ac2685_fk" FOREIGN KEY (shift_id) REFERENCES vinto_config."shift" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."shift_schedule" ADD CONSTRAINT "shift_schedule_67047c7b2e_fk" FOREIGN KEY (sector_id) REFERENCES vinto_master."sector" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."form_version" ADD CONSTRAINT "form_version_50f772d639_fk" FOREIGN KEY (form_id) REFERENCES vinto_config."form" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."form_version" ADD CONSTRAINT "form_version_6bc44b2ace_fk" FOREIGN KEY (workflow_id) REFERENCES vinto_config."workflow_definition" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."form_version" ADD CONSTRAINT "form_version_df9e2fd663_fk" FOREIGN KEY (source_batch_id) REFERENCES vinto_audit."import_batch" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."form_version_machine" ADD CONSTRAINT "form_version_machine_0e0d170a03_fk" FOREIGN KEY (form_version_id) REFERENCES vinto_config."form_version" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."form_version_machine" ADD CONSTRAINT "form_version_machine_588e409014_fk" FOREIGN KEY (machine_id) REFERENCES vinto_master."machine" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_group" ADD CONSTRAINT "field_group_0e0d170a03_fk" FOREIGN KEY (form_version_id) REFERENCES vinto_config."form_version" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_definition" ADD CONSTRAINT "field_definition_0e0d170a03_fk" FOREIGN KEY (form_version_id) REFERENCES vinto_config."form_version" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_definition" ADD CONSTRAINT "field_definition_9e35e6473d_fk" FOREIGN KEY (unit_id) REFERENCES vinto_master."unit" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_option" ADD CONSTRAINT "field_option_0e0d170a03_fk" FOREIGN KEY (form_version_id) REFERENCES vinto_config."form_version" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_option_dependency" ADD CONSTRAINT "field_option_dependency_0e0d170a03_fk" FOREIGN KEY (form_version_id) REFERENCES vinto_config."form_version" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."workflow_step" ADD CONSTRAINT "workflow_step_6bc44b2ace_fk" FOREIGN KEY (workflow_id) REFERENCES vinto_config."workflow_definition" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."workflow_step" ADD CONSTRAINT "workflow_step_0e0d170a03_fk" FOREIGN KEY (form_version_id) REFERENCES vinto_config."form_version" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."recipe_version" ADD CONSTRAINT "recipe_version_042ff47ae5_fk" FOREIGN KEY (article_id) REFERENCES vinto_master."article" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."recipe_version" ADD CONSTRAINT "recipe_version_df9e2fd663_fk" FOREIGN KEY (source_batch_id) REFERENCES vinto_audit."import_batch" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."recipe_component" ADD CONSTRAINT "recipe_component_b72f13db8e_fk" FOREIGN KEY (recipe_version_id) REFERENCES vinto_config."recipe_version" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."recipe_component" ADD CONSTRAINT "recipe_component_7fe54dfadb_fk" FOREIGN KEY (article_version_id) REFERENCES vinto_master."article_version" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."recipe_component" ADD CONSTRAINT "recipe_component_9e35e6473d_fk" FOREIGN KEY (unit_id) REFERENCES vinto_master."unit" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_definition" ADD CONSTRAINT "field_definition_2d55fc953e_fk" FOREIGN KEY (field_group_id, form_version_id) REFERENCES vinto_config."field_group" (id, form_version_id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_option" ADD CONSTRAINT "field_option_c49289262e_fk" FOREIGN KEY (field_definition_id, form_version_id) REFERENCES vinto_config."field_definition" (id, form_version_id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_option_dependency" ADD CONSTRAINT "field_option_dependency_78ecebaec2_fk" FOREIGN KEY (parent_option_id, form_version_id) REFERENCES vinto_config."field_option" (id, form_version_id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_option_dependency" ADD CONSTRAINT "field_option_dependency_7aad456cd7_fk" FOREIGN KEY (child_option_id, form_version_id) REFERENCES vinto_config."field_option" (id, form_version_id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."work_order" ADD CONSTRAINT "work_order_588e409014_fk" FOREIGN KEY (machine_id) REFERENCES vinto_master."machine" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."work_order_version" ADD CONSTRAINT "work_order_version_56022c89f7_fk" FOREIGN KEY (work_order_id) REFERENCES vinto_txn."work_order" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."work_order_line" ADD CONSTRAINT "work_order_line_28445554f1_fk" FOREIGN KEY (work_order_version_id) REFERENCES vinto_txn."work_order_version" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."work_order_line" ADD CONSTRAINT "work_order_line_7fe54dfadb_fk" FOREIGN KEY (article_version_id) REFERENCES vinto_master."article_version" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."work_order_line" ADD CONSTRAINT "work_order_line_9e35e6473d_fk" FOREIGN KEY (unit_id) REFERENCES vinto_master."unit" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."assignment" ADD CONSTRAINT "assignment_9afbf662e2_fk" FOREIGN KEY (work_order_line_id) REFERENCES vinto_txn."work_order_line" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."assignment" ADD CONSTRAINT "assignment_588e409014_fk" FOREIGN KEY (machine_id) REFERENCES vinto_master."machine" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."assignment" ADD CONSTRAINT "assignment_b949a4186e_fk" FOREIGN KEY (shift_schedule_id) REFERENCES vinto_config."shift_schedule" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."assignment" ADD CONSTRAINT "assignment_d1d061c10d_fk" FOREIGN KEY (assigned_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture" ADD CONSTRAINT "capture_0e0d170a03_fk" FOREIGN KEY (form_version_id) REFERENCES vinto_config."form_version" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture" ADD CONSTRAINT "capture_588e409014_fk" FOREIGN KEY (machine_id) REFERENCES vinto_master."machine" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture" ADD CONSTRAINT "capture_b949a4186e_fk" FOREIGN KEY (shift_schedule_id) REFERENCES vinto_config."shift_schedule" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture" ADD CONSTRAINT "capture_d1898ff342_fk" FOREIGN KEY (device_id) REFERENCES vinto_master."device" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture" ADD CONSTRAINT "capture_b72f13db8e_fk" FOREIGN KEY (recipe_version_id) REFERENCES vinto_config."recipe_version" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture_group_row" ADD CONSTRAINT "capture_group_row_7fe54dfadb_fk" FOREIGN KEY (article_version_id) REFERENCES vinto_master."article_version" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture_group_row" ADD CONSTRAINT "capture_group_row_b72f13db8e_fk" FOREIGN KEY (recipe_version_id) REFERENCES vinto_config."recipe_version" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."bobbin" ADD CONSTRAINT "bobbin_efeac91718_fk" FOREIGN KEY (source_capture_id) REFERENCES vinto_txn."capture" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."bobbin" ADD CONSTRAINT "bobbin_7fe54dfadb_fk" FOREIGN KEY (article_version_id) REFERENCES vinto_master."article_version" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."bobbin_relation" ADD CONSTRAINT "bobbin_relation_1c477d1b0f_fk" FOREIGN KEY (mother_bobbin_id) REFERENCES vinto_txn."bobbin" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."bobbin_relation" ADD CONSTRAINT "bobbin_relation_86357b63ec_fk" FOREIGN KEY (daughter_bobbin_id) REFERENCES vinto_txn."bobbin" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."bobbin_relation" ADD CONSTRAINT "bobbin_relation_a4701c6149_fk" FOREIGN KEY (capture_id) REFERENCES vinto_txn."capture" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."quality_release" ADD CONSTRAINT "quality_release_cb02dcc046_fk" FOREIGN KEY (bobbin_id) REFERENCES vinto_txn."bobbin" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."quality_release" ADD CONSTRAINT "quality_release_661b86f65d_fk" FOREIGN KEY (decided_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture" ADD CONSTRAINT "capture_70df6b5091_fk" FOREIGN KEY (assignment_id, machine_id, shift_schedule_id, operating_date) REFERENCES vinto_txn."assignment" (id, machine_id, shift_schedule_id, operating_date) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture_group_row" ADD CONSTRAINT "capture_group_row_5df320299e_fk" FOREIGN KEY (capture_id, form_version_id) REFERENCES vinto_txn."capture" (id, form_version_id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture_group_row" ADD CONSTRAINT "capture_group_row_2d55fc953e_fk" FOREIGN KEY (field_group_id, form_version_id) REFERENCES vinto_config."field_group" (id, form_version_id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture_group_row" ADD CONSTRAINT "capture_group_row_b6d1d2c6d8_fk" FOREIGN KEY (capture_id, recipe_version_id) REFERENCES vinto_txn."capture" (id, recipe_version_id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture_group_row" ADD CONSTRAINT "capture_group_row_6ff3cfa49f_fk" FOREIGN KEY (recipe_component_id, recipe_version_id) REFERENCES vinto_config."recipe_component" (id, recipe_version_id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture_detail" ADD CONSTRAINT "capture_detail_5df320299e_fk" FOREIGN KEY (capture_id, form_version_id) REFERENCES vinto_txn."capture" (id, form_version_id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture_detail" ADD CONSTRAINT "capture_detail_931c53c93e_fk" FOREIGN KEY (field_definition_id, form_version_id, value_type) REFERENCES vinto_config."field_definition" (id, form_version_id, value_type) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture_detail" ADD CONSTRAINT "capture_detail_da07594f62_fk" FOREIGN KEY (group_row_id, capture_id, form_version_id, field_group_id) REFERENCES vinto_txn."capture_group_row" (id, capture_id, form_version_id, field_group_id) ON DELETE RESTRICT;

ALTER TABLE vinto_audit."import_batch" ADD CONSTRAINT "import_batch_365e97575e_fk" FOREIGN KEY (imported_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_audit."import_record" ADD CONSTRAINT "import_record_e2e4f9ca3e_fk" FOREIGN KEY (batch_id) REFERENCES vinto_audit."import_batch" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_audit."audit_event" ADD CONSTRAINT "audit_event_b158513d94_fk" FOREIGN KEY (actor_id) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."user" ADD CONSTRAINT "user_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."user" ADD CONSTRAINT "user_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."profile" ADD CONSTRAINT "profile_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."profile" ADD CONSTRAINT "profile_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."user_profile" ADD CONSTRAINT "user_profile_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."user_profile" ADD CONSTRAINT "user_profile_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."sector" ADD CONSTRAINT "sector_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."sector" ADD CONSTRAINT "sector_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."machine" ADD CONSTRAINT "machine_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."machine" ADD CONSTRAINT "machine_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."machine_alias" ADD CONSTRAINT "machine_alias_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."machine_alias" ADD CONSTRAINT "machine_alias_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."device" ADD CONSTRAINT "device_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."device" ADD CONSTRAINT "device_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."unit" ADD CONSTRAINT "unit_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."unit" ADD CONSTRAINT "unit_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."material_class" ADD CONSTRAINT "material_class_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."material_class" ADD CONSTRAINT "material_class_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."article" ADD CONSTRAINT "article_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."article" ADD CONSTRAINT "article_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."article_version" ADD CONSTRAINT "article_version_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."article_version" ADD CONSTRAINT "article_version_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."article_machine" ADD CONSTRAINT "article_machine_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_master."article_machine" ADD CONSTRAINT "article_machine_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."shift" ADD CONSTRAINT "shift_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."shift" ADD CONSTRAINT "shift_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."shift_schedule" ADD CONSTRAINT "shift_schedule_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."shift_schedule" ADD CONSTRAINT "shift_schedule_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."workflow_definition" ADD CONSTRAINT "workflow_definition_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."workflow_definition" ADD CONSTRAINT "workflow_definition_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."form" ADD CONSTRAINT "form_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."form" ADD CONSTRAINT "form_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."form_version" ADD CONSTRAINT "form_version_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."form_version" ADD CONSTRAINT "form_version_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."form_version_machine" ADD CONSTRAINT "form_version_machine_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."form_version_machine" ADD CONSTRAINT "form_version_machine_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_group" ADD CONSTRAINT "field_group_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_group" ADD CONSTRAINT "field_group_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_definition" ADD CONSTRAINT "field_definition_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_definition" ADD CONSTRAINT "field_definition_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_option" ADD CONSTRAINT "field_option_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_option" ADD CONSTRAINT "field_option_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_option_dependency" ADD CONSTRAINT "field_option_dependency_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."field_option_dependency" ADD CONSTRAINT "field_option_dependency_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."workflow_step" ADD CONSTRAINT "workflow_step_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."workflow_step" ADD CONSTRAINT "workflow_step_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."recipe_version" ADD CONSTRAINT "recipe_version_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."recipe_version" ADD CONSTRAINT "recipe_version_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."recipe_component" ADD CONSTRAINT "recipe_component_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."recipe_component" ADD CONSTRAINT "recipe_component_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."report_definition" ADD CONSTRAINT "report_definition_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_config."report_definition" ADD CONSTRAINT "report_definition_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."work_order" ADD CONSTRAINT "work_order_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."work_order" ADD CONSTRAINT "work_order_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."work_order_version" ADD CONSTRAINT "work_order_version_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."work_order_version" ADD CONSTRAINT "work_order_version_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."work_order_line" ADD CONSTRAINT "work_order_line_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."work_order_line" ADD CONSTRAINT "work_order_line_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."assignment" ADD CONSTRAINT "assignment_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."assignment" ADD CONSTRAINT "assignment_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture" ADD CONSTRAINT "capture_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture" ADD CONSTRAINT "capture_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture_group_row" ADD CONSTRAINT "capture_group_row_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture_group_row" ADD CONSTRAINT "capture_group_row_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture_detail" ADD CONSTRAINT "capture_detail_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."capture_detail" ADD CONSTRAINT "capture_detail_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."bobbin" ADD CONSTRAINT "bobbin_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."bobbin" ADD CONSTRAINT "bobbin_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."bobbin_relation" ADD CONSTRAINT "bobbin_relation_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."bobbin_relation" ADD CONSTRAINT "bobbin_relation_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."quality_release" ADD CONSTRAINT "quality_release_30c2008cb6_fk" FOREIGN KEY (created_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

ALTER TABLE vinto_txn."quality_release" ADD CONSTRAINT "quality_release_7d4d41de86_fk" FOREIGN KEY (updated_by) REFERENCES vinto_master."user" (id) ON DELETE RESTRICT;

CREATE INDEX "user_profile_c6fb3f1944_fk_idx" ON vinto_master."user_profile" (user_id);

CREATE INDEX "user_profile_31fee0f720_fk_idx" ON vinto_master."user_profile" (profile_id);

CREATE INDEX "machine_67047c7b2e_fk_idx" ON vinto_master."machine" (sector_id);

CREATE INDEX "machine_alias_588e409014_fk_idx" ON vinto_master."machine_alias" (machine_id);

CREATE INDEX "device_588e409014_fk_idx" ON vinto_master."device" (machine_id);

CREATE INDEX "article_version_042ff47ae5_fk_idx" ON vinto_master."article_version" (article_id);

CREATE INDEX "article_version_9e35e6473d_fk_idx" ON vinto_master."article_version" (unit_id);

CREATE INDEX "article_version_a98e92fcc7_fk_idx" ON vinto_master."article_version" (material_class_id);

CREATE INDEX "article_machine_042ff47ae5_fk_idx" ON vinto_master."article_machine" (article_id);

CREATE INDEX "article_machine_588e409014_fk_idx" ON vinto_master."article_machine" (machine_id);

CREATE INDEX "article_version_df9e2fd663_fk_idx" ON vinto_master."article_version" (source_batch_id);

CREATE INDEX "shift_schedule_a1d8ac2685_fk_idx" ON vinto_config."shift_schedule" (shift_id);

CREATE INDEX "shift_schedule_67047c7b2e_fk_idx" ON vinto_config."shift_schedule" (sector_id);

CREATE INDEX "form_version_50f772d639_fk_idx" ON vinto_config."form_version" (form_id);

CREATE INDEX "form_version_6bc44b2ace_fk_idx" ON vinto_config."form_version" (workflow_id);

CREATE INDEX "form_version_df9e2fd663_fk_idx" ON vinto_config."form_version" (source_batch_id);

CREATE INDEX "form_version_machine_0e0d170a03_fk_idx" ON vinto_config."form_version_machine" (form_version_id);

CREATE INDEX "form_version_machine_588e409014_fk_idx" ON vinto_config."form_version_machine" (machine_id);

CREATE INDEX "field_group_0e0d170a03_fk_idx" ON vinto_config."field_group" (form_version_id);

CREATE INDEX "field_definition_0e0d170a03_fk_idx" ON vinto_config."field_definition" (form_version_id);

CREATE INDEX "field_definition_9e35e6473d_fk_idx" ON vinto_config."field_definition" (unit_id);

CREATE INDEX "field_option_0e0d170a03_fk_idx" ON vinto_config."field_option" (form_version_id);

CREATE INDEX "field_option_dependency_0e0d170a03_fk_idx" ON vinto_config."field_option_dependency" (form_version_id);

CREATE INDEX "workflow_step_6bc44b2ace_fk_idx" ON vinto_config."workflow_step" (workflow_id);

CREATE INDEX "workflow_step_0e0d170a03_fk_idx" ON vinto_config."workflow_step" (form_version_id);

CREATE INDEX "recipe_version_042ff47ae5_fk_idx" ON vinto_config."recipe_version" (article_id);

CREATE INDEX "recipe_version_df9e2fd663_fk_idx" ON vinto_config."recipe_version" (source_batch_id);

CREATE INDEX "recipe_component_b72f13db8e_fk_idx" ON vinto_config."recipe_component" (recipe_version_id);

CREATE INDEX "recipe_component_7fe54dfadb_fk_idx" ON vinto_config."recipe_component" (article_version_id);

CREATE INDEX "recipe_component_9e35e6473d_fk_idx" ON vinto_config."recipe_component" (unit_id);

CREATE INDEX "field_definition_2d55fc953e_fk_idx" ON vinto_config."field_definition" (field_group_id, form_version_id);

CREATE INDEX "field_option_c49289262e_fk_idx" ON vinto_config."field_option" (field_definition_id, form_version_id);

CREATE INDEX "field_option_dependency_78ecebaec2_fk_idx" ON vinto_config."field_option_dependency" (parent_option_id, form_version_id);

CREATE INDEX "field_option_dependency_7aad456cd7_fk_idx" ON vinto_config."field_option_dependency" (child_option_id, form_version_id);

CREATE INDEX "work_order_588e409014_fk_idx" ON vinto_txn."work_order" (machine_id);

CREATE INDEX "work_order_version_56022c89f7_fk_idx" ON vinto_txn."work_order_version" (work_order_id);

CREATE INDEX "work_order_line_28445554f1_fk_idx" ON vinto_txn."work_order_line" (work_order_version_id);

CREATE INDEX "work_order_line_7fe54dfadb_fk_idx" ON vinto_txn."work_order_line" (article_version_id);

CREATE INDEX "work_order_line_9e35e6473d_fk_idx" ON vinto_txn."work_order_line" (unit_id);

CREATE INDEX "assignment_9afbf662e2_fk_idx" ON vinto_txn."assignment" (work_order_line_id);

CREATE INDEX "assignment_588e409014_fk_idx" ON vinto_txn."assignment" (machine_id);

CREATE INDEX "assignment_b949a4186e_fk_idx" ON vinto_txn."assignment" (shift_schedule_id);

CREATE INDEX "assignment_d1d061c10d_fk_idx" ON vinto_txn."assignment" (assigned_by);

CREATE INDEX "capture_0e0d170a03_fk_idx" ON vinto_txn."capture" (form_version_id);

CREATE INDEX "capture_588e409014_fk_idx" ON vinto_txn."capture" (machine_id);

CREATE INDEX "capture_b949a4186e_fk_idx" ON vinto_txn."capture" (shift_schedule_id);

CREATE INDEX "capture_d1898ff342_fk_idx" ON vinto_txn."capture" (device_id);

CREATE INDEX "capture_b72f13db8e_fk_idx" ON vinto_txn."capture" (recipe_version_id);

CREATE INDEX "capture_group_row_7fe54dfadb_fk_idx" ON vinto_txn."capture_group_row" (article_version_id);

CREATE INDEX "capture_group_row_b72f13db8e_fk_idx" ON vinto_txn."capture_group_row" (recipe_version_id);

CREATE INDEX "bobbin_efeac91718_fk_idx" ON vinto_txn."bobbin" (source_capture_id);

CREATE INDEX "bobbin_7fe54dfadb_fk_idx" ON vinto_txn."bobbin" (article_version_id);

CREATE INDEX "bobbin_relation_1c477d1b0f_fk_idx" ON vinto_txn."bobbin_relation" (mother_bobbin_id);

CREATE INDEX "bobbin_relation_86357b63ec_fk_idx" ON vinto_txn."bobbin_relation" (daughter_bobbin_id);

CREATE INDEX "bobbin_relation_a4701c6149_fk_idx" ON vinto_txn."bobbin_relation" (capture_id);

CREATE INDEX "quality_release_cb02dcc046_fk_idx" ON vinto_txn."quality_release" (bobbin_id);

CREATE INDEX "quality_release_661b86f65d_fk_idx" ON vinto_txn."quality_release" (decided_by);

CREATE INDEX "capture_70df6b5091_fk_idx" ON vinto_txn."capture" (assignment_id, machine_id, shift_schedule_id, operating_date);

CREATE INDEX "capture_group_row_5df320299e_fk_idx" ON vinto_txn."capture_group_row" (capture_id, form_version_id);

CREATE INDEX "capture_group_row_2d55fc953e_fk_idx" ON vinto_txn."capture_group_row" (field_group_id, form_version_id);

CREATE INDEX "capture_group_row_b6d1d2c6d8_fk_idx" ON vinto_txn."capture_group_row" (capture_id, recipe_version_id);

CREATE INDEX "capture_group_row_6ff3cfa49f_fk_idx" ON vinto_txn."capture_group_row" (recipe_component_id, recipe_version_id);

CREATE INDEX "capture_detail_5df320299e_fk_idx" ON vinto_txn."capture_detail" (capture_id, form_version_id);

CREATE INDEX "capture_detail_931c53c93e_fk_idx" ON vinto_txn."capture_detail" (field_definition_id, form_version_id, value_type);

CREATE INDEX "capture_detail_da07594f62_fk_idx" ON vinto_txn."capture_detail" (group_row_id, capture_id, form_version_id, field_group_id);

CREATE UNIQUE INDEX assignment_one_active_machine ON vinto_txn.assignment (machine_id) WHERE status = 'active';

CREATE INDEX capture_machine_date_idx ON vinto_txn.capture (machine_id, operating_date);

CREATE INDEX capture_status_date_idx ON vinto_txn.capture (status, operating_date);

CREATE INDEX "import_batch_365e97575e_fk_idx" ON vinto_audit."import_batch" (imported_by);

CREATE INDEX "import_record_e2e4f9ca3e_fk_idx" ON vinto_audit."import_record" (batch_id);

CREATE INDEX "audit_event_b158513d94_fk_idx" ON vinto_audit."audit_event" (actor_id);

CREATE INDEX audit_entity_time_idx ON vinto_audit.audit_event (entity_schema, entity_table, occurred_at);

CREATE INDEX "user_30c2008cb6_fk_idx" ON vinto_master."user" (created_by);

CREATE INDEX "user_7d4d41de86_fk_idx" ON vinto_master."user" (updated_by);

CREATE INDEX "profile_30c2008cb6_fk_idx" ON vinto_master."profile" (created_by);

CREATE INDEX "profile_7d4d41de86_fk_idx" ON vinto_master."profile" (updated_by);

CREATE INDEX "user_profile_30c2008cb6_fk_idx" ON vinto_master."user_profile" (created_by);

CREATE INDEX "user_profile_7d4d41de86_fk_idx" ON vinto_master."user_profile" (updated_by);

CREATE INDEX "sector_30c2008cb6_fk_idx" ON vinto_master."sector" (created_by);

CREATE INDEX "sector_7d4d41de86_fk_idx" ON vinto_master."sector" (updated_by);

CREATE INDEX "machine_30c2008cb6_fk_idx" ON vinto_master."machine" (created_by);

CREATE INDEX "machine_7d4d41de86_fk_idx" ON vinto_master."machine" (updated_by);

CREATE INDEX "machine_alias_30c2008cb6_fk_idx" ON vinto_master."machine_alias" (created_by);

CREATE INDEX "machine_alias_7d4d41de86_fk_idx" ON vinto_master."machine_alias" (updated_by);

CREATE INDEX "device_30c2008cb6_fk_idx" ON vinto_master."device" (created_by);

CREATE INDEX "device_7d4d41de86_fk_idx" ON vinto_master."device" (updated_by);

CREATE INDEX "unit_30c2008cb6_fk_idx" ON vinto_master."unit" (created_by);

CREATE INDEX "unit_7d4d41de86_fk_idx" ON vinto_master."unit" (updated_by);

CREATE INDEX "material_class_30c2008cb6_fk_idx" ON vinto_master."material_class" (created_by);

CREATE INDEX "material_class_7d4d41de86_fk_idx" ON vinto_master."material_class" (updated_by);

CREATE INDEX "article_30c2008cb6_fk_idx" ON vinto_master."article" (created_by);

CREATE INDEX "article_7d4d41de86_fk_idx" ON vinto_master."article" (updated_by);

CREATE INDEX "article_version_30c2008cb6_fk_idx" ON vinto_master."article_version" (created_by);

CREATE INDEX "article_version_7d4d41de86_fk_idx" ON vinto_master."article_version" (updated_by);

CREATE INDEX "article_machine_30c2008cb6_fk_idx" ON vinto_master."article_machine" (created_by);

CREATE INDEX "article_machine_7d4d41de86_fk_idx" ON vinto_master."article_machine" (updated_by);

CREATE INDEX "shift_30c2008cb6_fk_idx" ON vinto_config."shift" (created_by);

CREATE INDEX "shift_7d4d41de86_fk_idx" ON vinto_config."shift" (updated_by);

CREATE INDEX "shift_schedule_30c2008cb6_fk_idx" ON vinto_config."shift_schedule" (created_by);

CREATE INDEX "shift_schedule_7d4d41de86_fk_idx" ON vinto_config."shift_schedule" (updated_by);

CREATE INDEX "workflow_definition_30c2008cb6_fk_idx" ON vinto_config."workflow_definition" (created_by);

CREATE INDEX "workflow_definition_7d4d41de86_fk_idx" ON vinto_config."workflow_definition" (updated_by);

CREATE INDEX "form_30c2008cb6_fk_idx" ON vinto_config."form" (created_by);

CREATE INDEX "form_7d4d41de86_fk_idx" ON vinto_config."form" (updated_by);

CREATE INDEX "form_version_30c2008cb6_fk_idx" ON vinto_config."form_version" (created_by);

CREATE INDEX "form_version_7d4d41de86_fk_idx" ON vinto_config."form_version" (updated_by);

CREATE INDEX "form_version_machine_30c2008cb6_fk_idx" ON vinto_config."form_version_machine" (created_by);

CREATE INDEX "form_version_machine_7d4d41de86_fk_idx" ON vinto_config."form_version_machine" (updated_by);

CREATE INDEX "field_group_30c2008cb6_fk_idx" ON vinto_config."field_group" (created_by);

CREATE INDEX "field_group_7d4d41de86_fk_idx" ON vinto_config."field_group" (updated_by);

CREATE INDEX "field_definition_30c2008cb6_fk_idx" ON vinto_config."field_definition" (created_by);

CREATE INDEX "field_definition_7d4d41de86_fk_idx" ON vinto_config."field_definition" (updated_by);

CREATE INDEX "field_option_30c2008cb6_fk_idx" ON vinto_config."field_option" (created_by);

CREATE INDEX "field_option_7d4d41de86_fk_idx" ON vinto_config."field_option" (updated_by);

CREATE INDEX "field_option_dependency_30c2008cb6_fk_idx" ON vinto_config."field_option_dependency" (created_by);

CREATE INDEX "field_option_dependency_7d4d41de86_fk_idx" ON vinto_config."field_option_dependency" (updated_by);

CREATE INDEX "workflow_step_30c2008cb6_fk_idx" ON vinto_config."workflow_step" (created_by);

CREATE INDEX "workflow_step_7d4d41de86_fk_idx" ON vinto_config."workflow_step" (updated_by);

CREATE INDEX "recipe_version_30c2008cb6_fk_idx" ON vinto_config."recipe_version" (created_by);

CREATE INDEX "recipe_version_7d4d41de86_fk_idx" ON vinto_config."recipe_version" (updated_by);

CREATE INDEX "recipe_component_30c2008cb6_fk_idx" ON vinto_config."recipe_component" (created_by);

CREATE INDEX "recipe_component_7d4d41de86_fk_idx" ON vinto_config."recipe_component" (updated_by);

CREATE INDEX "report_definition_30c2008cb6_fk_idx" ON vinto_config."report_definition" (created_by);

CREATE INDEX "report_definition_7d4d41de86_fk_idx" ON vinto_config."report_definition" (updated_by);

CREATE INDEX "work_order_30c2008cb6_fk_idx" ON vinto_txn."work_order" (created_by);

CREATE INDEX "work_order_7d4d41de86_fk_idx" ON vinto_txn."work_order" (updated_by);

CREATE INDEX "work_order_version_30c2008cb6_fk_idx" ON vinto_txn."work_order_version" (created_by);

CREATE INDEX "work_order_version_7d4d41de86_fk_idx" ON vinto_txn."work_order_version" (updated_by);

CREATE INDEX "work_order_line_30c2008cb6_fk_idx" ON vinto_txn."work_order_line" (created_by);

CREATE INDEX "work_order_line_7d4d41de86_fk_idx" ON vinto_txn."work_order_line" (updated_by);

CREATE INDEX "assignment_30c2008cb6_fk_idx" ON vinto_txn."assignment" (created_by);

CREATE INDEX "assignment_7d4d41de86_fk_idx" ON vinto_txn."assignment" (updated_by);

CREATE INDEX "capture_30c2008cb6_fk_idx" ON vinto_txn."capture" (created_by);

CREATE INDEX "capture_7d4d41de86_fk_idx" ON vinto_txn."capture" (updated_by);

CREATE INDEX "capture_group_row_30c2008cb6_fk_idx" ON vinto_txn."capture_group_row" (created_by);

CREATE INDEX "capture_group_row_7d4d41de86_fk_idx" ON vinto_txn."capture_group_row" (updated_by);

CREATE INDEX "capture_detail_30c2008cb6_fk_idx" ON vinto_txn."capture_detail" (created_by);

CREATE INDEX "capture_detail_7d4d41de86_fk_idx" ON vinto_txn."capture_detail" (updated_by);

CREATE INDEX "bobbin_30c2008cb6_fk_idx" ON vinto_txn."bobbin" (created_by);

CREATE INDEX "bobbin_7d4d41de86_fk_idx" ON vinto_txn."bobbin" (updated_by);

CREATE INDEX "bobbin_relation_30c2008cb6_fk_idx" ON vinto_txn."bobbin_relation" (created_by);

CREATE INDEX "bobbin_relation_7d4d41de86_fk_idx" ON vinto_txn."bobbin_relation" (updated_by);

CREATE INDEX "quality_release_30c2008cb6_fk_idx" ON vinto_txn."quality_release" (created_by);

CREATE INDEX "quality_release_7d4d41de86_fk_idx" ON vinto_txn."quality_release" (updated_by);


-- Context is supplied by the backend with SET LOCAL inside each business transaction.
-- No secrets/tokens/passwords belong in these business tables or audit payloads.
CREATE FUNCTION vinto_audit.touch_row() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor uuid := nullif(current_setting('vinto.actor_id', true), '')::uuid;
BEGIN
 IF TG_OP = 'INSERT' THEN
   NEW.created_at := clock_timestamp();
   NEW.updated_at := NEW.created_at;
   IF actor IS NOT NULL THEN NEW.created_by := actor; NEW.updated_by := actor; END IF;
 ELSE
   NEW.created_at := OLD.created_at;
   NEW.created_by := OLD.created_by;
   NEW.updated_at := clock_timestamp();
   IF actor IS NOT NULL THEN NEW.updated_by := actor; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION vinto_audit.record_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE old_value jsonb; new_value jsonb; row_value jsonb; row_key jsonb;
BEGIN
 IF TG_OP <> 'INSERT' THEN old_value := to_jsonb(OLD); END IF;
 IF TG_OP <> 'DELETE' THEN new_value := to_jsonb(NEW); END IF;
 row_value := coalesce(new_value, old_value);
 SELECT jsonb_object_agg(att.attname, row_value -> att.attname) INTO row_key
 FROM pg_index idx
 JOIN pg_attribute att ON att.attrelid = idx.indrelid AND att.attnum = ANY(idx.indkey)
 WHERE idx.indrelid = TG_RELID AND idx.indisprimary;
 INSERT INTO vinto_audit.audit_event (entity_schema,entity_table,entity_key,action,actor_id,database_actor,request_id,reason,old_data,new_data)
 VALUES (TG_TABLE_SCHEMA,TG_TABLE_NAME,row_key,TG_OP,
 nullif(current_setting('vinto.actor_id',true),'')::uuid,session_user,
 nullif(current_setting('vinto.request_id',true),''),nullif(current_setting('vinto.reason',true),''),old_value,new_value);
 IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION vinto_audit.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Immutable history: %.%', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = '23514';
END $$;

CREATE FUNCTION vinto_config.guard_published_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.status IN ('published','retired') THEN
   IF TG_OP = 'UPDATE' AND OLD.status = 'published' AND NEW.status = 'retired'
     AND (to_jsonb(NEW) - ARRAY['status','updated_at','updated_by']) = (to_jsonb(OLD) - ARRAY['status','updated_at','updated_by']) THEN
       RETURN NEW;
   END IF;
   RAISE EXCEPTION 'Published version is immutable' USING ERRCODE = '23514';
 END IF;
 IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION vinto_config.guard_form_child() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version_id uuid; old_version_id uuid;
BEGIN
 IF TG_OP <> 'DELETE' THEN version_id := NEW.form_version_id; END IF;
 IF TG_OP <> 'INSERT' THEN old_version_id := OLD.form_version_id; END IF;
 IF EXISTS (SELECT 1 FROM vinto_config.form_version WHERE id IN (version_id,old_version_id) AND status <> 'draft') THEN
   RAISE EXCEPTION 'Published form definition is immutable' USING ERRCODE = '23514';
 END IF;
 IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION vinto_config.guard_recipe_child() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version_id uuid; old_version_id uuid;
BEGIN
 IF TG_OP <> 'DELETE' THEN version_id := NEW.recipe_version_id; END IF;
 IF TG_OP <> 'INSERT' THEN old_version_id := OLD.recipe_version_id; END IF;
 IF EXISTS (SELECT 1 FROM vinto_config.recipe_version WHERE id IN (version_id,old_version_id) AND status <> 'draft') THEN
   RAISE EXCEPTION 'Published recipe is immutable' USING ERRCODE = '23514';
 END IF;
 IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION vinto_txn.guard_order_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.published_at IS NOT NULL THEN
   RAISE EXCEPTION 'Published order version is immutable' USING ERRCODE = '23514';
 END IF;
 IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION vinto_txn.guard_order_line() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version_id uuid; old_version_id uuid;
BEGIN
 IF TG_OP <> 'DELETE' THEN version_id := NEW.work_order_version_id; END IF;
 IF TG_OP <> 'INSERT' THEN old_version_id := OLD.work_order_version_id; END IF;
 IF EXISTS (SELECT 1 FROM vinto_txn.work_order_version WHERE id IN (version_id,old_version_id) AND published_at IS NOT NULL) THEN
   RAISE EXCEPTION 'Published order lines are immutable' USING ERRCODE = '23514';
 END IF;
 IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION vinto_txn.validate_assignment() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE machine_sector uuid; assigned_machine uuid;
BEGIN
 SELECT wo.machine_id INTO assigned_machine FROM vinto_txn.work_order_line line
 JOIN vinto_txn.work_order_version version ON version.id = line.work_order_version_id
 JOIN vinto_txn.work_order wo ON wo.id = version.work_order_id WHERE line.id = NEW.work_order_line_id;
 SELECT sector_id INTO machine_sector FROM vinto_master.machine WHERE id = NEW.machine_id;
 IF assigned_machine IS DISTINCT FROM NEW.machine_id OR NOT EXISTS
   (SELECT 1 FROM vinto_config.shift_schedule WHERE id = NEW.shift_schedule_id AND sector_id = machine_sector
    AND NEW.operating_date >= valid_from AND (valid_to IS NULL OR NEW.operating_date <= valid_to)) THEN
   RAISE EXCEPTION 'Assignment machine/shift mismatch' USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION vinto_txn.validate_capture() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE machine_sector uuid; device_machine uuid;
BEGIN
 IF TG_OP = 'UPDATE' THEN
   IF OLD.status = 'closed' THEN RAISE EXCEPTION 'Closed capture is immutable' USING ERRCODE = '23514'; END IF;
   IF NEW.form_version_id <> OLD.form_version_id OR NEW.machine_id <> OLD.machine_id
     OR NEW.shift_schedule_id <> OLD.shift_schedule_id OR NEW.device_id <> OLD.device_id
     OR NEW.assignment_id IS DISTINCT FROM OLD.assignment_id OR NEW.operating_date <> OLD.operating_date
     OR NEW.recipe_version_id IS DISTINCT FROM OLD.recipe_version_id THEN
       RAISE EXCEPTION 'Capture context is immutable; create a new capture' USING ERRCODE = '23514';
   END IF;
   IF OLD.status <> 'draft' AND (nullif(NEW.correction_reason,'') IS NULL
     OR nullif(current_setting('vinto.reason',true),'') IS NULL) THEN
       RAISE EXCEPTION 'Capture correction requires an audited reason' USING ERRCODE = '23514';
   END IF;
   NEW.revision := OLD.revision + 1;
 ELSE NEW.revision := 1;
 END IF;
 IF NOT EXISTS (SELECT 1 FROM vinto_config.form_version WHERE id = NEW.form_version_id
   AND (status = 'published' OR TG_OP = 'UPDATE' AND status = 'retired')) THEN
   RAISE EXCEPTION 'Capture requires published form' USING ERRCODE = '23514';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM vinto_config.form_version_machine WHERE form_version_id = NEW.form_version_id AND machine_id = NEW.machine_id) THEN
   RAISE EXCEPTION 'Machine is not allowed for this form version' USING ERRCODE = '23514';
 END IF;
 SELECT sector_id INTO machine_sector FROM vinto_master.machine WHERE id = NEW.machine_id;
 SELECT machine_id INTO device_machine FROM vinto_master.device WHERE id = NEW.device_id;
 IF device_machine IS NOT NULL AND device_machine <> NEW.machine_id THEN
   RAISE EXCEPTION 'Device machine mismatch' USING ERRCODE = '23514';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM vinto_config.shift_schedule WHERE id = NEW.shift_schedule_id AND sector_id = machine_sector
   AND NEW.operating_date >= valid_from AND (valid_to IS NULL OR NEW.operating_date <= valid_to)) THEN
   RAISE EXCEPTION 'Capture shift mismatch' USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION vinto_txn.guard_capture_child() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE capture_id uuid; old_capture_id uuid; parent_record record;
BEGIN
 IF TG_OP <> 'DELETE' THEN capture_id := NEW.capture_id; END IF;
 IF TG_OP <> 'INSERT' THEN old_capture_id := OLD.capture_id; END IF;
 FOR parent_record IN SELECT id,status FROM vinto_txn.capture WHERE id IN (capture_id,old_capture_id) ORDER BY id FOR UPDATE LOOP
   IF parent_record.status <> 'draft' THEN
     RAISE EXCEPTION 'Capture details can only be changed in draft state' USING ERRCODE = '23514';
   END IF;
 END LOOP;
 IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION vinto_txn.validate_detail_group() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected_group uuid;
BEGIN
 SELECT field_group_id INTO expected_group FROM vinto_config.field_definition WHERE id = NEW.field_definition_id;
 IF expected_group IS DISTINCT FROM NEW.field_group_id THEN
   RAISE EXCEPTION 'Field group mismatch' USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END $$;

-- Required fields and group cardinality are checked at transaction end so a
-- header and its values can be inserted atomically in either order.
CREATE FUNCTION vinto_txn.validate_completed_capture() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_id uuid; parent_record record;
BEGIN
 IF TG_TABLE_NAME = 'capture' THEN parent_id := NEW.id;
 ELSE parent_id := coalesce(NEW.capture_id, OLD.capture_id); END IF;
 SELECT * INTO parent_record FROM vinto_txn.capture WHERE id = parent_id;
 IF NOT FOUND OR parent_record.status IN ('draft','blocked') THEN RETURN NULL; END IF;
 IF parent_record.created_by IS NULL OR parent_record.updated_by IS NULL THEN
   RAISE EXCEPTION 'Submitted capture requires creator and modifier' USING ERRCODE = '23514';
 END IF;
 IF EXISTS (SELECT 1 FROM vinto_config.field_group g WHERE g.form_version_id = parent_record.form_version_id
   AND ((SELECT count(*) FROM vinto_txn.capture_group_row r WHERE r.capture_id = parent_id AND r.field_group_id = g.id) < g.min_rows
   OR g.max_rows IS NOT NULL AND (SELECT count(*) FROM vinto_txn.capture_group_row r WHERE r.capture_id = parent_id AND r.field_group_id = g.id) > g.max_rows
   OR NOT g.repeatable AND (SELECT count(*) FROM vinto_txn.capture_group_row r WHERE r.capture_id = parent_id AND r.field_group_id = g.id) > 1)) THEN
   RAISE EXCEPTION 'Capture group cardinality is invalid' USING ERRCODE = '23514';
 END IF;
 IF EXISTS (SELECT 1 FROM vinto_config.field_definition f WHERE f.form_version_id = parent_record.form_version_id AND f.required
   AND (f.field_group_id IS NULL AND NOT EXISTS (SELECT 1 FROM vinto_txn.capture_detail d WHERE d.capture_id = parent_id AND d.field_definition_id = f.id)
   OR f.field_group_id IS NOT NULL AND EXISTS (SELECT 1 FROM vinto_txn.capture_group_row r WHERE r.capture_id = parent_id AND r.field_group_id = f.field_group_id
     AND NOT EXISTS (SELECT 1 FROM vinto_txn.capture_detail d WHERE d.capture_id = parent_id AND d.field_definition_id = f.id AND d.group_row_id = r.id)))) THEN
   RAISE EXCEPTION 'Capture is missing required values' USING ERRCODE = '23514';
 END IF;
 RETURN NULL;
END $$;


CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_master."user" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_master."user" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_master."profile" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_master."profile" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_master."user_profile" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_master."user_profile" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_master."sector" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_master."sector" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_master."machine" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_master."machine" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_master."machine_alias" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_master."machine_alias" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_master."device" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_master."device" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_master."unit" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_master."unit" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_master."material_class" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_master."material_class" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_master."article" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_master."article" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_master."article_version" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_master."article_version" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_master."article_machine" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_master."article_machine" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_config."shift" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_config."shift" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_config."shift_schedule" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_config."shift_schedule" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_config."workflow_definition" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_config."workflow_definition" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_config."form" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_config."form" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_config."form_version" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_config."form_version" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_config."form_version_machine" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_config."form_version_machine" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_config."field_group" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_config."field_group" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_config."field_definition" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_config."field_definition" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_config."field_option" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_config."field_option" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_config."field_option_dependency" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_config."field_option_dependency" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_config."workflow_step" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_config."workflow_step" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_config."recipe_version" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_config."recipe_version" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_config."recipe_component" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_config."recipe_component" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_config."report_definition" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_config."report_definition" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_txn."work_order" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_txn."work_order" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_txn."work_order_version" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_txn."work_order_version" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_txn."work_order_line" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_txn."work_order_line" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_txn."assignment" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_txn."assignment" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_txn."capture" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_txn."capture" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_txn."capture_group_row" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_txn."capture_group_row" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_txn."capture_detail" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_txn."capture_detail" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_txn."bobbin" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_txn."bobbin" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_txn."bobbin_relation" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_txn."bobbin_relation" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER z_touch BEFORE INSERT OR UPDATE ON vinto_txn."quality_release" FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_txn."quality_release" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_audit."import_batch" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER audit_changes AFTER INSERT OR UPDATE OR DELETE ON vinto_audit."import_record" FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

CREATE TRIGGER immutable_event BEFORE UPDATE OR DELETE OR TRUNCATE ON vinto_audit.audit_event FOR EACH STATEMENT EXECUTE FUNCTION vinto_audit.reject_mutation();

CREATE TRIGGER immutable_article_version BEFORE UPDATE OR DELETE ON vinto_master.article_version FOR EACH ROW EXECUTE FUNCTION vinto_audit.reject_mutation();

CREATE TRIGGER immutable_import_record BEFORE UPDATE OR DELETE ON vinto_audit.import_record FOR EACH ROW EXECUTE FUNCTION vinto_audit.reject_mutation();

CREATE TRIGGER guard_version BEFORE UPDATE OR DELETE ON vinto_config."form_version" FOR EACH ROW EXECUTE FUNCTION vinto_config.guard_published_version();

CREATE TRIGGER guard_version BEFORE UPDATE OR DELETE ON vinto_config."recipe_version" FOR EACH ROW EXECUTE FUNCTION vinto_config.guard_published_version();

CREATE TRIGGER guard_definition BEFORE INSERT OR UPDATE OR DELETE ON vinto_config."form_version_machine" FOR EACH ROW EXECUTE FUNCTION vinto_config.guard_form_child();

CREATE TRIGGER guard_definition BEFORE INSERT OR UPDATE OR DELETE ON vinto_config."field_group" FOR EACH ROW EXECUTE FUNCTION vinto_config.guard_form_child();

CREATE TRIGGER guard_definition BEFORE INSERT OR UPDATE OR DELETE ON vinto_config."field_definition" FOR EACH ROW EXECUTE FUNCTION vinto_config.guard_form_child();

CREATE TRIGGER guard_definition BEFORE INSERT OR UPDATE OR DELETE ON vinto_config."field_option" FOR EACH ROW EXECUTE FUNCTION vinto_config.guard_form_child();

CREATE TRIGGER guard_definition BEFORE INSERT OR UPDATE OR DELETE ON vinto_config."field_option_dependency" FOR EACH ROW EXECUTE FUNCTION vinto_config.guard_form_child();

CREATE TRIGGER guard_definition BEFORE INSERT OR UPDATE OR DELETE ON vinto_config."workflow_step" FOR EACH ROW EXECUTE FUNCTION vinto_config.guard_form_child();

CREATE TRIGGER guard_recipe BEFORE INSERT OR UPDATE OR DELETE ON vinto_config.recipe_component FOR EACH ROW EXECUTE FUNCTION vinto_config.guard_recipe_child();

CREATE TRIGGER guard_order_version BEFORE UPDATE OR DELETE ON vinto_txn.work_order_version FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_order_version();

CREATE TRIGGER guard_order_line BEFORE INSERT OR UPDATE OR DELETE ON vinto_txn.work_order_line FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_order_line();

CREATE TRIGGER validate_assignment BEFORE INSERT OR UPDATE ON vinto_txn.assignment FOR EACH ROW EXECUTE FUNCTION vinto_txn.validate_assignment();

CREATE TRIGGER validate_capture BEFORE INSERT OR UPDATE ON vinto_txn.capture FOR EACH ROW EXECUTE FUNCTION vinto_txn.validate_capture();

CREATE TRIGGER prevent_capture_delete BEFORE DELETE ON vinto_txn.capture FOR EACH ROW EXECUTE FUNCTION vinto_audit.reject_mutation();

CREATE TRIGGER guard_capture BEFORE INSERT OR UPDATE OR DELETE ON vinto_txn."capture_detail" FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_capture_child();

CREATE CONSTRAINT TRIGGER validate_required AFTER INSERT OR UPDATE OR DELETE ON vinto_txn."capture_detail" DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vinto_txn.validate_completed_capture();

CREATE TRIGGER guard_capture BEFORE INSERT OR UPDATE OR DELETE ON vinto_txn."capture_group_row" FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_capture_child();

CREATE CONSTRAINT TRIGGER validate_required AFTER INSERT OR UPDATE OR DELETE ON vinto_txn."capture_group_row" DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vinto_txn.validate_completed_capture();

CREATE CONSTRAINT TRIGGER validate_required AFTER INSERT OR UPDATE ON vinto_txn.capture DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vinto_txn.validate_completed_capture();

CREATE TRIGGER validate_group BEFORE INSERT OR UPDATE ON vinto_txn.capture_detail FOR EACH ROW EXECUTE FUNCTION vinto_txn.validate_detail_group();

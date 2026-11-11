-- CV-P112-01 ACL follow-up. Forward-only: 0027 is already applied and immutable.
-- New tables are born fail-closed (05_no_default_privileges.sql).
-- The HTTP backend uses vinto_app, not the migration owner.
-- No grants to vinto_reference, PUBLIC, or unrelated business tables.
DO $$
BEGIN
  -- Disposable test databases may not provision the application LOGIN role.
  -- Production must have vinto_app; otherwise the role provisioning gate blocks activation.
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app') THEN
    -- Weight lookup/preview: never write nominal catalog data as vinto_app.
    GRANT SELECT ON TABLE vinto_master.pallet_nominal_weight TO vinto_app;
    -- One immutable pallet row per capture; reading for history and idempotency.
    -- No UPDATE or DELETE; triggers additionally reject modification.
    GRANT SELECT, INSERT ON TABLE vinto_txn.production_pallet TO vinto_app;
  END IF;
END $$;

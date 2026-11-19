-- OFF-04.4 PROPOSED rollback (NOT applied). Drops only the isolated vinto_offline schema objects created by the proposal.
BEGIN;
DROP SCHEMA IF EXISTS vinto_offline CASCADE;
COMMIT;

-- USR-03: username and credential ownership must remain immutable even for direct DML.
-- Reuses the guard_identity trigger from migration 0002; no data rewritten.
CREATE OR REPLACE FUNCTION vinto_auth.guard_credential_identity()
RETURNS trigger LANGUAGE plpgsql AS $usr03$
BEGIN
    IF NEW.user_id IS DISTINCT FROM OLD.user_id THEN
        RAISE EXCEPTION 'Credential owner is immutable' USING ERRCODE = '23514';
    END IF;
    IF NEW.username IS DISTINCT FROM OLD.username THEN
        RAISE EXCEPTION 'Credential username is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$usr03$;

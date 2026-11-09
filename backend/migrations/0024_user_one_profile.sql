-- USR-02: one profile per user. Migration is additive and does not modify existing users.
-- Preflight fails closed if a legacy account has zero or multiple profiles.
DO $usr02$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM vinto_master."user" u
        LEFT JOIN vinto_master.user_profile up ON up.user_id = u.id
        GROUP BY u.id
        HAVING count(up.profile_id) <> 1
    ) THEN
        RAISE EXCEPTION 'USR-02: accounts without exactly one profile; reconcile before applying 0024'
            USING ERRCODE = '23514';
    END IF;
END
$usr02$;

-- Existing PK (user_id, profile_id) only blocks duplicate pairs, not multiple
-- distinct profiles on the same user. The new constraint closes that gap.
ALTER TABLE vinto_master.user_profile
    ADD CONSTRAINT user_profile_one_per_user UNIQUE (user_id);

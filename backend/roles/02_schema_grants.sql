-- CLOUD-01B-2: USAGE sobre esquemas.
--
-- Ejecuta este archivo vinto_migrator (ya es propietario de los 6 esquemas: los creó al aplicar
-- 0001-0006 con migrate.py --target dev/test usando MIGRATOR_DATABASE_URL/MIGRATOR_TEST_DATABASE_URL).
-- Un propietario puede otorgar privilegios sobre lo que posee sin ser superusuario.
--
-- Requisito previo: 00_create_roles.sql y 01_database_grants.sql ya se ejecutaron, y las 6 migraciones
-- (0001-0006) ya se aplicaron contra esta base conectando como vinto_migrator (ver backend/roles/README.md,
-- paso 3). Sin eso, estos esquemas todavía no existen y este archivo falla.

\set ON_ERROR_STOP on

-- vinto_app: necesita los 5 esquemas que su código referencia (confirmado por grep en backend/app:
-- vinto_master, vinto_config, vinto_txn, vinto_audit, vinto_auth). NUNCA vinto_meta.
GRANT USAGE ON SCHEMA vinto_master, vinto_config, vinto_txn, vinto_audit, vinto_auth TO vinto_app;

-- vinto_reference: solo los esquemas que app/seed/reference.py escribe (confirmado por grep: nunca
-- toca vinto_txn ni vinto_auth).
GRANT USAGE ON SCHEMA vinto_master, vinto_config, vinto_audit TO vinto_reference;

-- vinto_meta: sin USAGE para nadie salvo vinto_migrator (su propietario). No se otorga explícitamente
-- a PUBLIC, vinto_app ni vinto_reference; un esquema recién creado por un rol no superusuario no
-- concede USAGE a PUBLIC por defecto, así que esto ya es el estado correcto sin ninguna sentencia
-- adicional. Se deja como comentario, no como GRANT, para no conceder por error lo que se quiere negar:
-- NO ejecutar: GRANT USAGE ON SCHEMA vinto_meta TO vinto_app;  (vinto_app nunca debe leer el historial de migraciones)

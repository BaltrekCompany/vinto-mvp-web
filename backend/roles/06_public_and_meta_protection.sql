-- CLOUD-01B-2: verificación/documentación explícita de PUBLIC y de vinto_meta (OBS-PG-03, principio 8).
--
-- Nada de lo que sigue debería cambiar el estado real de la base (son REVOKE sobre privilegios que
-- PostgreSQL nunca concedió a PUBLIC para estos objetos, porque ninguno de los 6 esquemas es "public"
-- y ningún esquema no-"public" creado por un rol no superusuario concede USAGE a PUBLIC por defecto).
-- Se ejecutan explícitamente de todas formas para que el estado deseado quede escrito y verificable
-- en el repositorio, en vez de depender silenciosamente de un comportamiento por defecto de PostgreSQL
-- que un futuro cambio de versión u otra migración podría alterar sin que nadie lo note. Ejecuta
-- vinto_migrator (propietario de los esquemas y de las tablas).

\set ON_ERROR_STOP on

REVOKE ALL ON SCHEMA vinto_master, vinto_config, vinto_txn, vinto_audit, vinto_auth, vinto_meta FROM PUBLIC;

REVOKE ALL ON ALL TABLES IN SCHEMA vinto_meta FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA vinto_auth FROM PUBLIC;

-- vinto_reference nunca debe poder leer vinto_auth (no tiene USAGE sobre ese esquema desde
-- 02_schema_grants.sql, pero se deja constancia explícita de la intención):
-- NO ejecutar: GRANT SELECT ON vinto_auth.credential TO vinto_reference;  (el importador de catálogos
-- jamás necesita ver credenciales)

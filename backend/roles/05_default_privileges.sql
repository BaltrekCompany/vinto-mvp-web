-- CLOUD-01B-2 / OBS-PG-01: privilegio por defecto sobre TABLAS FUTURAS. Ejecuta vinto_migrator.
--
-- Resolución de OBS-PG-01: nunca "GRANT SELECT, INSERT, UPDATE, DELETE" indiscriminado sobre tablas
-- futuras. El único privilegio por defecto es SELECT, y solo en los 4 esquemas donde vinto_app/
-- vinto_reference ya leen hoy. vinto_auth y vinto_meta quedan EXCLUIDOS del default: ninguna tabla
-- nueva de esos dos esquemas debe ser legible sin una decisión explícita (vinto_auth guarda secretos
-- hasheados; vinto_meta es el historial de migraciones).
--
-- Esto solo afecta a CREATE TABLE ejecutados por vinto_migrator DESPUÉS de este ALTER DEFAULT
-- PRIVILEGES, es decir, a partir de la migración 0007 (0001-0006 ya existen y tienen sus GRANT
-- explícitos en 03_table_grants.sql). Toda escritura (INSERT/UPDATE/DELETE) sobre una tabla nueva
-- SIGUE requiriendo un GRANT explícito en la propia migración que la crea (ver
-- backend/migrations/README.md, sección "CLOUD-01B-2: modelo de privilegios mínimos").

\set ON_ERROR_STOP on

ALTER DEFAULT PRIVILEGES FOR ROLE vinto_migrator IN SCHEMA vinto_master, vinto_config, vinto_txn, vinto_audit
  GRANT SELECT ON TABLES TO vinto_app, vinto_reference;

-- Deliberadamente SIN default privileges para vinto_auth y vinto_meta: una tabla nueva ahí nace SIN
-- ningún privilegio para vinto_app/vinto_reference hasta que una migración lo conceda explícitamente.

-- CLOUD-01B-2 / PG54-01: el modelo NO concede ningún privilegio por defecto sobre tablas futuras.
--
-- Corrección sobre la versión anterior de este archivo: esa versión ejecutaba
-- "ALTER DEFAULT PRIVILEGES ... GRANT SELECT ON TABLES TO vinto_app, vinto_reference" para los esquemas
-- aplicativos. La auditoría de PR #54 (PG54-01) señaló correctamente que eso era una concesión
-- automática — aunque solo de lectura — sobre objetos que todavía no existen, y que el modelo debe ser
-- FAIL-CLOSED: una tabla nueva nace SIN NINGÚN privilegio para vinto_app/vinto_reference, en cualquier
-- esquema, sin excepción. La migración que introduce la tabla (0007 en adelante) es quien DEBE declarar
-- explícitamente, en su propio archivo .sql, exactamente los privilegios que esa tabla necesita (ver
-- backend/migrations/README.md, sección "CLOUD-01B-2: modelo de privilegios mínimos"). Sin ese GRANT
-- explícito, la tabla queda inaccesible para vinto_app y vinto_reference — ni siquiera SELECT.
--
-- Este archivo, por tanto, NO ejecuta ningún ALTER DEFAULT PRIVILEGES que conceda algo. Se conserva como
-- paso explícito del aprovisionamiento (en vez de simplemente omitirlo) para declarar y verificar el
-- estado deseado, incluido el comportamiento de PUBLIC, en vez de depender silenciosamente de que
-- PostgreSQL no concede nada por defecto. Ejecuta vinto_migrator (propietario de los esquemas).

\set ON_ERROR_STOP on

-- Declaración explícita y verificable: SIN ningún ALTER DEFAULT PRIVILEGES que otorgue nada a
-- vinto_app/vinto_reference en ningún esquema. PostgreSQL ya no concede nada por defecto a un rol
-- distinto del propietario sobre un objeto nuevo, así que no hay ninguna sentencia GRANT que anular aquí
-- — la ausencia de un ALTER DEFAULT PRIVILEGES con GRANT es, en sí misma, la política correcta.
--
-- Para que quede explícito y auditable (y no dependa únicamente del comportamiento por defecto de
-- PostgreSQL, que una versión futura podría cambiar), se fija explícitamente que PUBLIC tampoco recibe
-- nada sobre objetos futuros de los esquemas aplicativos:
ALTER DEFAULT PRIVILEGES FOR ROLE vinto_migrator IN SCHEMA vinto_master, vinto_config, vinto_txn, vinto_audit, vinto_auth
  REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE vinto_migrator IN SCHEMA vinto_master, vinto_config, vinto_txn, vinto_audit, vinto_auth
  REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE vinto_migrator IN SCHEMA vinto_master, vinto_config, vinto_txn, vinto_audit, vinto_auth
  REVOKE ALL ON FUNCTIONS FROM PUBLIC;

-- NO ejecutar ningún "... GRANT ... TO vinto_app" ni "... TO vinto_reference" en este archivo. Si una
-- migración futura necesita que vinto_app lea o escriba una tabla nueva, el GRANT va DENTRO de esa
-- migración (0007_descripcion.sql), nunca aquí.

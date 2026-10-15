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
-- nada sobre TABLAS ni SECUENCIAS futuras de los esquemas aplicativos (para estos dos tipos de objeto,
-- PostgreSQL ya no concede nada a PUBLIC por defecto, así que este REVOKE es defensivo/declarativo, no
-- correctivo — verificado empíricamente: una tabla nueva sin GRANT explícito queda con
-- has_table_privilege('public', ..., 'SELECT') = false incluso sin este REVOKE):
ALTER DEFAULT PRIVILEGES FOR ROLE vinto_migrator IN SCHEMA vinto_master, vinto_config, vinto_txn, vinto_audit, vinto_auth
  REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE vinto_migrator IN SCHEMA vinto_master, vinto_config, vinto_txn, vinto_audit, vinto_auth
  REVOKE ALL ON SEQUENCES FROM PUBLIC;

-- FUNCIONES: deliberadamente SIN "ALTER DEFAULT PRIVILEGES ... ON FUNCTIONS" aquí. A diferencia de
-- tablas/secuencias, verificado empíricamente (y documentado como limitación de PostgreSQL desde hace
-- años: BUG #8685 "alter default privileges cannot revoke default execute privilege on functions",
-- vigente también en los hilos de pgsql-hackers sobre "Removing the default grant of EXECUTE on
-- functions/procedures to PUBLIC") que esta sentencia NO suprime el EXECUTE que PostgreSQL concede a
-- PUBLIC por defecto sobre toda función nueva: tras ejecutarla, una función recién creada seguía con
-- proacl NULL y PUBLIC con EXECUTE=true. Escribirla aquí daría una falsa sensación de protección.
--
-- La única forma fiable es revocarlo del OBJETO YA CREADO (funciona siempre, verificado). Por eso: toda
-- migración futura (0007 en adelante) que cree una función invocable directamente con SELECT (no una
-- función de trigger, que PostgreSQL rechaza invocar directamente sin importar el EXECUTE — ver
-- 04_function_grants.sql) DEBE incluir, en el mismo archivo, su propio
-- "REVOKE EXECUTE ON FUNCTION <nombre>(<tipos>) FROM PUBLIC;" inmediatamente después de crearla, antes
-- de conceder EXECUTE a los roles que sí la necesiten.

-- NO ejecutar ningún "... GRANT ... TO vinto_app" ni "... TO vinto_reference" en este archivo. Si una
-- migración futura necesita que vinto_app lea o escriba una tabla nueva, el GRANT va DENTRO de esa
-- migración (0007_descripcion.sql), nunca aquí.

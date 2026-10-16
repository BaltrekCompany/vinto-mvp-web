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

-- FUNCIONES: precisión incorporada tras la auditoría de ChatGPT sobre PR #54 (verificación final).
-- La corrección anterior de este archivo concluyó, de un experimento con
-- "ALTER DEFAULT PRIVILEGES FOR ROLE vinto_migrator IN SCHEMA <esquemas> REVOKE EXECUTE ON FUNCTIONS
-- FROM PUBLIC", que NINGUNA forma de ALTER DEFAULT PRIVILEGES podía suprimir el EXECUTE que PostgreSQL
-- concede a PUBLIC por defecto sobre una función nueva. Repetido el experimento distinguiendo las dos
-- variantes que documenta https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html:
--   (a) "... IN SCHEMA x REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"  -> NO crea entrada en pg_default_acl
--       para un REVOKE (confirmado: pg_default_acl queda vacío); el EXECUTE de PUBLIC NO se suprime.
--   (b) "... FOR ROLE vinto_migrator REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC" (SIN "IN SCHEMA")  -> SÍ
--       crea una entrada global (defaclnamespace = 0) para ese rol; una función nueva creada por
--       vinto_migrator en CUALQUIER esquema (se verificó en vinto_txn y en un esquema distinto sin
--       ninguna entrada propia) queda con proacl NO NULO y PUBLIC/vinto_app/vinto_reference en
--       EXECUTE=false. Una función creada por OTRO rol (no vinto_migrator) no se ve afectada: el
--       alcance global es "por rol creador", no "para todo el clúster".
-- La variante (b) sí funciona y es la que se aplica abajo. La documentación/el comentario anteriores de
-- este archivo quedan corregidos: el problema era el "IN SCHEMA" combinado con REVOKE sobre funciones,
-- no el mecanismo de ALTER DEFAULT PRIVILEGES para funciones en general.
ALTER DEFAULT PRIVILEGES FOR ROLE vinto_migrator REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- Esto NO protege retroactivamente una función ya existente (verificado: vinto_txn.management_start_year,
-- creada antes de este ALTER DEFAULT PRIVILEGES por la migración 0004, siguió con PUBLIC en
-- EXECUTE=true después de aplicarlo). El REVOKE explícito sobre ese objeto en 04_function_grants.sql
-- sigue siendo necesario y no se elimina.
--
-- Toda migración futura (0007 en adelante) que cree una función invocable directamente con SELECT (no
-- una función de trigger, que PostgreSQL rechaza invocar directamente sin importar el EXECUTE — ver
-- 04_function_grants.sql) queda protegida por este default global SIN necesitar su propio REVOKE; aun
-- así, conviene declarar explícitamente a quién SÍ se le concede EXECUTE (GRANT EXECUTE ON FUNCTION
-- ... TO vinto_app;), por la misma disciplina de "declarar explícitamente cada privilegio" que exige
-- este modelo para tablas.

-- NO ejecutar ningún "... GRANT ... TO vinto_app" ni "... TO vinto_reference" en este archivo. Si una
-- migración futura necesita que vinto_app lea o escriba una tabla nueva, el GRANT va DENTRO de esa
-- migración (0007_descripcion.sql), nunca aquí.

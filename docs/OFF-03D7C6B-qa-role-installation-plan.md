# OFF-03D.7C6B — Ensayo de identidad y reversión (solo GitHub CI)

**18-nov-2026. Draft apilado sobre PR #215.** No autoriza escrituras en PostgreSQL QA real ni creación de roles, cuentas, concesiones, firmas o cambios de servicios/Nginx. Esta rama prueba el procedimiento oficial exclusivamente en PostgreSQL 17 efímero.

## Evidencia de entrada

Codex reportó OFF03D7C6B_PREFLIGHT=PASS_READ_ONLY con el catálogo completo, 31 migraciones y ACL, backup POST-DDL, piloto/TVC activos, clúster QA independiente, cero usuarios y concesiones, rol vinto_identity ausente y DML legado de vinto_app todavía activo. Los SQL de identidad y rollback coinciden con el checkout protegido; no se hicieron cambios de escritura.

## SQL oficial que se ensaya sin modificar

- backend/roles/00c_create_identity_role.sql: Git blob 04bc90dfeaf225d2c139587899fa46ce54913fe5. Crea rol LOGIN vinto_identity sin SUPERUSER, CREATEDB, CREATEROLE ni INHERIT, sin privilegios iniciales.
- backend/roles/03c_d3b2_identity_role_grants.sql: Git blob 6df9ac8c96d6cf85a00aecccc6631f8eddc7450b. Concede privilegios de identidad como vinto_migrator propietario, en transacción, sin revocar DML previo de vinto_app.
- backend/roles/rollback/ROLLBACK_D3B2.sql: Git blob 0039f4c530b611873f4b60710bf42aec54edd2c7. Revoca privilegios otorgados y deja vinto_identity existente. No es DROP ROLE.
- 03d_d3b4_cut_identity_dml.sql queda expresamente NO EJECUTADO; es una fase separada posterior a pruebas de conexión dual y aprobación independiente.

## Evidencia CI requerida

El runner scripts/off-03d7c6b-role-install-rehearsal-ci.sh reutiliza 31 migraciones/ACL e importación canónica en un contenedor PG17 desechable. Comprueba SHA Git de tres SQL; genera un secreto aleatorio solo en el runner y lo pasa al psql efímero mediante STDIN, no por argumento. Ejecuta 00c como bootstrap del contenedor y verifica rol sin permisos; luego ejecuta 03c como vinto_migrator y comprueba CONNECT, USAGE y solo DML de identidad. Confirma 31 migraciones, cero usuarios/grants y DML legado intacto. Finalmente ejecuta rollback D3B2 SOLO EN CI efímero y verifica que perdió CONNECT/INSERT pero no desapareció. Se destruye el contenedor al terminar. El runner se niega a funcionar si GITHUB_ACTIONS no es true; no tiene acceso al VPS.

La prueba demuestra comportamiento de SQL en CI, **no** que sea seguro ejecutar en la VPS sin un ejecutor separado, nuevo punto de recuperación y autorización expresa.

## Plan operativo futuro no autorizado

1. Validar de nuevo el preflight de rol y el aislamiento del clúster QA, sin tocar piloto/TVC ni volver a importar catálogos.
2. Definir un respaldo postimportación actual y restaurarlo en PG17 sin red antes de crear el rol, o registrar explícitamente otro plan de reversión. D7C4 es anterior al catálogo importado y NO sustituye una copia actual.
3. Preparar un ejecutor con modo inspección y modo de instalación condicionado por confirmaciones específicas del operador. Generar y custodiar un password de rol exclusivo de QA con archivo root:0600 sin imprimir el contenido ni pasarlo como argumento de shell o GitHub.
4. Tras autorización específica, crear SOLO vinto_identity en el clúster QA con el SQL oficial 00c; verificar que no tiene permisos iniciales.
5. Con autorización explícita para GRANT, ejecutar SOLO 03c como migrador y comprobar permisos efectivos, que vinto_app conserve su DML actual, que 31 migraciones y catálogos sigan intactos y no existan usuarios/grants.
6. Si falla alguna fase, detener sin repetir la operación ni restaurar automáticamente. ROLLBACK_D3B2 revoca privilegios SOLO antes del corte D3B4; NO elimina el rol y no restaura credenciales. Eliminar un rol huérfano o rotar password requiere aprobación y procedimiento separados.

## Puertas posteriores

D7C6C: separación DML de vinto_app (corte D3B4) solo tras ambas conexiones verificadas y aprobación independiente. D7C6D: cuenta QA sintética CALIDAD y ocho concesiones, también con autorización independiente. Perfil CALIDAD posee quality.capture y quality.release, por lo cual es indispensable verificar el middleware QA real deny-write bajo VPN/allowlist que impida acceso público antes de permitir la cuenta.

OFF-04 captura/sync permanece apagada. No hay API QA desplegada, ni merge a main.


## Hallazgo de regresion: propietario DB distinto del migrador

En el primer ensayo del PR #216, el script oficial 00c creo vinto_identity en PG17 efimero, pero la verificacion de CONNECT tras 03c no paso. El log emitio un warning de PostgreSQL: "no privileges were granted for vinto_qa_offline". La causa es que la base QA pertenece al administrador vinto_qa_bootstrap; vinto_migrator es propietario de los esquemas/tablas, pero NO dispone de grant option sobre la propia base. El SQL oficial 03c intenta conceder CONNECT como vinto_migrator y PostgreSQL no concede ese permiso.

**Decision de implementacion:** no alterar el SQL oficial 00c/03c. El procedimiento de roles requiere una subfase adicional exclusiva del ADMINISTRADOR de la base QA: GRANT CONNECT ON DATABASE vinto_qa_offline TO vinto_identity antes de aplicar 03c, y un REVOKE CONNECT por ese mismo administrador al revertir. El rollback oficial ROLLBACK_D3B2 ejecutado por vinto_migrator revoca privilegios de tablas/esquemas, pero NO puede revocar un CONNECT otorgado por el administrador. El rol global tampoco desaparece. Esta diferencia debe ser parte explicita de la autorizacion y de la prueba de rollback.

La CI corregida comprueba separadamente ambos lados en un contenedor PG17 efimero. Hasta que esa CI termine PASS, la instalacion en VPS se mantiene BLOQUEADA. La aprobacion futura debera mencionar CREATE ROLE, GRANT CONNECT del administrador, los GRANT de 03c del migrador y el REVOKE CONNECT de administrador dentro del plan de recuperacion. No hacer cambios en pilot/TVC ni usar una base PG compartida.

# OFF-03D.7C6B — Ejecutor controlado de identidad QA, sin nuevo respaldo

**18-nov-2026.** El operador indicó expresamente: «Saltemos ese respaldo, vamos avanzando con el siguiente punto». Se omite el **respaldo adicional posterior a la importación**, pero se conserva D7C4 histórico PRE-IMPORTACIÓN; **NO se restaura D7C4**. El permiso para omitir una copia **no amplía automáticamente el alcance a CREATE ROLE/GRANT**. Este PR prepara la operación y exige confirmaciones expresas antes de cualquier escritura real. Draft apilado sobre #216, sin merge a main.

## Por qué avanzar sin un respaldo nuevo es un riesgo aceptado, no un respaldo equivalente

D7C4 es una copia consistente de PostgreSQL QA con 31 migraciones, tomada **antes** de incorporar el catálogo oficial completo (26 formularios, 315 artículos, 4 versiones Calidad publicadas, 8 asociaciones MP1/MP3). Se verificó restauración sin red, pero volver a ese snapshot eliminaría el catálogo importado en QA. El rollback de los privilegios D3B2, ensayado en CI, permite una reversión **lógica y acotada**, no una recuperación punto-en-tiempo de todos los objetos. Si se interrumpe la creación del rol o la operación queda parcialmente completa, se debe detener y auditar el estado; **no repetir apply, ni restaurar automáticamente, ni hacer rollback implícito**.

## Evidencia previa

- D7C5A-R1: importación oficial en QA real, 31 migraciones, checksum de lote, cuatro formularios Calidad published, 8 pares MP1/MP3, 0 usuarios/grants e idempotencia PASS_READ_ONLY; backup histórico D7C4 íntegro.
- D7C6A: `vinto_identity` ausente; `vinto_app` conserva DML de identidad; API QA todavía sin pruebas de bloqueo operacional en servidor desplegado.
- D7C6B-PRE: Codex confirmó `OFF03D7C6B_PREFLIGHT=PASS_READ_ONLY`, aislamiento del clúster, SQL oficiales/rollback pinneados, 0 usuarios/grants, piloto/TVC PASS.
- PR #216 CI #44343142224: **2/2 PASS**, en PG17 desechable para 00c, concesión CONNECT por propietario de base, 03c por migrador, y rollback D3B2 más REVOKE CONNECT separado. Identificó que migrador no puede conceder CONNECT de base de datos propiedad de bootstrap.

## Artefacto nuevo

`scripts/off-03d7c6b-qa-identity-role-install.sh` solo soporta:

| Modo | Comportamiento | Estado |
|---|---|---|
| `inspect` | Solo lectura, PRE-ROL. Revalida el blob del preflight D7C6B, catálogo, recuperación histórica, aislamiento, roles, privilegios y ausencia de credencial/rol | Permitido sin autorización de escritura |
| `apply` | Solo con confirmaciones explícitas. Hace una única alta de `vinto_identity`, GRANT CONNECT desde bootstrap y 03c oficial desde migrador, luego verifica identidad y ACL | **No autorizado en este PR** |
| `verify` | Solo lectura, POST-ROL. Verifica permisos efectivos, 31 migraciones/catálogo intacto, usuarios=0/grants=0 y **autentica de forma real** el rol por TCP en 127.0.0.1:6554 con transacciones READ ONLY | Solo después de aplicar o para auditoría posterior |

**No repetir `inspect` PRE-ROL cuando exista el rol.** Luego de `apply`, usar exclusivamente `verify`, evitando los falsos bloqueos por cambio legítimo de fase.

El destino está fijado al contenedor PG17 `vinto-qa-postgres`, etiqueta `qa`, red `vinto-qa-internal`, host `127.0.0.1:6554` y DB `vinto_qa_offline`. Checkout protegido SHA `7b9eb8c82a290d06e719ee4990c2020076bbd11b`, inmutable, coincide con los Git blob de SQL 00c, 03c y rollback. `apply` comprueba `CONFIRM_QA_IDENTITY_ROLE_INSTALL=YES`, `CONFIRM_QA_TARGET=vinto_qa_offline_6554` y `ACK_NO_NEW_BACKUP=YES` **además de una autorización humana específica**.

La contraseña se genera únicamente durante el `apply` autorizado, con `secrets.token_hex(32)` / `O_EXCL` / `O_NOFOLLOW` y permisos root:0600 en `/etc/vinto-qa/role-identity.password`, nunca GitHub, chat, argumentos CLI, SQL en texto o logs. No se sobrescribe ningún secreto existente. La credencial de migrador existente es también root:0600 y se transfiere por STDIN al proceso de `psql` en el **contenedor QA**, sin aparecer en los argumentos Docker. `flock` evita ejecución concurrente.

### Permisos aplicados (una sola operación, secuencia fija)

1. `00c_create_identity_role.sql`: administrador `vinto_qa_bootstrap`, rol LOGIN sin CREATEDB/CREATEROLE/SUPERUSER/INHERIT ni permisos iniciales. Check en metadata.
2. `GRANT CONNECT ON DATABASE vinto_qa_offline TO vinto_identity`: **administrador propietario de DB**; comprobar el privilegio efectivo. El 03c oficial intenta ese mismo GRANT como migrador pero PostgreSQL advierte que no es propietario; el GRANT previo del propietario hace que el resultado sea correcto sin alterar el SQL oficial.
3. `03c_d3b2_identity_role_grants.sql`: `vinto_migrator` real por TCP interno, dueño de esquemas y tablas, transacción con lock_timeout. Aditivo; no retira DML de `vinto_app`.
4. `verify`: comprueba **cada** SELECT/INSERT/UPDATE por separado (no pasa una lista de privilegios a `has_table_privilege`, que en PostgreSQL puede evaluar un «alguno»); esquema/columna de perfil; prohibición de privilegios de negocio y DELETE indebido; `vinto_app` preservado; historial/catálogo y 0 usuarios/grants; conexión nueva `vinto_identity` por loopback, solo lectura.

**Fuera de alcance:** corte D3B4, usuario sintético, grants por máquina/formulario, firma Ed25519, Node, Nginx, acceso QA web, OFF-04, piloto/TVC/producción y `main`.

### Reversión: limitada y **no automática**

En fase D7C6B, antes del corte D3B4, el rollback oficial `ROLLBACK_D3B2.sql` como `vinto_migrator` retira permisos de tablas/esquemas, pero **NO elimina el rol** y NO puede revocar CONNECT otorgado por el propietario de la base. Se requiere `REVOKE CONNECT` como `vinto_qa_bootstrap` tras la revocación de grants, con verificación read-only. Ese rollback necesita una **autorización separada**, evaluación del estado y cuidado de no dejar usuarios sin administrador. No hacer DROP ROLE automático ni borrar la clave/archivo como parte del rollback sin procedimiento. La actual instalación QA NO modifica `vinto_app`, por lo que ese rol permanece como camino de administración durante la transición.

### CI y autorización

La CI del PR:
- tests Node de modos negativos, triple confirmación, destino fijo, identidad, control de secretos, query READ ONLY, ausencia de rollback automático, y separación `inspect/apply/verify`;
- replay de SQL oficial 00c/03c, con owner GRANT CONNECT y rollback D3B2/REVOKE CONNECT en PostgreSQL17 **desechable**, además de ejecutar el **mismo SQL POST-ROL** extraído del instalador y autenticar `vinto_identity` en modo readonly.

**Punto operativo siguiente:** tras CI PASS, Codex podrá verificar integridad del archivo y ejecutar **solo `inspect`** con hash fijado. Para que Codex ejecute `apply`, el operador deberá autorizar expresamente **CREATE ROLE `vinto_identity`, GRANT CONNECT y 03c exclusivamente en PostgreSQL QA, sin respaldo nuevo**, consciente de los límites de reversión. El pedido general de continuar no equivale a ese permiso. No hay cambios en VPS ni merge mientras se prepara este candidato.

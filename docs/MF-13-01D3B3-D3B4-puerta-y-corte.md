# MF-13-01D.3B.3 + D.3B.4 — Puerta de dos roles y corte de privilegios

Estado: **puerta automatizada y scripts del corte implementados y probados en bases PostgreSQL efímeras. El corte NO se ha ejecutado en ningún entorno persistente, y preparar `03d` NO autoriza su ejecución:** el corte real tiene una aprobación independiente durante el release único (`docs/MF-13-RELEASE-unico-procedimiento.md`). Ningún cambio en la VPS, en TVC ni en datos operativos.

Sigue el diseño de `docs/MF-13-01D3B-endurecimiento-privilegios-concesiones.md` (§5 y §7) y el plan `docs/MF-13-PLAN-release-unico.md`. Los criterios de aceptación de D.3B.3 y D.3B.4 se mantienen **separados** (§1).

## 0. Auditoría previa (resultados)

| Pregunta | Resultado |
|----------|-----------|
| ¿Algún consumidor de identidad usa `vinto_app`? | No. Las únicas escrituras de identidad están en `app/auth` y `app/admin` (inventario de escrituras de MF-13-01D.3B). Las rutas que usan la conexión de identidad son exactamente login, logout y `/api/admin/*` (auditoría estática de rutas dentro de la puerta). El resto del negocio solo importa tipos de `app.auth.service` |
| ¿Qué lee el negocio de identidad? | Solo `resolve_session`: `session` (por `token_hash`), `user`, `user_profile`, `profile`, y de `credential` únicamente `user_id`, `username`, `must_change`. `app/authz/readiness.py` (informe de lectura) usa `username`. Nada lee `password_hash` fuera de `authenticate` (conexión de identidad) |
| Bloqueos del motor | `FOR SHARE` sobre `user`, `user_profile`, `profile`, `machine`, `sector` y `user_machine_form_grant`: PostgreSQL exige `UPDATE` de al menos una columna; el corte deja `UPDATE (updated_at)`. `user_sector` no se bloquea (sin `UPDATE`, como diseña D.3A) |
| Compatibilidad con los scripts existentes | **Defecto encontrado y corregido** en la guarda de `postgres-grants` (PR #99): en un PRIMER aprovisionamiento `vinto_app` aún no tiene ningún privilegio y la consulta lo contaba como «D.3B.1 aplicado», bloqueando la fase. Ahora exige que el rol tenga `SELECT`. Además la guarda cubre D.3B.4 (`03` también restauraría el DML de identidad) |
| Pre-existente, fuera de alcance | `authz_readiness.py` abre la conexión del rol de referencia, que no tiene acceso a `vinto_auth`: con el modelo de roles de CLOUD-01B-2 ya fallaba antes de este cambio |

## 1. Criterios de aceptación (separados)

### D.3B.3 — puerta de verificación con dos roles

`backend/tests/test_d3b3_two_role_gate.py`, `TwoRoleGateTests`, recorre con los **scripts reales** y roles LOGIN reales:

`S0 inicial → S1 D.3B.1 (03b) → S2 D.3B.2 (00c/03c) → S3 D.3B.4 (03d) → S4 ROLLBACK_D3B4 → S5 ROLLBACK_D3B2 → S6 ROLLBACK_D3B1 (= S0)`

y ejecuta en cada estado la matriz que le corresponde:

| Comprobación | Estados |
|--------------|---------|
| Login, `/api/auth/me`, logout y qué rol sirve cada ruta (login/logout: identidad; `/me`: negocio) | S0–S6 |
| Administración (sectores, concesiones máquina-formulario), 401 sin sesión y 403 sin `user.manage` | S0–S6 |
| CLI `create_user` y `manage_user` | S0, S2, S3, S4 |
| Las cuatro capturas (central, F3, Calidad por bobina y por máquina) con `enforce` y el rol de negocio | S0, S2, S3, S4 (y una en S1) |
| Auditoría y atribución del actor (`session_user` = rol de login real) | cada matriz de API y CLI |
| Revocación de sector concurrente a una captura, y desactivación de un administrador concurrente a una escritura (sin interbloqueos) | S2, S3 |
| `current_user` distinto entre las conexiones de negocio e identidad | S2, S3 |
| El rol de negocio no puede modificar identidad ni leer el hash tras el corte | S3 |
| Orden prohibido: sin `IDENTITY_DATABASE_URL` el login falla tras el corte y no crea sesión | S3 |
| Sin la variable el sistema funciona; con la variable también | S4 (primero con, después sin) |
| El rollback completo devuelve la ACL EXACTA inicial de negocio, identidad y referencia | S6 |
| Preflight (`08`) y consulta de deriva (`07`) coherentes con cada estado | S0–S3 |

**Evidencia.** La prueba construye un informe (`contract: mf-13-01d3b3-gate/v1`) con veredicto **APROBADA/RECHAZADA**, versión de PostgreSQL y una fila por comprobación; con `D3B3_EVIDENCE_DIR` lo escribe como `d3b3-gate-evidence.json` y `.md` (sin URLs ni contraseñas; una prueba lo exige). Una excepción no controlada en cualquier paso queda registrada como fallo y el informe se escribe igualmente. **Solo es aprobación válida de la puerta (`valid_as_gate_approval`) con PostgreSQL 17**; con `D3B3_REQUIRE_PG17=1` (CI) la prueba falla en otra versión. Resultado local en 16.15: **APROBADA, 123 comprobaciones (las 119 originales más 4 de membresías), 0 fallidas, `valid_as_gate_approval = false`**.

**Rechazo.** Tres mutantes producen RECHAZADA: un corte que no revoca el hash, un corte que olvida `session`, y una reversión que no devuelve `INSERT` en `auth_event` (esta última por excepción registrada).

### D.3B.4 — el corte

`backend/roles/03d_d3b4_cut_identity_dml.sql` (convierte la fase `D3B4` del prototipo aprobado; una prueba exige que las sentencias coincidan) y `backend/roles/rollback/ROLLBACK_D3B4.sql`:

| Requisito | Cómo se cumple |
|-----------|----------------|
| Transaccional, idempotente, con guardas | `BEGIN`/`COMMIT`, `lock_timeout`, guardas y verificación final; repetirlo no cambia la ACL |
| Prohibido revocar antes de verificar el rol de identidad | La guarda comprueba, en la misma transacción y antes de cualquier `REVOKE`, que `vinto_identity` existe, puede conectar, no es peligroso y tiene los 24 privilegios que `vinto_app` perderá. Si no, aborta sin cambios |
| Aprobación independiente | Exige `vinto.d3b4_approval=CUT-IDENTITY-DML-APPROVED` (freno contra ejecuciones accidentales; la aprobación real es humana y queda en el acta del release). `deploy.sh` no lo ejecuta |
| Orden de fases y membresías | Aborta si D.3B.1 no está aplicado; si `vinto_app` es superusuario o tiene `CREATEROLE`/`CREATEDB`/`BYPASSRLS`/`REPLICATION`; si es propietario de las tablas **o puede asumir a su propietario**; si `vinto_app` pertenece a **cualquier** rol (con `INHERIT`, con `SET` o solo con `ADMIN OPTION`); si `vinto_app` y `vinto_identity` pueden asumirse mutuamente; o si cualquiera de los dos puede asumir a `vinto_migrator`, `vinto_reference`, `vinto_test_admin` o al propietario de las tablas (ver «Membresías» más abajo) |
| Lo estrictamente necesario para el negocio | Conserva `SELECT` de tabla sobre `user`, `user_profile`, `user_sector`, `user_machine_form_grant` y `session`; `credential` solo `user_id`, `username`, `must_change`; `UPDATE (last_seen_at)` de `session`; `INSERT` en auditoría |
| Bloqueos del motor | `UPDATE (updated_at)` sobre `user`, `user_profile` y `user_machine_form_grant` (más `profile`, `machine`, `sector` de D.3B.1); la verificación final lo comprueba |
| Privilegios efectivos tras el corte | La verificación final aborta (y no deja nada) si queda cualquier `INSERT`/`UPDATE`/`DELETE` de tabla, si se puede leer el hash, si falta una lectura necesaria o un bloqueo del motor, o si el rol de identidad perdió algo |
| `ROLLBACK_D3B4` restaura el acceso **antes** de retirar `IDENTITY_DATABASE_URL` | Solo concede, no requiere aprobación, restaura la ACL exacta; con ambos roles activos se prueba que login, administración y capturas funcionan, y solo después se prueba el modo sin variable. Con el corte aplicado, quitar la variable falla (`42501`): es el orden prohibido |
| No se ejecuta fuera de bases efímeras | Ningún flujo del repositorio lo invoca; una prueba exige que `deploy.sh` no lo nombre |

### Membresías de PostgreSQL (criterio de las guardas)

`pg_has_role(rol, objetivo, 'USAGE')` solo indica que el rol **hereda** los privilegios del objetivo. Una membresía `GRANT objetivo TO rol WITH INHERIT FALSE, SET TRUE` da `USAGE = false` y aun así permite `SET ROLE objetivo`; una membresía solo con `ADMIN OPTION` permite concederse otras. PostgreSQL 16+ distingue `MEMBER` (cualquier membresía), `USAGE` (herencia) y `SET`:

| Membresía de `vinto_app` en `vinto_identity` | `USAGE` | `SET` | `MEMBER` |
|----------------------------------------------|---------|-------|----------|
| `INHERIT FALSE, SET TRUE` | false | **true** | **true** |
| `INHERIT TRUE, SET FALSE` | true | false | true |
| `ADMIN TRUE, INHERIT FALSE, SET FALSE` | false | false | **true** |

Por eso las guardas usan `MEMBER` (superconjunto, válido en cualquier versión) y, en el corte, comprueban además `USAGE` y `SET` (este último solo si el servidor es ≥16) para dar el motivo exacto, y exigen que `vinto_app` **no pertenezca a ningún rol**. El mismo criterio está en `03b` y `03c` (propietario alcanzable solo por `SET`) y en `08_release_preflight.sql`, que además lista las membresías y no aborta si un rol no existe. Pruebas negativas con `INHERIT FALSE, SET TRUE` y las demás combinaciones: el corte aborta sin modificar ninguna ACL, el preflight deja de marcar `ready_for_d3b4`, y retiradas las membresías el mismo corte se aplica (control positivo). Mutante: volver al criterio `USAGE` hace RECHAZAR la puerta.

## 2. Reaprovisionamiento

`03_table_grants.sql` concede a `vinto_app` el conjunto amplio (también sobre las tablas de ambas fases). Re-ejecutarlo solo restaura la deriva. `postgres-grants` ahora cuenta, antes de cualquier `GRANT`, las tablas de D.3B.1 (3) y de D.3B.4 (6) ya endurecidas y **falla cerrado** sin ejecutar nada, indicando el procedimiento (03 → 03b → 03d con su aprobación, y `ROLLBACK_D3B4` antes de quitar la variable). Un rol sin privilegios (primer aprovisionamiento) o inexistente cuenta `0 0`. `07` muestra `d3b1_compliant` / `d3b4_compliant` por tabla.

## 3. Pruebas

- `test_d3b3_two_role_gate.py`: `TwoRoleGateTests` (la puerta), `CutScriptFilesTests` (coincidencia con el prototipo, transaccionalidad, solo privilegios, aprobación, README), `GateRejectsAnIncorrectCutTests` (corte con candados, nunca revoca antes de verificar, roles iguales/propietario, re-ejecutar `03` deshace el corte y se detecta, primer aprovisionamiento no se marca), `ReportTests`.
- `MembershipGuardTests` y `ReleaseProcedureOrderTests` (ver «Membresías» y el procedimiento del release).
- `test_postgres_grants_d3b1_guard.sh`: 14 casos de la guarda de `deploy.sh` (nada aplicado = flujo heredado; D.3B.1, D.3B.4, ambas, parcial, ilegible = falla cerrado sin SQL).
- GitHub Actions (`.github/workflows/d3b1-postgres17.yml`): ejecuta todo lo anterior contra `postgres:17`, exige la versión y publica la evidencia como artefacto.

## 4. Riesgos y límites

1. **PostgreSQL 17:** las pruebas locales corrieron en 16.15; la aprobación de la puerta solo es válida con el resultado del flujo en 17.
2. La puerta prueba el comportamiento sobre bases efímeras; **no** sustituye la verificación sobre la instalación del release (preflight `08` + puerta repetida en el release).
3. El corte protege frente a SQL arbitrario con el rol de negocio, no frente a un compromiso del proceso completo (posee ambas credenciales) ni frente a una inyección en un endpoint de identidad.
4. `ROLLBACK_D3B4` exige que `vinto_migrator` sea quien concedió los privilegios (o un superusuario actuando como propietario); la verificación final aborta si otro rol los concedió.
5. Entre `03` y `03d` al reaprovisionar a mano hay una ventana breve con privilegios amplios.
6. Con el corte aplicado y `IDENTITY_DATABASE_URL` rota, no hay login ni administración (a propósito, sin retroceso); las sesiones abiertas siguen sirviendo al negocio.

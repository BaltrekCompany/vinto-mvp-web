# MF-13 — Procedimiento del release único en la VPS (borrador para aprobación)

Estado: **procedimiento preparado; NO autoriza ni ejecuta nada.** Cada fase de endurecimiento sigue sin aplicarse en la VPS. Este documento se activa solo con una **autorización explícita y por escrito** del responsable del proyecto para tocar la instalación. No existe un entorno QA persistente separado: la aceptación se hace sobre este mismo release, con acceso restringido, y los usuarios finales se abren después (`docs/MF-13-PLAN-release-unico.md`).

Hay **dos escenarios** con órdenes distintos, porque los recursos del MVP pueden no existir todavía: **A, primera instalación** y **B, actualización de una instalación MVP ya aprovisionada** (§4). Ambos comparten reglas, condiciones, aprobación independiente del corte y reversiones.

## 1. Reglas que no se negocian

1. **TVC es intocable.** Ningún paso nombra ni modifica `postgres-vinto`, `vinto-web.service`, `/opt/vinto-web`, `vinto_default` ni `/etc/nginx/sites-available/vinto-tvc`, ni usa credenciales o datos de TVC. Las protecciones existentes de los scripts se conservan (`assert_container_is_ours`, `assert_unit_is_ours`, `TVC_BACKUP_CONFIRMED`, `assert_path_not_shared`, la fase `preflight`) y **ningún paso las salta ni las debilita**.
2. **Cada fase de privilegios tiene su punto de control y su reversión probada.** No se avanza sin el «GO» del punto de control anterior; NO-GO = detener y aplicar la reversión indicada, sin improvisar.
3. **El corte (D.3B.4) tiene una aprobación independiente** de la del release: quien autoriza el release no autoriza por eso el corte.
4. **Sin atajos de privilegios:** `postgres-grants` falla cerrado si hay fases aplicadas; no se re-ejecuta `03` sola.
5. Nunca se quita `IDENTITY_DATABASE_URL` con el corte aplicado: primero `ROLLBACK_D3B4`.
6. Ningún secreto en tickets, registros ni en la línea de comandos (contraseñas por variable de entorno del proceso `psql`, como en `backend/roles/README.md`).
7. **Estado mixto = incidente.** Si algunos recursos del MVP existen y otros no (§4), no se elige ningún escenario: se detiene y se consulta al responsable.

## 2. Roles y aprobaciones

| Rol humano | Responsabilidad |
|------------|-----------------|
| Responsable del release | Autoriza el release (documento escrito), ejecuta los pasos, guarda la evidencia de cada punto de control |
| Aprobador independiente del corte | Autoriza D.3B.4 tras revisar la evidencia del punto previo al corte; no es quien ejecuta |
| Responsable de TVC | Confirma que el respaldo de TVC existe y está verificado (`TVC_BACKUP_CONFIRMED=yes`) |

## 3. Condiciones previas (todas, antes de pedir el release)

- Los PR de la serie (D.3B.1, D.3B.2, D.3B.3/D.3B.4) fusionados, y GitHub Actions `postgres:17` en **PASS** con la evidencia `d3b3-gate-evidence` en `APROBADA` y `valid_as_gate_approval: true`.
- `REFERENCE_DATABASE_URL` definida (o `PG_PRIVILEGE_MODE=hardened`, que ya lo exige): sin ella `import-reference` cae a `vinto_app` y falla tras D.3B.1.
- Revisión humana de los scripts SQL (`03b`, `00c`, `03c`, `03d` y los tres rollbacks). Esta serie **no añade migraciones**; si el release incluye alguna, se sigue el procedimiento existente de `migrate` (revisar los pendientes antes de aplicar).
- Ventana de mantenimiento acordada (sin usuarios finales operando).

## 4. ¿Escenario A o B? (solo lectura, antes de cualquier cambio)

Comprobar, sin modificar nada, la existencia de los recursos del MVP:

| Recurso | Cómo se comprueba |
|---------|-------------------|
| Árbol del MVP | `/opt/vinto-mvp-web` (`MVP_APP_DIR`) y el usuario `vinto-mvp` |
| Contenedor PostgreSQL del MVP | `vinto-mvp-postgres` (nunca `postgres-vinto`, que es de TVC) |
| Unidades systemd | `vinto-mvp-backend.service`, `vinto-mvp-frontend.service` |
| Base y roles | `vinto_piloto` y los roles `vinto_app`, `vinto_migrator`, `vinto_reference` (solo si el contenedor ya existe) |

- **Ninguno existe → Escenario A (primera instalación).**
- **Todos existen → Escenario B (actualización).**
- **Cualquier otra combinación → estado mixto: STOP** (regla 7).

La fase `preflight` / `preflight-startup` de `deploy.sh` hace las comprobaciones de identidad de recursos y de TVC en ambos escenarios; esta tabla solo decide qué orden seguir.

## 5. Escenario A — primera instalación

Aún no hay código desplegado, contenedor, base ni roles del MVP. Por eso **no hay `healthcheck` ni MVP que respaldar al principio**, y el preflight de roles y privilegios (`08`) solo es ejecutable una vez creados los roles (A3).

| Pto. | Pasos (cada fase de `deploy.sh` con `CONFIRM=yes`) | Se comprueba y se guarda como evidencia | Reversión si NO-GO |
|------|-----------------------------------------------------|------------------------------------------|--------------------|
| **A0** | Autorización escrita; `bash deploy.sh preflight` (infraestructura, TVC, puertos, rutas); respaldo de TVC confirmado (`TVC_BACKUP_CONFIRMED=yes` será exigido al levantar el PostgreSQL del MVP); condiciones del §3; §4 resuelto en «ninguno existe» | Salida de `preflight`; instantánea de solo lectura del estado de TVC para comparar al final | Nada que revertir |
| **A1** | Código **sin servicios**: `user-and-dirs` → `preflight-build-deps` → `install-node-runtime` → `checkout <sha>` (`AUTHORIZED_COMMIT`) → `python-venv <sha>` → `install-frontend-artifact` → `preflight-startup` → `activate <sha>` | El release existe y `current` lo apunta; **no hay unidades ni servicios todavía** (`activate` solo conmuta el enlace), así que aquí no hay `healthcheck` | `rollback.sh version` no aplica (no hay versión anterior): se retiran los árboles creados con el procedimiento de `deploy/mvp/README.md` |
| **A2** | PostgreSQL del MVP: `postgres-up` (exige `TVC_BACKUP_CONFIRMED=yes`) → `postgres-bootstrap-db` → `postgres-roles` (crea `vinto_app`, `vinto_migrator`, `vinto_reference`; **sin** `vinto_identity` ni `00b`) → `migrate` | Roles creados; `migrate --check` sin pendientes. **Primer momento en que se puede ejecutar el preflight:** `psql -f backend/roles/08_release_preflight.sql` → guardar la salida (`vinto_app` sin membresías ni atributos peligrosos, `vinto_identity` aún inexistente es lo esperado) | `rollback.sh postgres` solo detiene el contenedor (nunca borra datos); la destrucción deliberada de datos es un procedimiento aparte |
| **A3** | Privilegios base: `postgres-grants` (02–06; la guarda ve «nada aplicado» incluso en esta base recién aprovisionada) → `08`: `ready_for_d3b1 = true` → **D.3B.1**: `03b` → `07`: `d3b1_compliant = true` (3 filas) → `import-reference` (dry-run) → `import-reference-apply` con `vinto_reference` → **respaldo del MVP** `bash backup.sh create-and-verify` (ya hay datos que proteger) | Evidencia de `07` y del respaldo verificado | `rollback/ROLLBACK_D3B1.sql` |
| **A4** | Servicios SIN la variable: `systemd-install` → `healthcheck` | `healthcheck` OK; login, capturas y administración funcionan (§7) con la conexión única. **Aquí está el primer `healthcheck` de la primera instalación** | `rollback.sh systemd` (detiene las unidades) |
| **A5** | **D.3B.2**: como administrador del clúster `00c` (con `IDENTITY_PASSWORD` en el entorno del proceso) y como `vinto_migrator` `03c` → `08`: `d3b2_privilegios_completos = true` → añadir `IDENTITY_DATABASE_URL` a `backend/.env` y reiniciar | Checklist §7 con ambos roles; `current_user` distinto entre las dos conexiones | Quitar la variable y reiniciar; opcional `rollback/ROLLBACK_D3B2.sql` |
| **A6** | Puerta D.3B.3 sobre la instalación: repetir la matriz con ambos roles **antes** del corte | `08`: `ready_for_d3b4 = true`; evidencia de PostgreSQL 17 (CI) adjunta; **segundo respaldo** `backup.sh create-and-verify` (punto de restauración previo al corte) | Igual que A5 |
| **A7** | **Aprobación independiente del corte.** El aprobador revisa la evidencia de A0–A6 y firma. Sin firma no hay corte | Acta firmada | — |
| **A8** | **D.3B.4**: con `ROLLBACK_D3B4` a mano, como `vinto_migrator`: `PGOPTIONS="-c vinto.d3b4_approval=CUT-IDENTITY-DML-APPROVED" psql -v ON_ERROR_STOP=1 -f 03d_d3b4_cut_identity_dml.sql` | `07`: `d3b4_compliant = true` (7 filas); `08`: `d3b4_aplicado = true`; checklist §7 completo con el rol de negocio restringido | **`rollback/ROLLBACK_D3B4.sql` ANTES de tocar `IDENTITY_DATABASE_URL`**; luego verificar con ambos roles |
| **A9** | Frontend MF-13-02 y arranque final; `healthcheck`; comparar el estado de TVC con la instantánea de A0 (sin cambios) | Informe final con la evidencia de A0–A8 | `rollback.sh version <sha>` si ya hubiera un release anterior; si no, `rollback.sh systemd` |
| **A10** | Entrega a QA manual con acceso restringido | Lista de cuentas de prueba creadas con `create_user.py` | — |

## 6. Escenario B — actualización de una instalación ya aprovisionada

Ya hay código, servicios, base y roles. Aquí **sí** se exige el estado sano de partida y un respaldo antes de cambiar nada.

| Pto. | Pasos | Se comprueba y se guarda como evidencia | Reversión si NO-GO |
|------|-------|------------------------------------------|--------------------|
| **B0** | Autorización escrita; `bash deploy.sh preflight` y `preflight-startup`; respaldo de TVC confirmado; **`bash backup.sh create-and-verify`** del MVP con su `.verified`; `healthcheck` de partida **OK**; copia de `backend/.env` y de las unidades (sin imprimir secretos); `psql -f backend/roles/08_release_preflight.sql` → guardar la salida (`vinto_app_no_es_superusuario_ni_propietario`, `vinto_app_sin_membresias_ni_atributos_peligrosos`, fases ya aplicadas); condiciones del §3 | Todo lo anterior. Si el `healthcheck` de partida falla, **NO-GO**: se arregla la instalación antes de actualizar | Nada que revertir |
| **B1** | Código nuevo: `checkout <sha>` (`AUTHORIZED_COMMIT`) → `python-venv <sha>` → `install-frontend-artifact` → `preflight-startup` → `activate <sha>` (con las unidades instaladas, `activate` comprueba el esquema, reinicia y verifica la salud; **sin** `IDENTITY_DATABASE_URL`) | `healthcheck` OK; comportamiento idéntico al anterior | `bash rollback.sh version <sha-anterior>` |
| **B2** | Privilegios base: `postgres-grants` **solo si hace falta** (si hay fases aplicadas se detiene a propósito; seguir su mensaje) → `08`: `ready_for_d3b1` → **D.3B.1**: `03b` → `07`: `d3b1_compliant = true` → `import-reference` (dry-run) con `vinto_reference` | Evidencia de `07`; login y capturas OK | `rollback/ROLLBACK_D3B1.sql` |
| **B3** | **D.3B.2**: `00c` y `03c` → `08`: `d3b2_privilegios_completos = true` → con la variable aún sin definir, todo igual que en B2 → añadir `IDENTITY_DATABASE_URL` y reiniciar | Checklist §7 con ambos roles; `current_user` distinto | Quitar la variable y reiniciar; opcional `rollback/ROLLBACK_D3B2.sql` |
| **B4** | Puerta D.3B.3 sobre la instalación y **respaldo previo al corte** (`backup.sh create-and-verify`) | `08`: `ready_for_d3b4 = true`; evidencia de PostgreSQL 17 (CI) adjunta | Igual que B3 |
| **B5** | **Aprobación independiente del corte** | Acta firmada | — |
| **B6** | **D.3B.4**: con `ROLLBACK_D3B4` a mano, como `vinto_migrator`: `PGOPTIONS="-c vinto.d3b4_approval=CUT-IDENTITY-DML-APPROVED" psql -v ON_ERROR_STOP=1 -f 03d_d3b4_cut_identity_dml.sql` | `07`: `d3b4_compliant = true`; `08`: `d3b4_aplicado = true`; checklist §7 | **`rollback/ROLLBACK_D3B4.sql` ANTES de tocar `IDENTITY_DATABASE_URL`** |
| **B7** | Frontend MF-13-02 (`install-frontend-artifact` + `activate` del release final) y `healthcheck` | Comparar TVC con su estado de B0 (sin cambios) | `rollback.sh version <sha-anterior>` |
| **B8** | Entrega a QA manual con acceso restringido | Informe final | — |

## 7. Checklist funcional (en los puntos de control con ambos roles y en el corte)

Login y logout; `/auth/me`; crear usuario (CLI y API admin), desactivar/reactivar; conceder/revocar sector; conceder/revocar máquina-formulario (la auditoría registra `vinto_identity` como `database_actor` cuando la variable está definida); las cuatro capturas (las compuertas se mantienen en `off` hasta que el QA manual las active explícitamente); revocación de sector con una captura en curso; administrador sin `user.manage` recibe 403; sin sesión, 401.

## 8. Qué hacer ante problemas

| Síntoma | Causa probable | Acción |
|---------|----------------|--------|
| `postgres-grants` falla cerrado | Hay D.3B.1 o D.3B.4 aplicado (correcto) | Seguir el mensaje; no forzar. Reaprovisionar: `03` + `03b` (+ `03d` con aprobación) a mano, o ejecutar `02`/`04…06` sin `03` |
| 503 en login/administración tras definir la variable | URL de identidad errónea o rol sin `CONNECT` | Corregir la URL (no hay retroceso a propósito) o quitar la variable (solo si el corte NO está aplicado) |
| `42501` en login/administración | Corte aplicado y `IDENTITY_DATABASE_URL` ausente o rol de identidad sin privilegios | Restaurar la variable; si no es posible, `ROLLBACK_D3B4` y verificar |
| `import-reference` falla con `42501` | `REFERENCE_DATABASE_URL` no definida (cae a `vinto_app`) tras D.3B.1 | Definirla con `vinto_reference` |
| `03b`/`03c`/`03d` abortan | Una guarda detectó una condición insegura (rol propietario o superusuario, **cualquier membresía** de `vinto_app` en otro rol —también `INHERIT FALSE, SET TRUE` o solo `ADMIN`—, privilegios de identidad incompletos, falta de aprobación) | Leer el mensaje; no hay cambios (transaccional); corregir la causa y volver a ejecutar `08` |
| `08` muestra `ready_for_* = false` | Falta una precondición de esa fase | Ver las banderas anteriores del resumen; no continuar |

## 9. Después de la aceptación

Apertura a usuarios finales: decisión posterior y separada, con las compuertas y el alcance acordados en el QA manual. Los rollbacks de privilegios permanecen disponibles; el procedimiento se archiva con su evidencia.

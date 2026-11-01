# MF-13 — Procedimiento del release único en la VPS (borrador para aprobación)

Estado: **procedimiento preparado; NO autoriza ni ejecuta nada.** Cada fase de endurecimiento sigue sin aplicarse en la VPS. Este documento se activa solo con una **autorización explícita y por escrito** del responsable del proyecto para tocar la instalación. No existe un entorno QA persistente separado: la aceptación se hace sobre este mismo release, con acceso restringido, y los usuarios finales se abren después (`docs/MF-13-PLAN-release-unico.md`).

## 1. Reglas que no se negocian

1. **TVC es intocable.** Ningún paso nombra ni modifica `postgres-vinto`, `vinto-web.service`, `/opt/vinto-web`, `vinto_default` ni `/etc/nginx/sites-available/vinto-tvc`, ni usa credenciales o datos de TVC. Las protecciones existentes de los scripts se conservan (`assert_container_is_ours`, `assert_unit_is_ours`, `TVC_BACKUP_CONFIRMED`, `assert_path_not_shared`) y **ningún paso las salta ni las debilita**.
2. **Cada fase de privilegios tiene su punto de control y su reversión probada.** No se avanza sin el «go» del punto de control anterior.
3. **El corte (D.3B.4) tiene una aprobación independiente** de la del release: quien autoriza el release no autoriza por eso el corte.
4. **Sin atajos de privilegios:** `postgres-grants` falla cerrado si hay fases aplicadas; no se re-ejecuta `03` sola.
5. Nunca se quita `IDENTITY_DATABASE_URL` con el corte aplicado: primero `ROLLBACK_D3B4`.
6. Ningún secreto en tickets, registros ni en la línea de comandos (contraseñas por variable de entorno del proceso `psql`, como en `backend/roles/README.md`).

## 2. Roles y aprobaciones

| Rol humano | Responsabilidad |
|------------|-----------------|
| Responsable del release | Autoriza el release (documento escrito), ejecuta los pasos, guarda la evidencia de cada punto de control |
| Aprobador independiente del corte | Autoriza D.3B.4 tras revisar la evidencia de C5; no es quien ejecuta |
| Responsable de TVC | Confirma que el respaldo de TVC existe y está verificado (`TVC_BACKUP_CONFIRMED=yes`) |

## 3. Condiciones previas (todas, antes de pedir el release)

- Los PR de la serie (D.3B.1, D.3B.2, esta) fusionados, y GitHub Actions `postgres:17` en **PASS** con la evidencia `d3b3-gate-evidence` en `APROBADA` y `valid_as_gate_approval: true`.
- `REFERENCE_DATABASE_URL` definida (o `PG_PRIVILEGE_MODE=hardened`, que ya lo exige): sin ella `import-reference` cae a `vinto_app` y falla tras D.3B.1.
- Revisión humana de los scripts SQL (`03b`, `00c`, `03c`, `03d` y los tres rollbacks).
- Ventana de mantenimiento acordada (sin usuarios finales operando).

## 4. Puntos de control

Cada punto de control termina en **GO / NO-GO**. NO-GO = detener y aplicar la reversión indicada; no improvisar.

| Pto. | Cuándo | Qué se comprueba (y se guarda como evidencia) | Reversión si NO-GO |
|------|--------|-----------------------------------------------|--------------------|
| **C0** | Antes de tocar nada | Autorización escrita; `bash deploy.sh preflight` y `preflight-startup`; respaldo de TVC confirmado; **`bash backup.sh create-and-verify`** del MVP con su `.verified`; copia de `backend/.env` y de las unidades (sin imprimir secretos); `psql -f backend/roles/08_release_preflight.sql` → guardar la salida | Nada que revertir |
| **C1** | Código desplegado SIN `IDENTITY_DATABASE_URL` | `checkout <sha>`, `python-venv`, `install-frontend-artifact`, `activate <sha>`; `healthcheck` OK; comportamiento idéntico al anterior | `bash rollback.sh version <sha-anterior>` |
| **C2** | Esquema y roles | `postgres-roles`, `migrate` (revisar pendientes antes de aplicar); `08`: `vinto_app_no_es_superusuario_ni_propietario = true` y `vinto_app` no es propietario de ninguna tabla | `rollback.sh version`; las migraciones no se revierten (solo aditivas, revisadas antes) |
| **C3** | D.3B.1 | `08`: `ready_for_d3b1 = true`; como `vinto_migrator` `03b_d3b1_restrict_catalog_writes.sql`; `07`: `d3b1_compliant = true` (3 filas); `import-reference` (dry-run) con `vinto_reference`; login y capturas OK | `rollback/ROLLBACK_D3B1.sql` |
| **C4** | D.3B.2 | `00c` (con `IDENTITY_PASSWORD` en el entorno) y `03c`; `08`: `d3b2_privilegios_completos = true`; **con la variable aún sin definir**: todo igual que en C3. Añadir `IDENTITY_DATABASE_URL` a `backend/.env` (`deploy/mvp/env/backend.env.example`) y reiniciar el servicio: login, logout, `/auth/me`, administración, CLI y capturas OK; `current_user` distinto entre ambas conexiones | Quitar la variable y reiniciar (suficiente); opcional `rollback/ROLLBACK_D3B2.sql` |
| **C5** | Puerta D.3B.3 en la instalación | Repetir la matriz de la puerta con ambos roles reales **antes** del corte: `08`: `ready_for_d3b4 = true`; checklist manual del §5; evidencia de PostgreSQL 17 (CI) adjunta | Igual que C4 |
| **C6** | **Aprobación independiente del corte** | El aprobador revisa la evidencia de C0–C5 y firma. Sin firma no hay corte | — |
| **C7** | D.3B.4 | Tener a mano `ROLLBACK_D3B4`. Como `vinto_migrator`: `PGOPTIONS="-c vinto.d3b4_approval=CUT-IDENTITY-DML-APPROVED" psql -v ON_ERROR_STOP=1 -f 03d_d3b4_cut_identity_dml.sql`; `07`: `d3b4_compliant = true` (7 filas); `08`: `d3b4_aplicado = true`; repetir el checklist del §5 (todo debe seguir funcionando con el rol de negocio restringido) | **`rollback/ROLLBACK_D3B4.sql` ANTES de tocar `IDENTITY_DATABASE_URL`**; luego verificar con ambos roles |
| **C8** | Frontend MF-13-02 y arranque | `systemd-install` (solo si procede), `healthcheck`; el frontend muestra y restringe por permisos | `rollback.sh version <sha>` |
| **C9** | Entrega a QA manual | Informe final con la evidencia de C0–C8; acceso restringido; lista de cuentas de prueba creadas con `create_user.py` | — |

## 5. Checklist funcional (en C4, C5 y C7)

Login y logout; `/auth/me`; crear usuario (CLI y API admin), desactivar/reactivar; conceder/revocar sector; conceder/revocar máquina-formulario (la auditoría registra `vinto_identity` como `database_actor`); las cuatro capturas con las compuertas en el valor acordado para el QA manual (**las compuertas se mantienen en `off` hasta que el QA manual las active explícitamente**); revocación de sector con una captura en curso; administrador sin `user.manage` recibe 403; sin sesión, 401.

## 6. Qué hacer ante problemas

| Síntoma | Causa probable | Acción |
|---------|----------------|--------|
| `postgres-grants` falla cerrado | Hay D.3B.1 o D.3B.4 aplicado (correcto) | Seguir el mensaje; no forzar. Reaprovisionar: `03` + `03b` (+ `03d` con aprobación) a mano, o ejecutar `02`/`04…06` sin `03` |
| 503 en login/administración tras definir la variable | URL de identidad errónea o rol sin `CONNECT` | Corregir la URL (no hay retroceso a propósito) o quitar la variable (solo si el corte NO está aplicado) |
| `42501` en login/administración | Corte aplicado y `IDENTITY_DATABASE_URL` ausente o rol de identidad sin privilegios | Restaurar la variable; si no es posible, `ROLLBACK_D3B4` y verificar |
| `import-reference` falla con `42501` | `REFERENCE_DATABASE_URL` no definida (cae a `vinto_app`) tras D.3B.1 | Definirla con `vinto_reference` |
| `03b`/`03d` abortan | Una guarda detectó una condición insegura | Leer el mensaje; no hay cambios (transaccional); corregir la causa |

## 7. Después de la aceptación

Apertura a usuarios finales: decisión posterior y separada, con las compuertas y el alcance acordados en el QA manual. Los rollbacks de privilegios permanecen disponibles; el procedimiento se archiva con su evidencia.

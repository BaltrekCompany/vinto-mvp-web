# MF13-03.B — Plan de despliegue y habilitación (PREPARADO, NO EJECUTADO)

Estado: `origin/main` con PR1–PR8, migraciones 0010–0012 y **PR-C** (`check-release` / `migrate-release`). **Nada de este documento se ejecutó.** No se tocó la VPS, `vinto_piloto`, TVC, ETL ni Nginx. Cada paso con `CONFIRM=yes` exige autorización explícita de quien administra el VPS (ver `deploy/mvp/README.md`). Diagnóstico y pruebas de PR-C: `docs/MF-13-03B-PRC-migrar-antes-de-activar.md`.

## 1. Inventario de lo que cambia

| Componente | Cambio | Observación |
|---|---|---|
| PostgreSQL (`vinto_piloto`) | Migraciones **0010, 0011, 0012** (las que falten: lo dice `check-release`) | Solo `vinto_migrator` (propietario) las aplica. 0010 rellena `machine_id` (auditado); 0011 cambia el índice por un trigger; 0012 añade una guarda. Ninguna reescribe datos históricos. |
| Backend FastAPI (systemd) | Release nuevo `releases/<sha>/` | Funciones nuevas **apagadas** (`WORK_ORDERS_MULTI_MACHINE_ENABLED=false` por defecto). |
| Frontend (artefacto construido aparte) | UI de Jefatura, Supervisión y Operación | Se construye con `build-frontend-artifact.sh`; nunca en la VPS. |
| `shared/backend.env` | **Sin cambios.** No define `WORK_ORDERS_MULTI_MACHINE_ENABLED` ni `AUTHZ_*` | `PG_PRIVILEGE_MODE=hardened`, `APP_ENV=pilot` ya están en la plantilla. |
| Roles/GRANTs, Nginx, TVC, ETL | Sin cambios | Las funciones-trigger las crea el propietario; no requieren GRANT a `vinto_app`. |

## 2. Secuencia de despliegue de una ACTUALIZACIÓN (cinco etapas separadas)

**Por qué este orden.** Verificado con pruebas (§3 del informe PR-C): el backend **anterior** funciona sobre el esquema 0010–0012 (328 pruebas del backend anterior pasan sobre ese esquema), pero el backend **nuevo** NO funciona sobre un esquema anterior a 0010. Por tanto **las migraciones van antes de activar el backend nuevo**. Hasta PR-C, `activate` comprobaba el esquema contra el release anterior (`current`) y no contra el que se activa; ahora comprueba el **release destino** y se detiene si le faltan migraciones.

Los pasos de preparación del release (`checkout`, `link-backend-env`, `python-venv`, `install-frontend-artifact`) no cambian y **no** activan nada.

### Etapa A — Preflight ANTES de migrar (solo lectura)
1. Backup verificado (`scripts/backup.sh`) y restauración probada en una base descartable.
2. `psql -v ON_ERROR_STOP=1 -f backend/preflights/mf13_03b_preflight_before_migrate.sql` — **funciona sobre el esquema actual, incluso sin 0010–0012** (solo lee objetos anteriores a 0010; probado sobre una base con 0001–0009). Muestra: versión aplicada, roles `vinto_migrator`/`vinto_app`, precondiciones que 0011 verificaría (línea activa dos veces; máquina con dos OT), operadores sin concesión (requisito para encender el flag, no para migrar) y asignaciones de otro turno.
3. `bash deploy.sh check-release <sha>` — **solo lectura, sin CONFIRM**: usa el `migrate.py` y los archivos de migración **del propio release**, como el usuario de servicio. Salida: `0` el esquema ya basta; `2` faltan migraciones (las lista); `1` error o historial divergente (checksum modificado, huecos, o el release conoce *menos* migraciones que la base).

### Etapa B — Aplicación de migraciones
`CONFIRM=yes AUTHORIZED_COMMIT=<sha> bash deploy.sh migrate-release <sha>`
- Solo sobre un release **ya preparado** (venv, build del frontend, `backend/.env` enlazado): si no, se detiene **antes** de tocar la base.
- Exige `CONFIRM=yes` **y** `AUTHORIZED_COMMIT` exactamente igual al SHA (mismo patrón que `checkout`).
- Toma el candado compartido con `activate`/`rollback` (nunca migra mientras se conmuta `current`) y `migrate.py` toma además su candado advisory.
- Diagnóstico de solo lectura primero; si el historial diverge **no aplica nada**. Aplica solo lo que falta, cada migración en su propia transacción.
- **No** cambia `current`, **no** reinicia systemd, **no** activa backend ni frontend.
- Idempotente: repetirlo sin pendientes dice «Nada que aplicar».
- Ventana de bloqueo: los triggers de 0011/0012 esperan a las escrituras en curso sobre `assignment` (lock de tabla breve): programarlo fuera de un turno de captura.

### Etapa C — Verificación posterior
- Automática al final de `migrate-release`: `migrate.py --check` del release (debe pasar).
- `psql -v ON_ERROR_STOP=1 -f backend/preflights/mf13_03b_verify_after_migrate.sql` — **solo después de migrar** (consulta `machine_id` y el trigger de 0012; falla si se ejecuta antes). Esperado: `12 | 12 | O` y secciones vacías salvo decisiones humanas (máquinas con varias activas, estados imposibles, etc.).
- Opcional: `psql -f backend/preflights/0012_assignment_single_mode_preflight.sql`.
- Contar `assignment`, `capture`, `work_order_line` antes y después; deben coincidir.

### Etapa D — Activación del backend
`bash deploy.sh preflight-startup` → `CONFIRM=yes bash deploy.sh activate <sha>`.
La guarda de `activate` ejecuta `migrate.py --check` **del release destino** antes de tocar `current`; si falta algo, falla y remite a `check-release`/`migrate-release`. Luego conmuta, reinicia, hace healthcheck y, si falla, revierte solo el symlink (comportamiento existente, sin cambios). La primera instalación (sin unidades systemd) no reinicia nada y sigue usando `migrate` como siempre.
Nota: **volver a un release más viejo con `activate` queda rechazado** por la guarda (el release conoce menos migraciones que la base); para volver atrás se usa `rollback.sh version <sha>`, que no consulta el esquema.

### Etapa E — Pruebas de humo
Con la compuerta **APAGADA**: login de Jefatura/Supervisión/Operación; `GET /api/work-orders/capabilities` → `{"multi_machine": false}` (403 para Operación); crear y publicar una OT de una máquina; activar una línea y luego otra (la primera se reemplaza); Operación ve su línea **sin selector** y captura F3; `activate-all` → 422 `MULTI_MACHINE_DISABLED`; ningún botón «Activar todas las líneas». Observar un turno completo. Con la compuerta encendida (etapas posteriores) se reutiliza el recorrido `scripts/e2e/mm13-run.mjs` **solo en laboratorio**.

## 3. Corte entre migración y activación (qué pasa y qué hacer)

| Momento del corte | Estado resultante | Acción |
|---|---|---|
| Durante `migrate-release`, a mitad de una migración | La migración en curso se revierte entera; las anteriores quedan aplicadas; `current` intacto; el backend viejo sigue sirviendo | Repetir `migrate-release` (aplica solo lo que falte) |
| Tras migrar, antes de `activate` | Esquema 0012 + backend **anterior** sirviendo, `current` sin cambios | **Seguro** (compatibilidad verificada): esperar o continuar con `activate`. No hace falta revertir el esquema |
| `activate` rechazado por la guarda | `current` intacto, sin reinicios | `check-release <sha>` y `migrate-release <sha>` |
| Falla el healthcheck tras `activate` | Reversión automática del symlink al release anterior | Investigar; el release anterior es compatible con el esquema nuevo |

## 4. Habilitación progresiva (el flag NO es lo primero)

La compuerta es una variable del backend (global; no por OT ni por máquina). Se enciende solo con autorización expresa, en este orden:

| Etapa | Acción | Condición de salida |
|---|---|---|
| 0 | Despliegue con compuerta APAGADA (secuencia A–E) | Humo OK + un turno de observación |
| 1 | Conceder las concesiones máquina-formulario que falten a **todos** los operadores activos (sección 4 del preflight) | Sin filas |
| 2 | (Opcional) `AUTHZ_ASSIGNMENT_READS_MODE=observe` | Sin ocultamientos inesperados |
| 3 | Encender el flag en laboratorio/piloto aislado y correr el recorrido E2E | Todo verde salvo defectos aceptados |
| 4 | Producción: encender fuera de turno, con Supervisión presente; primera OT multimáquina pequeña | Capturas correctas por línea |
| 5 | Ampliar. **No** activar modos `AUTHZ_*` `enforce` aquí (decisión aparte) | — |

Reversión del flag: apagar y reiniciar. Con varias activas heredadas el backend responde 409 `MULTIPLE_ACTIVE_ASSIGNMENTS` hasta finalizarlas con `finish`.

## 5. Rollback

| Qué falló | Acción | Límite real |
|---|---|---|
| Backend nuevo (tras `activate`) | `rollback.sh version <sha-anterior>` (symlink atómico) | El backend anterior es compatible con 0010–0012: **no se revierte el esquema** |
| Frontend | Reinstalar el artefacto anterior / `rollback.sh version` | — |
| Flag | Apagar y reiniciar | Varias activas heredadas ⇒ 409 hasta finalizar |
| 0012 | `backend/rollbacks/0012_…_rollback.sql` | La regla «una sola» vuelve a depender solo de la aplicación |
| 0011 | `backend/rollbacks/0011_…_rollback.sql` | **Rehúsa** con 2+ activas en una máquina |
| 0010 | `backend/rollbacks/0010_…_rollback.sql` | Solo antes de que una línea use otra máquina |
| Datos | Restaurar el backup | Pierde lo escrito después; último recurso |

## 6. Matriz GO / NO-GO

| # | Condición | GO si | NO-GO si |
|---|---|---|---|
| 1 | Suites | Backend sin fallos nuevos frente a `main` (19 heredados); suite bash 52/52; pruebas de `migrate-release` en verde | Un fallo nuevo |
| 2 | Backup | Verificado y restaurado en base descartable | No |
| 3 | Preflight ANTES de migrar | Sin precondiciones de 0011 violadas | Alguna violada |
| 4 | `check-release <sha>` | Salida 0 o 2 (pendientes conocidas) | Salida 1 (divergencia) |
| 5 | Orden | `migrate-release` **antes** de `activate` | Se pretende activar primero |
| 6 | Verificación posterior | `--check` limpio y `verify_after_migrate` esperado | Estado imposible |
| 7 | Compuerta | Apagada en el despliegue inicial | Se enciende en el mismo cambio |
| 8 | Concesiones (para encender) | Sección 4 sin filas | Operadores sin concesión |
| 9 | Defectos de la QA (DEF-1/DEF-2, Rebobinado/Conversión) | Aceptados o corregidos antes de **encender** | Sin decisión |
| 10 | Autorizaciones (VPS y TVC) | Por escrito, fase por fase | Falta |

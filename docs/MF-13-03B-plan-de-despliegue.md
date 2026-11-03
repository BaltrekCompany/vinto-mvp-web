# MF13-03.B — Plan de despliegue y habilitación (PREPARADO, NO EJECUTADO)

Estado: `origin/main` e193777 (PR1–PR8 y migraciones 0010–0012 fusionados). **Nada de este documento se ejecutó.** No se tocó la VPS, `vinto_piloto`, TVC, ETL ni Nginx. Cada paso con `CONFIRM=yes` exige autorización explícita de quien administra el VPS (ver `deploy/mvp/README.md`).

## 1. Inventario de lo que cambia

| Componente | Cambio | Observación |
|---|---|---|
| PostgreSQL (`vinto_piloto`, contenedor del MVP) | Migraciones **0010, 0011, 0012** (las que falten: confirmar con `migrate.py --check`) | Solo `vinto_migrator` (propietario) las aplica. Ninguna toca ni reescribe datos históricos salvo el relleno de `machine_id` de 0010 (auditado). |
| Backend FastAPI (`vinto-mvp-api`, systemd) | Release nuevo (`releases/<sha>/`): OT multimáquina, activación masiva, visibilidad por máquina, `/capabilities`, `/active-lines`, declaración de modo (0012) | Todas las funciones nuevas quedan **apagadas** (`WORK_ORDERS_MULTI_MACHINE_ENABLED=false` por defecto). |
| Frontend (artefacto estático construido aparte) | UI de Jefatura (PR6/6.1), Supervisión (PR7), Operación (PR8) | Se construye con `scripts/build-frontend-artifact.sh`; nunca en la VPS. |
| `backend.env` (`shared/backend.env`) | **Sin cambios requeridos.** No contiene `WORK_ORDERS_MULTI_MACHINE_ENABLED` ni `AUTHZ_*` (verificado en `deploy/mvp/env/backend.env.example`); por defecto, apagados | `PG_PRIVILEGE_MODE=hardened` y `APP_ENV=pilot` ya están en la plantilla. |
| Roles/GRANTs (`backend/roles/*.sql`) | Sin cambios | Las funciones-trigger de 0011/0012 las crea el propietario; no requieren GRANT adicional a `vinto_app`. |
| Nginx, TVC, ETL | Sin cambios | Fuera de alcance. |

## 2. Orden de despliegue (decisión clave)

**Compatibilidad hacia atrás** (verificada por lectura de las migraciones y por las pruebas de 0012):
- Backend **viejo** sobre esquema 0010–0012: funciona (0010 es un paso *expand* que rellena `machine_id` con un trigger; 0011 conserva «sustituir la anterior»; 0012 en modo «una sola» equivale al historial).
- Backend **nuevo** sobre esquema anterior a 0010: **NO** funciona (necesita `work_order_line.machine_id`).

Por tanto **las migraciones van ANTES de activar el backend nuevo**. Atención: `deploy.sh migrate` solo ejecuta `--check` y corre desde `current` (después de `activate`); por sí solo dejaría una ventana con el backend nuevo sobre el esquema viejo. Procedimiento propuesto (requiere autorización, no cambia `deploy.sh`):

1. **Congelar el cambio** y confirmar con quien administra TVC que la coexistencia sigue autorizada.
2. **Backup verificado** de `vinto_piloto` y del Postgres de TVC (`scripts/backup.sh`) y comprobar su restauración en una base descartable.
3. **Preflight SQL de solo lectura** (§4) y revisar sus filas.
4. `checkout <sha>` → `python-venv <sha>` → `install-frontend-artifact <sha> …` **sin `activate`**.
5. **Migrar desde el release nuevo, aún sin activarlo**, como `vinto-mvp`: `cd releases/<sha>/backend && .venv/bin/python migrate.py --check`, revisar, y solo entonces `migrate.py` (aplica 0010→0012 una por una, cada una en su transacción). Ventana: el trigger de 0011/0012 espera a las escrituras en curso sobre `assignment` (lock de tabla breve); programar fuera de turno de captura o con `lock_timeout` corto y reintento.
6. Verificar: `migrate.py --check` limpio, `validate_assignment_single_mode` y `validate_assignment_exclusivity` habilitados (preflight sección 1).
7. `preflight-startup` → `activate <sha>` → `systemd restart` → `healthcheck`.
8. **Pruebas de humo con la compuerta APAGADA** (§6).
9. Observación (mínimo un turno completo) antes de cualquier habilitación.

## 3. Backups e integridad

- `backup.sh` antes del paso 5; guardar checksum y fecha del respaldo, y probar la restauración fuera de producción.
- Antes y después de migrar: recuento de `assignment`, `capture`, `work_order_line` y suma de verificación de `to_jsonb(assignment)`; deben coincidir (0012 no toca filas; 0010 solo rellena `machine_id`).
- Auditoría: confirmar que el relleno de 0010 dejó un evento por fila con el motivo `MF13-03B PR1 backfill…`.

## 4. Preflight SQL de solo lectura

`backend/preflights/mf13_03b_predeploy_readonly.sql` (probado en lectura estricta: `SET TRANSACTION READ ONLY`) y `backend/preflights/0012_assignment_single_mode_preflight.sql`. Cada sección devuelve filas **solo** si requiere decisión humana:
1. versión de migraciones (esperado 12 | 12 | `O`);
2. **requisito de PR5:** operadores/Calidad activos sin ninguna concesión máquina-formulario (con la compuerta encendida dejarían de ver máquinas);
3. máquinas con varias asignaciones activas;
4. estados imposibles (línea sin máquina, línea activa dos veces, máquina con dos OT);
5. asignaciones activas de otro turno o fecha operativa.

## 5. Habilitación progresiva (el flag NO es lo primero)

La compuerta es una variable del backend (global; no por OT ni por máquina). Se enciende solo con autorización expresa, **en este orden**:

| Etapa | Acción | Condición de salida |
|---|---|---|
| 0 | Despliegue con compuerta APAGADA (§2) | Humo apagado OK + un turno de observación sin incidentes |
| 1 | Conceder (por Administración) las concesiones máquina-formulario que falten a **todos** los operadores activos (preflight 2) | Preflight 2 sin filas |
| 2 | (Opcional, antes del flag) `AUTHZ_ASSIGNMENT_READS_MODE=observe` para medir qué se ocultaría, sin cambiar respuestas | Sin ocultamientos inesperados |
| 3 | Encender `WORK_ORDERS_MULTI_MACHINE_ENABLED=true` en el entorno de **laboratorio/piloto aislado**, reiniciar, correr el humo encendido | Humo encendido OK |
| 4 | Producción: encender fuera de turno de captura, con Supervisión presente; primera OT multimáquina de una sola OT y dos líneas | Capturas correctas por línea; sin 409/422 inesperados |
| 5 | Ampliar uso; **no** activar modos `AUTHZ_*` `enforce` como parte de esto (decisión aparte) | — |

Reversión del flag: apagar y reiniciar. Con varias activas heredadas el backend responde 409 `MULTIPLE_ACTIVE_ASSIGNMENTS` hasta finalizarlas explícitamente (`finish`); nunca se finaliza nada por adivinación.

## 6. Pruebas de humo

**Compuerta apagada (tras el paso 7):** login de Jefatura/Supervisión/Operación; `GET /api/work-orders/capabilities` → `{"multi_machine": false}` (Jefatura/Supervisión; 403 para Operación); crear y publicar una OT de una sola máquina; activar una línea y luego otra (la primera se reemplaza); Operación ve su línea **sin selector** y captura F3; `activate-all` → 422 `MULTI_MACHINE_DISABLED`; ningún botón «Activar todas las líneas».
**Compuerta encendida (etapa 3/4):** OT con líneas en MP1 y MP3; vista previa y confirmación (una sola solicitud); Operación ve el selector con las líneas de su máquina, ninguna marcada; captura por línea con el `assignment_id` correcto; finalizar una línea y ver que Operación la pierde; una segunda OT en MP1 muestra conflicto y no se confirma.
Para ambas se reutiliza el recorrido automatizado `scripts/e2e/mm13-run.mjs` **en laboratorio** (nunca contra producción: crea su propio PostgreSQL).

## 7. Rollback

| Qué falló | Acción | Límite real |
|---|---|---|
| Backend nuevo (tras `activate`) | `rollback.sh version <sha-anterior>` (symlink atómico) | El backend anterior es compatible con 0010–0012 (verificado), así que **no hace falta revertir esquema** |
| Frontend | Reinstalar el artefacto anterior / `rollback.sh version` | — |
| Flag | Apagar y reiniciar | Estado heredado con varias activas → 409 hasta finalizar |
| 0012 | `backend/rollbacks/0012_…_rollback.sql` (sin precondición de datos) | La regla «una sola» vuelve a depender solo de la aplicación |
| 0011 | `backend/rollbacks/0011_…_rollback.sql` | **Rehúsa** mientras una máquina tenga 2+ activas (no finaliza nada por su cuenta) |
| 0010 | `backend/rollbacks/0010_…_rollback.sql` | Solo antes de que alguna línea use una máquina distinta de la de su OT |
| Datos | Restaurar el backup | Pierde lo escrito después del backup; último recurso |

## 8. Matriz GO / NO-GO

| # | Condición | GO si | NO-GO si |
|---|---|---|---|
| 1 | Suite backend completa | Sin fallos nuevos frente a `main` (19 heredados conocidos) | Un fallo nuevo |
| 2 | E2E de navegador (laboratorio) | Todo verde salvo defectos documentados y aceptados | Un fallo no documentado |
| 3 | Backup verificado y restaurado en base descartable | Sí | No |
| 4 | Preflight SQL revisado | Sin estados imposibles; decisiones tomadas sobre filas 2, 3 y 5 | Estado imposible o decisión pendiente |
| 5 | Orden de despliegue | Migrar **antes** de activar el backend nuevo | Se pretende activar primero |
| 6 | Compuerta | Apagada en el despliegue inicial | Se enciende en el mismo cambio |
| 7 | Concesiones de operadores (etapa 1) | Preflight 2 sin filas | Hay operadores activos sin concesión |
| 8 | Defectos conocidos de la QA (ver informe) | Aceptados explícitamente o corregidos | Sin decisión |
| 9 | Rebobinado/Conversión | Equipos informados de que con varias activas ven 409 (no hay selector) | Se espera selector en esos frentes |
| 10 | Autorización del administrador del VPS y de TVC | Por escrito, fase por fase | Falta |

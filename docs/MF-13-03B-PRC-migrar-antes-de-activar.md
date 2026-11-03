# MF13-03.B PR-C — migrar el release nuevo ANTES de activarlo (OBS-2)

Base: `origin/main` dc19572 (merge de PR #113). Solo scripts de despliegue, pruebas y documentos; **no cambia código de aplicación ni esquema**. No se ejecutó ningún despliegue, no se aplicó ninguna migración fuera de bases efímeras, no se tocó la VPS, `vinto_piloto`, TVC, ETL, Nginx ni flags.

## 1. Diagnóstico (Fase A)

| Hallazgo | Evidencia |
|---|---|
| `deploy.sh migrate` corre desde `current` (el release **ya activo**) y solo ejecuta `migrate.py --check`; aplicar es manual (`migrate.py` a mano) | `phase_migrate` (`release_dir="$APP_DIR/current"`) |
| **La guarda de `activate` miraba el release equivocado.** `activate` sí llamaba a `assert_schema_migrated` antes de conmutar `current`, pero esa función ejecuta el `migrate.py` de `current`, o sea del release **anterior**. Un release nuevo con migraciones sin aplicar pasaba la guarda y se activaba sobre un esquema insuficiente | `lib_common.sh::assert_schema_migrated` (`release_dir=".../current"`); la suite `test_activate_hardening.sh` fijaba ese comportamiento (el simulador de esquema vivía en `OLD_SHA`) |
| La guarda solo se aplica con unidades systemd instaladas (primera instalación: no reinicia nada) | `phase_activate` (`units_installed`) |
| `rollback.sh version` no consulta el esquema (conmuta symlink y reinicia) | `rollback_version` no referencia `migrate` |
| Privilegios: `migrate.py --target dev` usa `MIGRATOR_DATABASE_URL` en `PG_PRIVILEGE_MODE=hardened` (rol `vinto_migrator`, propietario de los esquemas), nunca la cuenta de la API (`vinto_app`); se ejecuta como `$SERVICE_USER` con `backend/.env` enlazado a `shared/backend.env` | `migrate.py`, `resolve_role_url`, comentarios de `phase_migrate` |
| Mecanismos de `migrate.py`: candado advisory de sesión (se niega si otra ejecución migra), **una transacción por migración**, SHA-256 sobre SQL con LF, `validate_history` detecta huecos, duplicados, archivos aplicados modificados y versiones aplicadas ausentes del checkout; sin downgrade | `backend/migrate.py`, `backend/migrations/README.md` |
| Compatibilidad **backend anterior ↔ esquema 0010–0012** | Verificada (ver §3.3): 328 pruebas del backend anterior pasan sobre ese esquema |

## 2. Cambios (Fase B)

- **`deploy.sh check-release <sha>`** (nuevo, **solo lectura**, sin `CONFIRM`): `migrate.py --status` del propio release. Salida `0` el esquema basta, `2` faltan migraciones (las lista y sugiere el siguiente paso), `1` error o historial divergente.
- **`deploy.sh migrate-release <sha>`** (nuevo): `CONFIRM=yes` y `AUTHORIZED_COMMIT=<sha>` exacto (mismo patrón que `checkout`); candado compartido con `activate`/`rollback`; exige un release **preparado** (venv + uvicorn, build del frontend, `backend/.env`, migraciones) y se detiene **antes de tocar la base** si no lo está; diagnóstico de solo lectura primero (si el historial diverge, no aplica nada); aplica lo que falte con el `migrate.py` y los archivos **del propio release**, como `$SERVICE_USER` y desde su directorio; verifica con `--check` al terminar; **no** cambia `current`, **no** reinicia systemd, **no** activa backend ni frontend; idempotente.
- **Guarda de `activate`:** `assert_schema_migrated "$release_dir"` (release **destino**), antes de conmutar `current`. Sin argumento conserva el comportamiento anterior (`postgres-grants`, `systemd-install`). Un release que conoce *menos* migraciones que la base (volver atrás con `activate`) queda rechazado; se vuelve atrás con `rollback.sh version`.
- Sin mecanismo de privilegios nuevo: reutiliza `sudo -u $SERVICE_USER` + `backend/.env`, como `migrate`.
- **Preflights SQL separados** (el previo no puede consultar objetos de 0010–0012): `backend/preflights/mf13_03b_preflight_before_migrate.sql` (solo objetos anteriores a 0010; probado sobre una base con 0001–0009) y `mf13_03b_verify_after_migrate.sql` (el consolidado anterior, renombrado; falla si se ejecuta antes de migrar).
- Documentación: `deploy/mvp/README.md` (sección de actualización) y `docs/MF-13-03B-plan-de-despliegue.md` reescrito con las cinco etapas separadas, el corte entre migración y activación, rollback y matriz GO/NO-GO.

## 3. Pruebas aisladas (Fase C)

### 3.1 `backend/tests/test_deploy_release_migrations.py` (19 pruebas, OK; más la del preflight consolidado en `test_qa_integral_multimachine`)
Ejecuta **las fases reales de `deploy.sh`** con el **`migrate.py` real** de un release simulado sobre **PostgreSQL efímero** (`*_test`, creado y borrado por la prueba). `sudo` se sustituye por un shim que ignora `-u` (así que **la separación real de usuarios NO se prueba aquí**, la cubre §3.2); `systemctl` es un shim que registra llamadas y no debe recibir ninguna.

| Caso pedido | Prueba |
|---|---|
| 1 Base actualizada | `check-release` → 0; `migrate-release` → «Nada que aplicar»; filas de `schema_migration` idénticas |
| 2 Con pendientes | `check-release` → 2 y lista 0010–0012; sin `CONFIRM` / sin o con `AUTHORIZED_COMMIT` equivocado / SHA corto → nada se aplica |
| 3 Checksum incorrecto | checksum alterado en la base, y archivo de migración editado en el release → exit 1 «modificada», nada se aplica |
| 4 Error durante una migración | `0013` sintética con `SELECT 1/0`: 0010–0012 quedan aplicadas, 0013 no se registra y su DDL parcial se revierte; `current` y systemd intactos |
| 5/6 Ya aplicada / repetida | segunda ejecución → «Nada que aplicar», `applied_at` sin cambios |
| 7 Activar con esquema antiguo | la guarda rechaza el release nuevo sobre esquema 0009; **la guarda antigua (sobre `current`) lo dejaba pasar** (prueba que documenta el defecto); acepta cuando está migrado; `activate` pasa el release destino y la guarda va antes de conmutar `current` |
| 8 Migrar sin activar | `current` sin cambios, ninguna llamada a `systemctl` |
| 9 Recuperación | se corrige la migración fallida y el **mismo** comando aplica solo lo que falta |
| 10 Rollback de aplicación sin revertir esquema | el release viejo sobre esquema nuevo → `check-release` exit 1 remitiendo a `rollback.sh version`; `rollback_version` no referencia `migrate.py`; el esquema no se revierte |
| Otros | release no preparado o inexistente → exit 1 antes de tocar la base; usa los archivos del release (no los de `current`); preflight previo corre sobre esquema 0009 y sobre 0012; el posterior **falla** antes de migrar (por eso están separados) y pasa después |
Mutaciones: guarda de nuevo sobre `current` → falla; `migrate-release` sin la autorización exacta → falla.

### 3.2 `deploy/mvp/scripts/tests/test_activate_hardening.sh` (52/52, con usuarios reales)
Contenedor Ubuntu desechable, `testop` (invoca, con sudo) y `testsvc` (sin privilegios). Los 45 casos previos siguen pasando tras mover el simulador de esquema al release destino; **7 casos nuevos (46–52)**: `migrate-release` ejecuta `migrate.py` **como `testsvc`, desde `releases/<sha>/backend`, con el venv de ese release** (tres llamadas: `--status`, aplicar, `--check`) y `current` intacto; sin `CONFIRM`/`AUTHORIZED_COMMIT` no se ejecuta nada; historial divergente se detiene sin aplicar; fallo al aplicar no verifica ni activa; `check-release` es de solo lectura sin `CONFIRM`; `activate` ignora el estado del release anterior y exige el destino; destino con esquema insuficiente → `current` intacto y sin reinicios. `shellcheck` (nivel warning) sin hallazgos antes ni después.

### 3.3 Compatibilidad del backend anterior con 0010–0012
Se tomó el **último commit anterior a MF-13-03B (45f0c25, esquema 0009)** en un worktree aparte y se ejecutaron 12 módulos de pruebas de asignaciones, OT y capturas (328 pruebas): **control** sobre su propio esquema → OK; **con las migraciones 0010, 0011 y 0012 copiadas** (esquema final) → **OK, 0 fallos**. Es decir, migrar antes de activar deja al backend en servicio funcionando. Límite: es una batería de pruebas, no tráfico real; las diferencias de SQLSTATE en escrituras directas por SQL (23505 → 23P01) no las ejerce ese código.

### 3.4 Antes de PR-C (Fase C, ítem 7, hallazgo adicional)
La suite existente fijaba la semántica defectuosa («el chequeo corre sobre `current`»); se actualizó para que el simulador de esquema viva en el release destino y se agregaron los casos 51–52.

## 4. Riesgos y límites

1. **La cadena completa con usuarios reales + `migrate.py` real + PostgreSQL real no se ejecutó en una sola prueba**: cada mitad se prueba por separado (§3.1 y §3.2). El simulador de `python` de §3.2 reproduce las salidas y códigos de `migrate.py`, pero no es el programa real.
2. **No se ejecutó nada en la VPS** (ni systemd real, ni permisos reales de `vinto-mvp`/`vinto_migrator`): queda para la validación autorizada.
3. `migrate-release` y `check-release` leen la base con el mismo rol que `migrate` (propietario); el rol exacto de producción no se verificó aquí.
4. `activate` ahora rechaza activar un release más viejo que la base: es intencional (usar `rollback.sh version`), pero cambia el comportamiento previo para quien usara `activate` para retroceder.
5. Un corte durante `migrate-release` deja las migraciones ya completadas aplicadas (por diseño de `migrate.py`); repetir el comando continúa.
6. Los finales de línea del checkout de Windows (CRLF) rompen los scripts en Linux: las pruebas los normalizan; el repositorio guarda LF.

## 5. Recomendación de merge
**GO** para fusionar PR-C: corrige el hueco de activación sobre un esquema insuficiente, sin cambiar código de aplicación ni esquema, con pruebas que fallan sin el arreglo. No sustituye la validación en el VPS real, que sigue pendiente y requiere autorización.

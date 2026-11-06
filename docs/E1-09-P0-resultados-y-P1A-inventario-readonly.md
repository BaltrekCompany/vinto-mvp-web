# VINTO E1-09 — P0 validado y P1-A inventario de respaldo (SOLO LECTURA)

**Corte informado:** 06/nov/2026, hora de Bolivia. **Estado:** P0 PASS para preparar P1, P1-A diseñado pero **NO EJECUTADO**.  
**Evidencia:** resultados agregados entregados por el ejecutor remoto mediante la conversación; no hubo SSH directo desde ChatGPT.  
**Alcance:** `vinto-mvp-postgres`, `vinto_piloto`, rol `vinto_app`; TVC fuera de alcance.

## A. P0 — resultados recibidos

| Control | Resultado informado | Alcance real |
|---|---|---|
| Release activo VPS | PASS `86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4` | `/opt/vinto-mvp-web/current` apunta al release previo a E1 |
| Servicios | PASS | `vinto-mvp-backend.service` y `vinto-mvp-frontend.service` loaded / active / running |
| PostgreSQL MVP | PASS | `vinto-mvp-postgres`, imagen `postgres:17`, proyecto Compose `vinto-mvp`, servicio `postgres`; running / healthy |
| Migración 0013 | Ausente (esperado) | Sin archivo SQL en release ni `vinto_txn.work_order_line_execution` en catálogo. **No** significa lista para E1 |
| Flag de línea | No configurado en proceso antiguo | Ni variable `WORK_ORDER_LINE_EXECUTION_ENABLED` en proceso ni referencia en código anterior; **no extrapolar** al nuevo release |
| Lectura de permisos | Parcial PASS | `vinto_app` puede leer tablas de grants; condiciones básicas activas, pero no se probó elegibilidad efectiva por perfil/formulario/operación |
| Base y mapeo | PASS | 12 OT `in_progress`, 16 baseline, 11 asignaciones activas, mapeo 11/11; 0 sin baseline / ambiguas / origen no operacional |
| Cinco líneas sin activa | PASS histórico | BOBINAS MP1:4 y MP3:1, todas con `assignment.finished`; ninguna sin historial |
| Actividad P0 frente SQL-E | Cero en campos revisados | SQL-E 09:13:23 → P0 09:49:15 (hora Bolivia); 0 capturas creadas/recibidas/enviadas/actualizadas, 0 OT o asignaciones nuevas/actualizadas. No demuestra identidad de filas sin una comparación individual no publicada |
| `vinto_meta` | NO VERIFICADO | Rol restringido; no otorgar nuevos grants |
| Respaldo recuperable | NO VERIFICADO | No se ejecutó `backup.sh create`, `verify` ni `create-and-verify` |

**Grants básicos**: sector: BOBINAS 5/5 activos, CONVERSION 3/3, REBOBINADO 4/4. Máquina: MP1 4 activas, 1 revocada; MP3 8 activas; GAMBINI 3; OMET_I 2. Las concesiones de máquina NO son necesariamente usuarios distintos. No concluir cobertura efectiva de todos los formularios/rutas desde estos conteos.

**Decisión P0:** GO únicamente para **preparar** P1. NO-GO para modificar, respaldar, migrar, resetear datos, desplegar o activar E1.

## B. Qué debe comprobar P1-A antes de cualquier respaldo

El script real de GitHub `deploy/mvp/scripts/backup.sh` usa por defecto:
- Carpeta `/home/ubuntu/vinto-mvp-backups`, **directorio regular existente**, propietario = usuario ejecutor y permiso exactamente `700` (según `lib_common.sh::assert_private_dir`).
- Mínimo de espacio libre de `500 MB` (según `VINTO_MVP_BACKUP_MIN_FREE_MB` por defecto). **Es un mínimo defensivo, no garantía suficiente** para dump + verificación de restauración. Los volúmenes pueden ocupar sistemas de archivos distintos: backup y Docker root.
- Base `vinto_piloto`, imagen `postgres:17`; identifica contenedor por nombre/etiqueta/imagen antes de crear backup.
- `create-and-verify` hace dump y manifiesto en snapshot MVCC consistente, checksums y restauración efectiva en contenedor efímero `--network none`, luego compara tablas contra manifiesto. **Esta operación escribe archivos y crea/borrará un contenedor; NO forma parte de P1-A.**
- `list` usa `assert_private_dir` y solo enumera; la presencia de `.verified` por sí sola **no sustituye** revalidación y contexto correcto.
- `rollback.sh version` vuelve a código anterior y reinicia servicios; **no** revierte migración 0013 ni restaura la base.

### P1-A — comandos de diagnóstico, sin mutaciones

Ejecutar únicamente dentro de la sesión SSH autorizada para MVP. El operador debe revisar el contenido y el alcance antes de pegar. **No ejecutar** `backup.sh create`, `verify`, `create-and-verify`, `prune-apply`, `deploy.sh`, ningún `sudo` mutador ni `mkdir/chmod`. No mostrar `.env`, variables de contraseña, `docker inspect .Config.Env`, ni rutas de datos individuales.

```bash
set -euo pipefail
OPS=/home/ubuntu/vinto-mvp-ops/scripts
BACKUP_DIR=/home/ubuntu/vinto-mvp-backups

echo "=== Identidad y sintaxis de scripts (lectura) ==="
test -f "$OPS/backup.sh"
test -f "$OPS/lib_common.sh"
bash -n "$OPS/backup.sh"
bash -n "$OPS/lib_common.sh"
sha256sum "$OPS/backup.sh" "$OPS/lib_common.sh"

echo "=== Overrides sin revelar sus valores ==="
if [ -n "${VINTO_MVP_BACKUP_DIR+x}" ] || [ -n "${VINTO_MVP_BACKUP_DB+x}" ] || [ -n "${VINTO_MVP_BACKUP_MIN_FREE_MB+x}" ]; then
  echo "P1A_NO_VERIFICADO: variables de override presentes; confirmar alcance sin imprimir secretos."
  exit 1
fi

echo "=== Capacidad del filesystem de respaldo (solo lectura) ==="
df -Pm /home/ubuntu
df -Pi /home/ubuntu
if [ -L "$BACKUP_DIR" ]; then
  echo "P1A_BLOQUEADO: carpeta de backup es symlink"; exit 1
elif [ -d "$BACKUP_DIR" ]; then
  stat -c 'tipo=%F propietario=%U permisos=%a' "$BACKUP_DIR"
  actual_owner="$(stat -c '%U' "$BACKUP_DIR")"
  actual_perms="$(stat -c '%a' "$BACKUP_DIR")"
  if [ "$actual_owner" != "$(id -un)" ] || [ "$actual_perms" != "700" ]; then
    echo "P1A_BLOQUEADO: propietario/permisos del directorio no cumplen el contrato"; exit 1
  fi
  df -Pm "$BACKUP_DIR"
  df -Pi "$BACKUP_DIR"
  du -sm "$BACKUP_DIR"
  echo "conteo_dump=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.dump' -printf '.' | wc -c)"
  echo "conteo_verified=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.verified' -printf '.' | wc -c)"
  echo "conteo_corrupt=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.CORRUPT' -printf '.' | wc -c)"
else
  echo "P1A_NO_VERIFICADO: la carpeta backup por defecto no existe; NO crearla en esta fase"
fi

echo "=== Capacidad del filesystem de Docker (solo lectura) ==="
DOCKER_ROOT="$(docker info --format '{{.DockerRootDir}}')"
if [ -d "$DOCKER_ROOT" ]; then
  df -Pm "$DOCKER_ROOT" || echo "P1A_NO_VERIFICADO: capacidad Docker no accesible"
  df -Pi "$DOCKER_ROOT" || true
else
  echo "P1A_NO_VERIFICADO: Docker root no accesible sin elevar privilegios"
fi
```

Si el directorio de backups presenta permisos/propietario incorrectos, **detener P1-A** y reportar, sin corregir automáticamente. Si algún comando falla (con `set -e`), informar en qué control se detuvo; no añadir `sudo` para sortearlo.

### P1-A — tamaño agregado de la base (solo lectura, mismo contenedor/rol)

En la misma sesión SSH, únicamente si la identidad del contenedor MVP coincide con la de P0 y sigue saludable:

```bash
docker exec -i vinto-mvp-postgres psql -X -w -U vinto_app -d vinto_piloto -v ON_ERROR_STOP=1 <<'SQL'
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '10000ms';
SET LOCAL lock_timeout = '1000ms';
SELECT 1 / CASE WHEN current_database()='vinto_piloto'
                 AND current_user='vinto_app'
                 AND current_setting('transaction_read_only')='on'
                 AND to_regclass('vinto_txn.work_order_line_execution') IS NULL
                THEN 1 ELSE 0 END AS identidad_pre_e1;
SELECT pg_database_size(current_database())::bigint AS tamanio_db_bytes;
COMMIT;
SQL
```

No imprimir nombres de tablas, OT, registros individuales ni credenciales. La consulta de `pg_database_size` es una aproximación del volumen vivo: **no predice** exactamente el tamaño comprimido de `pg_dump` ni el espacio temporal de la restauración. Para P1-B es necesario acreditar espacio real suficiente, considerando ambos filesystems, antes de autorizar ejecución.

## C. Resultado solicitado de P1-A

Entregar **solo**: SHA-256 de los dos scripts del directorio Ops (o validación contra fuente versionada), `bash -n` PASS/FAIL, carpeta backup: existe/symlink/propietario/permisos/volumen agregado, número de dumps/marcadores `.verified`/`.CORRUPT`, espacio libre MB e inodos del backup FS, Docker-root espacio libre MB e inodos, tamaño de `vinto_piloto` en bytes/MB, y cualquier `NO VERIFICADO`. No publicar rutas de backups individuales, archivos sensibles, variables de contraseña ni dumps.

### Condición para preparar P1-B (solicitar autorización antes de ejecutarlo)

- El script local debe corresponder a una revisión confiable e íntegra; directorio privado `700`, propietario ejecutor, libre de symlink.
- Comprobar suficiente espacio en ambos filesystems, más margen razonable sobre el volumen estimado; `500 MB` por defecto no demuestra capacidad suficiente.
- Verificar aislamiento estricto de TVC y que ningún backup anterior será sobrescrito o podado.
- Definir el backup requerido y aceptar que la verificación usa Docker efímero; se necesita autorización separada antes de `CONFIRM=yes bash backup.sh create-and-verify`.
- P1-B no incluye migración 0013, cambios de flags, desplegar, reiniciar, borrar ni manipular datos de pruebas.

**Dictamen vigente:** P0 PASS; P1-A READ ONLY POR EJECUTAR; P1-B NO AUTORIZADO; migración/deploy/flag ON NO-GO.

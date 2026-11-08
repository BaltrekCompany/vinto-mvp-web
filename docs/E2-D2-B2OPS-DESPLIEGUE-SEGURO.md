# E2-D2-B2-OPS — activación, rollback y bandera (GO/NO-GO)

**Estado:** diseño ejecutable en scripts de VINTO MVP, NO autorización para producción. `WORK_ORDER_REPROGRAM_HANDOFF_ENABLED` permanece OFF en VPS. No cambiar E2-D1, TVC, ETL ni los demás servicios.

## Contrato de protección

Los scripts de operador `deploy/mvp/scripts/{lib_common.sh,deploy.sh,rollback.sh}` comparten la función `d2_ops_gate`, ejecutada con el mismo `flock` exclusivo que serializa `activate` y `rollback.sh version`. Siempre valida el estado real de PostgreSQL mediante el preflight **solo lectura** `app.work_orders.handoff_rollout_cli` y la identidad `vinto-mvp`; no imprime ni pasa credenciales por argv.

**Identidad de base de datos:** el preflight necesita consultar el historial `vinto_meta.schema_migration`; `vinto_app` no tiene, ni debe recibir, USAGE sobre `vinto_meta`. El CLI utiliza `MIGRATOR_DATABASE_URL` cuando está definida, mediante el resolvedor de identidades existente. En `PG_PRIVILEGE_MODE=hardened` la exige y falla cerrado si falta; en `legacy` el fallback antiguo a `DATABASE_URL` puede fallar por permisos, lo cual es **NO-GO**, no un motivo para dar permisos a `vinto_app`. La sesión SQL está limitada a `REPEATABLE READ READ ONLY`. No pasar URLs ni claves en comandos.

| Operación | Lugar del gate | Resultado con pending/published/reassigned |
| --- | --- | --- |
| `deploy.sh activate <SHA>` | **Antes** de crear `current.tmp` o mover `current` | NO-GO |
| Rollback automático por falla healthcheck | Inmediatamente **antes** de revertir `current` | NO-GO, deja el nuevo release activo y requiere investigación |
| `rollback.sh version <SHA>` | Antes de conmutar `current` | NO-GO |
| `deploy.sh d2-gate disable` | Diagnóstico independiente, solo lectura | NO-GO |
| `deploy.sh d2-gate enable` | Diagnóstico independiente, solo lectura | NO-GO |

El preflight verifica hashes exactos de migraciones 0019–0022, trigger E1 habilitado y **cero** handoffs abiertos. Falla cerrado si la BD está inaccesible, el runner no está disponible o el destino es incompatible con la variable D2 del `.env`. Una operación con resultado GO **no concede por sí sola permiso de despliegue ni modifica la bandera**.

### Primera instalación de B2 desde E2-D1

En el primer corte, el release activo E2-D1 **no contiene** el CLI D2. La función usa el CLI del release candidato **solo si se instaló correctamente**. En consecuencia, los pasos requeridos son: checkout/venv/artefacto, backup y ensayo de restauración, aplicación controlada de migraciones `0019–0022`, `check-release` PASS, después `activate` protegido; D2 sigue OFF. No ejecutar `d2-gate enable` antes de que el release compatible quede activo.

Cuando **ni el release activo ni el destino** contengan la migración `0019`, el gate ejecuta igualmente un probe PostgreSQL de solo lectura a través del Python del release activo: comprueba si hay una tabla de handoffs heredada y rechaza si existen reservas abiertas o la base no responde. Solo en una primera instalación **sin release activo** admite el camino legado sin probe (todavía no puede existir un escritor D2). Si alguno contiene escritor D2 pero no hay CLI confiable, el gate se niega a continuar. El rollback a un release que **no conoce** la variable `WORK_ORDER_REPROGRAM_HANDOFF_ENABLED` se rechaza si dicha clave existe en `shared/backend.env`, incluso cuando no hay handoffs.

### Instalar realmente los scripts OPS (no automático)

**El merge de GitHub no actualiza los scripts ya copiados en `/home/ubuntu/vinto-mvp-ops/scripts`.** Antes de habilitar D2 se exige instalar `deploy.sh`, `rollback.sh` y `lib_common.sh` **como paquete indivisible**, con el mismo SHA comprobado en el release y con respaldo del paquete anterior. No reemplazar un solo archivo. El instalador autorizado debe verificar propietario, permisos, huellas SHA256, sintaxis `bash -n` y disponibilidad del candado; ejecutar `deploy.sh d2-gate rollback` como ensayo de solo lectura, luego pruebas de `activate`/rollback contra datos sintéticos.

Durante la instalación, no hay que cambiar `current`, `.env`, migraciones ni servicios. No introducir una mezcla de scripts nuevos y antiguos en un host con D2 activo.

### Apagado de bandera y recuperación

La ruta aprobada de control es `bash deploy.sh d2-gate disable` y luego un cambio de configuración autorizado, con verificación posterior de procesos/DB y segunda comprobación del gate. **El comando es solo lectura:** no cambia `.env` ni reinicia systemd. Un cambio directo por editor o panel que omita el gate NO está protegido automáticamente por el script OPS; por ello no es un procedimiento aprobado. Incluso si alguien deshabilita la bandera con handoffs abiertos, el backend conserva las guardas y el trigger SQL de E1 bloquea el inicio, pero eso NO es una autorización de downgrade.

Cuando existan handoffs abiertos: `pending` se cancela por Supervisión con motivo; `published` se termina con reasignación supervisada; `reassigned` se completa con el acuse exacto del operador para la versión y asignación nueva. No borrar versiones ni asignaciones anteriores. Repetir el preflight hasta cero y comprobar turnos, permisos y E1.

## Alcance real y limitaciones

- **No hay pausa transaccional de nuevas reservas HTTP** entre preflight y reinicio. `flock` serializa scripts de operador, no solicitudes API: la verificación debe ejecutarse durante una ventana operativa sin nuevos relevos y repetirse después del cambio.
- El rollback automático bloqueado por handoffs puede dejar el release nuevo sin healthcheck válido: exige intervención de soporte, no degradación silenciosa.
- `rollback.sh systemd/postgres/all` son procedimientos de parada ante incidentes, distintos de `rollback.sh version`. No sustituyen la reversión segura de código.
- El preflight D2 no detecta otros posibles problemas de compatibilidad ajenos a D2. Necesita respaldo, pruebas integrales PostgreSQL 17 y QA manual.
- No habilitar D2 hasta verificar en VPS el paquete OPS realmente instalado, un release B2 con migración `0022`, pruebas de concurrencia F3/F6/acuse/E1 y aprobación funcional.

## Criterios mínimos de aceptación de B2-OPS

1. Pruebas shell aisladas: legado/legado, legado/B2, B2/legado, handoffs abiertos, BD no disponible, runner ausente, destino incompatible; orden de gate antes de symlink.
2. Pruebas PostgreSQL17 reales: datos cero/abiertos, acuse y consolidación, integridad de migración/trigger, sin identificadores sensibles.
3. QA manual de recuperación y reversión en VPS **sin datos reales**, respaldo restaurable y ventana controlada.
4. Demostrar que el release de producción realmente ejecuta scripts OPS revisados y que D2 continúa OFF tras desplegar.

Último resultado verificable en GitHub no equivale a autorización productiva.

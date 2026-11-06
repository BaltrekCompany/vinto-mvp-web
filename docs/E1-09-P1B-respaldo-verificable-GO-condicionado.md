# VINTO E1-09 — P1-B: respaldo nuevo y restauración verificable

**Fecha:** 06/nov/2026. **Estado actual:** **P1-B COMPLETADO — PASS** según informe remitido por el ejecutor SSH. Se conserva el procedimiento y los NO-GO históricos para trazabilidad.  
**Fuente de evidencia P1-A:** resultados agregados remitidos por operador SSH; no se usó SSH desde ChatGPT.  
**Código de referencia:** `main@a8a8beaf611e8d892658eeabb5a5e1b972a32316`; VPS sigue en release `86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4` según P0.  
**Referencia:** [P0 y P1-A](E1-09-P0-resultados-y-P1A-inventario-readonly.md).

## RESULTADO FINAL — P1-B PASS (2026-11-06)

**Evidencia entregada por Codex Desktop/operador SSH; ChatGPT no ha entrado directamente al VPS.** Se ejecutó **una sola vez** `CONFIRM=yes VINTO_MVP_BACKUP_MIN_FREE_MB=1024 bash backup.sh create-and-verify` y terminó con **exit 0**.

| Evidencia | Resultado informado |
|---|---|
| Nuevo respaldo | `vinto-mvp-vinto_piloto-20261106-154402-3915284.dump` |
| SHA-256 del dump | `4ea5aa54a8ebfc579d6703683e7252efe0acd432615072e39a0319a3b29b97a3` |
| SHA-256 del manifiesto | `0cab974da88b70d3721c8da1ee0885938dc1ca2e9b434717fbe3502dd7f4b363` |
| Checksums de ambos | PASS |
| Marcador nuevo `.verified` | PASS |
| Restauración aislada | PASS, en contenedor temporal PostgreSQL `--network none` |
| Conciliación del manifiesto | **47 tablas comparadas, 0 discrepancias** |
| Contenedores de verificación restantes | 0 |
| Integridad respaldos anteriores | 18 dumps anteriores conservados; resumen criptográfico previo/posterior idéntico (`bf443da5…58d509e`) |
| Inventario después | 19 dumps, 19 marcadores `.verified`, 0 `.CORRUPT`, 0 `.partial` |
| Servicios MVP | Backend y frontend activos; `vinto-mvp-postgres` imagen `postgres:17`, Compose `vinto-mvp`, running/healthy |
| Credenciales | Consumo interno autorizado; valores no inspeccionados ni divulgados |
| Concurrencia adicional | Timer de respaldos de paquetes del SO inactivo, próximo 8 h después, ajeno a VINTO |
| Desviación no bloqueante | Una invocación aislada del helper de permisos requirió contexto `SCRIPT_DIR`; repetida con contexto correcto, PASS, sin modificar entorno |

**Criterio técnico P1-B cumplido.** La verificación comprueba que `pg_restore` concluyó y que los **recuentos por tabla** de la base restaurada coinciden con un manifiesto capturado en el mismo snapshot; **no equivale a una comparación byte a byte** de todos los registros, ni a una garantía frente a fallas del mismo disco. Los 19 respaldos están en el almacenamiento compartido de la VPS según el último inventario; residencia fuera del host **NO VERIFICADA**.

**Decisión:** cerrar **P1-B PASS**; autorización consumida, **no repetir** `create-and-verify` sin nuevo objetivo y aprobación. Preparar **P2-A solo lectura**, que evalúe la migración 0013, compatibilidad y tratamiento de datos históricos simulados. **NO-GO para P2-B (aplicar 0013), activación de flag, despliegue E1, modificación de simulados o TVC**. Los apartados posteriores describen decisiones y procedimientos previos a este cierre y se conservan como historial.

## AUTORIZACIÓN VIGENTE — P1-B autorizado, pendiente de ejecutar (06/nov/2026)

El usuario respondió **«Autorizo»** a la solicitud explícita de **retomar P1-B con el script corregido**, revalidando primero las condiciones del VPS y ejecutando **una sola vez** `create-and-verify`. Esta aprobación se añade a la autorización previa de uso **interno programático** de credenciales existentes de `docker/.env` por `backup.sh` exclusivamente para autenticación, sin inspección manual ni exposición de valores.

**Estado real al registrar la aprobación:** script Ops PR #136 instalado PASS según Codex; respaldo P1-B **AUTORIZADO PERO NO EJECUTADO** en esta conversación (ChatGPT no dispone de SSH al VPS). Los textos históricos posteriores que dicen "NO AUTORIZADO" describen el estado anterior y quedan superados **solo para P1-B** por este apartado. Mantener NO-GO si falla alguna guarda.

**Orden de ejecución a Codex Desktop, bajo SSH preautorizado:**

1. Antes de toda escritura, confirmar integridad de `backup.sh` instalado SHA-256 `53bbda26c74b46f3868f239e27385f64d7c7c3d363a4e90a7427fb02259d3a25`, `lib_common.sh` SHA-256 `31696d213baaf5436cc09766327ed6e1f53605802ffce970f89bb2813318c31b`, sintaxis Bash, `flock`, directorio regular `ubuntu:700`, contenedor exacto `vinto-mvp-postgres` healthy, imagen `postgres:17`, Compose `vinto-mvp`, base `vinto_piloto`.
2. Revalidar capacidad libre ≥1024 MiB en filesystem **compartido** del backup y Docker, inodos suficientes, overrides de ruta/base unset, sin scripts manuales/antiguos de respaldo no cooperativos en curso ni tareas futuras que puedan solaparse. Confirmar preflight de aislamiento TVC y política de no sobreescritura/poda. Ante desviación: **NO-GO, detener sin ejecutar**.
3. Permitir únicamente al script examinar los **valores de autenticación necesarios** en `docker/.env` internamente; **prohibido** imprimirlos, grabarlos o usar `set -x`. El contrato del archivo se verifica antes de acceder a valores.
4. Tras controles PASS, ejecutar **una vez**:
   ```bash
   cd /home/ubuntu/vinto-mvp-ops/scripts
   CONFIRM=yes VINTO_MVP_BACKUP_MIN_FREE_MB=1024 bash backup.sh create-and-verify
   ```
5. Verificar que el backup **nuevo** tiene marcador `.verified`, hashes/manifiesto válidos, restauración efectiva en Postgres efímero `--network none`, **0 discrepancias** en tablas, contenedor y contraseña temporal eliminados, servicios MVP saludables y backups previos intactos. Reportar datos agregados y el resultado PASS/FAIL. Si falla, detener sin reintentos automáticos.

**Esta autorización NO cubre:** restaurar sobre `vinto_piloto`, limpiar simulados, migración 0013, desplegar E1, modificar flags/grants/servicios ni tocar TVC. No avanzar a P2 aunque P1-B pase.

## ACTUALIZACIÓN MÁS RECIENTE — Bloqueos P1-B subsanados a nivel de script (06/nov/2026)

El usuario autorizó la integración del correctivo #136 y su posterior instalación Ops. **Codex Desktop informó instalación PASS**, reemplazando solo `/home/ubuntu/vinto-mvp-ops/scripts/backup.sh`: Git blob `5ae19d8a8db75bb61f8e67bd1159acfab684ddc3`, SHA-256 `53bbda26c74b46f3868f239e27385f64d7c7c3d363a4e90a7427fb02259d3a25`. Se conservó copia de rollback `backup.sh.pre-e1-09-20261106T153014Z` con SHA-256 previo `12151e680a2ef8dd400393794041c18adf4425bfd4ebfea38d5882e7b345738a`; `lib_common.sh` intacto (`31696d213baaf5436cc09766327ed6e1f53605802ffce970f89bb2813318c31b`). Sintaxis Bash PASS; sin anomalías. [Evidencia completa](E1-09-PR136-instalacion-controlada-Ops.md).

**Se cerraron los dos bloqueos procedimentales anteriores:**
1. El usuario **permitió el consumo interno programático de `docker/.env` por `backup.sh` solo para autenticación**. Prohibido inspeccionar valores manualmente, imprimir credenciales, exponerlas en logs/chat/GitHub, `set -x` o `docker inspect .Config.Env`.
2. La versión nueva del script **incluye `flock` exclusivo** para `create`, `verify`, `create-and-verify` y `prune-apply`; el ejecutor confirmó disponibilidad de `flock`. El candado no protege operadores antiguos que no lo usen: inspección operativa previa sigue siendo obligatoria.

**Estado:** instalación Ops PASS; P1-B **todavía NO ejecutado**. Los controles se revalidarán inmediatamente antes de una ejecución autorizada: script instalado SHA256 esperado, contenedor MVP saludable e idéntico, directorio 700, filesystem compartido con ≥1024 MiB e inodos suficientes, ausencia de operaciones externas sin lock, sin overrides de backup salvo `VINTO_MVP_BACKUP_MIN_FREE_MB=1024`, no sobrescritura/poda de los 18 respaldos previos.

**No reutilizar una autorización anterior como si la operación ya se hubiera ejecutado.** La instalación quedó deliberadamente separada de P1-B; solicitar nuevo GO explícito para ejecutar exclusivamente un `create-and-verify` tras revalidar sus guardas. La fase 0013, deploy y flag ON siguen NO-GO.

Las secciones antiguas siguientes preservan la explicación del NO-GO original como **historial**, no reflejan el estado del script instalado hoy.

## 0. ACTUALIZACIÓN OPERATIVA — P1-B NO-GO, no ejecutado (06/nov/2026)

El ejecutor SSH realizó las comprobaciones previas sin cambios y **detuvo correctamente P1-B antes de ejecutar create-and-verify** por dos conflictos de procedimiento:

1. **Acceso a secretos:** el mandato decía "no leer secretos", mientras que `backup.sh` requiere leer de manera programática `docker/.env` (variables de autenticación) para que `pg_dump` funcione. Una operación autenticada no puede realizarse bajo prohibición absoluta de *cualquier* lectura de credenciales. Se necesita autorización explícita para **consumo interno por el script**, manteniendo prohibición total de `cat/grep/echo/set -x` de secretos, exposición por terminal/logs/chat y lectura directa por el operador. Si el usuario no autoriza ni siquiera el consumo programático, **NO-GO definitivo para este procedimiento**.
2. **Concurrencia:** el script instalado en el VPS aún no implementa exclusión `flock`. Una comprobación puntual de procesos vacíos no garantiza que otro backup no arranque inmediatamente después. Se abrió [PR #136](https://github.com/BaltrekCompany/vinto-mvp-web/pull/136) con bloqueo exclusivo para `create`, `verify`, `create-and-verify` y `prune-apply`; la primera prueba de CI se corrigió por crear un lock de prueba modo 644 y la versión corregida **PASS** ([run #42240240275](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/42240240275)). El PR sigue DRAFT y **el código Ops del VPS no se ha actualizado**.

**Resultado de comprobaciones previas:** hashes y `bash -n` PASS, contrato de permisos `docker/.env` PASS sin leer contenido, directorio `700`, 18 dumps / 18 verified / 0 corrupt / 0 partial, 184,833 MiB libres y 25,735,732 inodos compartidos, contenedor correcto y saludable, 0 procesos concurrentes detectados en el instante de revisión. No hubo nueva lectura SQL ni backup/restore efímero.

**NO EJECUTAR todavía el comando de la sección 2.** Es una referencia de la solicitud original y requiere primero: revisar y aprobar PR #136, controlar su instalación y SHA final en `/home/ubuntu/vinto-mvp-ops/scripts`, verificar lock privado/mecanismo no-bypass en operadores y documentar autorización específica para uso programático (no exposición) de credenciales. Solo entonces revalidar preflight y repetir P1-B, sin dar por válido el GO anterior como autorización de cambios de scripts.

**Nada de lo anterior habilita migración 0013, limpieza de datos simulados, despliegue ni flag ON.**

## 1. Decisión derivada de P1-A

**GO condicionado para solicitar autorización explícita de P1-B**. El resultado P1-A muestra:
- `backup.sh` SHA-256 `12151e680a2ef8dd400393794041c18adf4425bfd4ebfea38d5882e7b345738a`.
- `lib_common.sh` SHA-256 `31696d213baaf5436cc09766327ed6e1f53605802ffce970f89bb2813318c31b`.
- Ambos coinciden con los objetos Git de `main`; `bash -n` PASS.
- Sin overrides para `VINTO_MVP_BACKUP_DIR`, `VINTO_MVP_BACKUP_DB` ni `VINTO_MVP_BACKUP_MIN_FREE_MB` en P1-A.
- Directorio `/home/ubuntu/vinto-mvp-backups` regular, propietario `ubuntu`, modo `700`, 41 MiB utilizados.
- 18 `.dump`, 18 `.verified`, 0 `.CORRUPT`; los marcadores no acreditan restaurabilidad actual sin una verificación de contenido.
- Backup FS y Docker root en el **mismo** `/dev/sda1` (no sumar dos reservas): 184838 MiB libres, 25735732 inodos libres.
- Base `vinto_piloto` con 50,271,923 bytes (~47.94 MiB). La capacidad supera ampliamente el margen propuesto de **1024 MiB**; verificar de nuevo antes de iniciar.

## 2. Qué hará y qué NO hará P1-B

**Única acción permitida tras autorización independiente:**

```bash
# SOLO DESPUÉS DE GO EXPRESO PARA P1-B, Y DE REVALIDAR LAS PRECONDICIONES
cd /home/ubuntu/vinto-mvp-ops/scripts
CONFIRM=yes VINTO_MVP_BACKUP_MIN_FREE_MB=1024 bash backup.sh create-and-verify
```

- Este comando **sí escribe** archivos nuevos `.dump`, `.manifest`, checksums y `.verified` en el directorio privado. Usa `pg_dump` con snapshot MVCC compartido con el manifiesto; **no modifica las tablas** de `vinto_piloto`.
- **Lee** las credenciales existentes desde `docker/.env` mediante funciones autorizadas que exigen permisos estrictos. Las credenciales no deben imprimirse, registrarse en GitHub ni compartirse por chat. Es una diferencia deliberada respecto de P1-A, donde se prohibió consultar `.env`.
- **Crea, inicia y elimina** un contenedor `postgres:17` efímero con `--network none`, CPU 1 y memoria 512 MiB. Restaura **solo** dentro de ese contenedor; no restaura en `vinto_piloto` ni en TVC.
- Compara recuentos por tabla con el manifiesto congelado, valida integridad SHA-256 y solamente al finalizar deja `<nuevo-dump>.verified`.
- Nunca sobreescribe un respaldo: nombres con fecha UTC y PID, colisión detectada y bloqueo. No ejecuta `prune`, `prune-apply`, `deploy.sh`, migración 0013, cambios de banderas, reinicios ni cambios de usuarios/datos.
- Una interrupción o fallo de restauración deja el respaldo nuevo sin garantía de validez; **no asumir PASS** si no aparece el nuevo `.verified`.

## 3. Preflight inmediato a cargo del ejecutor antes del comando mutador

Verificar con comandos de lectura, sin imprimir secretos:

1. El operador y los scripts son los previstos: `ubuntu`, rutas Ops exactas, hashes SHA-256 conocidos, `bash -n` PASS, sin cambios de HEAD ni scripts. Si cambia el SHA, **NO-GO**.
2. Contenedor `vinto-mvp-postgres` saludable y verificado por nombre/imagen/etiquetas Compose `vinto-mvp`; la base objetivo es `vinto_piloto`. No utilizar contenedores TVC, `postgres-vinto`, ni puerto 6543.
3. Directorio de backup regular no symlink, dueño `ubuntu`, permisos `700`; no modificar dueño/permisos durante el preflight.
4. Filesystem compartido `/dev/sda1` con al menos **1024 MiB libres** e inodos suficientes. El umbral es una red de seguridad, no garantía matemática de restaurabilidad; atención a presión de Docker/disk mientras corra.
5. Reconfirmar que los overrides de backup están ausentes; la única variable nueva explícita será el umbral de espacio mínimo `VINTO_MVP_BACKUP_MIN_FREE_MB=1024`. Si hay override de ruta o BD, detener.
6. Identificar que no hay otra ejecución simultánea de backup/restore/prune. No listar secretos ni procesos con argumentos sensibles.
7. Confirmar que la tarea no destruirá ni sobrescribirá backups previos (18 `.dump` y 18 `.verified` en el corte P1-A). Si los conteos cambian por actividad legítima, documentar nuevo baseline antes de actuar; no forzar 18.
8. Verificar que `docker/.env` cumple contrato de propiedad y permisos **mediante la función del script**. No usar `cat`, `grep` ni volcar sus valores.
9. Aceptar expresamente la creación de archivos y contenedor aislado. Si no hay GO de P1-B, **parar antes del comando**.

## 4. Evidencia de salida requerida

Registrar únicamente, sin datos personales ni credenciales:
- Resultado `PASS/FAIL` de creación y verificación; SHA-256 del nuevo dump y manifiesto o indicadores de `sha256sum -c` PASS.
- Nombre de archivo **sanitizado** o marca UTC del nuevo respaldo, sin contenido ni ruta de secretos; confirmación de `.verified` correspondiente al **nuevo** respaldo.
- Cantidad de tablas comparadas; cantidad de discrepancias (se exige **0**).
- Confirmación de restauración en `--network none` y eliminación del contenedor efímero y su archivo temporal de contraseña.
- Conteos de backups/verified antes y después, identificando que ninguno de los anteriores fue modificado ni eliminado.
- Estado posterior `vinto-mvp-postgres` healthy, backend/frontend active/running, y sin acceso a TVC.
- Advertencias y fallos; si el comando termina con error, **NO-GO** para cualquier fase posterior.

**Criterio de PASS:** un respaldo nuevo restaurado en contenedor temporal aislado, integridad comprobada, manifiesto reconciliado con **0 diferencias**, marcador `.verified` del nuevo dump, limpieza del contenedor temporal y servicios originales saludables. Los 18 backups históricos permanecen inalterados.

## 5. Fases posteriores explícitamente NO autorizadas

- **P2:** migración 0013; puede alterar PostgreSQL. Su aplicación requiere una revisión independiente del historial de migraciones `vinto_meta` mediante un mecanismo autorizado.
- **P3:** despliegue nuevo con flag OFF, smoke del legado; exige aprobación posterior.
- **P4:** saneamiento de datos simulados, activación del flag, QA manual y cualquier borrado/reprogramación; exige aprobación distinta. El preflight de E1 sigue bloqueado por líneas legadas en progreso sin ejecución lógica, aun cuando sean simuladas.
- **TVC:** totalmente fuera del alcance.

**Dictamen vigente:** P1-A PASS; **GO condicionado para solicitar P1-B**, pero **P1-B NO EJECUTADO y NO AUTORIZADO** hasta que el usuario conceda permiso específico para el comando mutador anterior.

# VINTO E1-09 — P1-B: respaldo nuevo y restauración verificable

**Fecha:** 06/nov/2026. **Estado:** PROCEDIMIENTO PREPARADO, **P1-B NO EJECUTADO**.  
**Fuente de evidencia P1-A:** resultados agregados remitidos por operador SSH; no se usó SSH desde ChatGPT.  
**Código de referencia:** `main@a8a8beaf611e8d892658eeabb5a5e1b972a32316`; VPS sigue en release `86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4` según P0.  
**Referencia:** [P0 y P1-A](E1-09-P0-resultados-y-P1A-inventario-readonly.md).

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

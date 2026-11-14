# VINTO E1-09 — Inspección inicial en Codex Desktop (READ ONLY)

Estado: procedimiento preparado; no se ha ejecutado por ChatGPT. El usuario dispone de conexión SSH VINTO-VPS en Codex Desktop.

Ticket: GitHub #131. Base técnica E1-08: PR #130, QA 158/158. Ningún merge ni despliegue autorizado.

**Nota de estado (06/nov/2026):** este runbook de inspección inicial conserva su contexto histórico. La integración GitHub E1-02 a E1-08 fue completada posteriormente en `main@a8a8beaf611e8d892658eeabb5a5e1b972a32316`, tras QA diferencial [#42169307786](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/42169307786). **No se ha desplegado a la VPS por esa acción**, ni se ha aplicado 0013. Para el siguiente diagnóstico funcional usar [SQL-E de conciliación](E1-09-SQL-E-conciliacion-asignaciones-readonly.md); el objetivo ya no es volver a diseñar SQL-A/B, que cuentan con evidencia histórica en [SQL-A/D](E1-09-resultados-SQL-A-D-legado.md).

## Alcance

Recoger una línea base NO destructiva del MVP VINTO: SHA activo, salud de servicios propios, contenedor PostgreSQL del MVP y preparación para consultar agregados de asignaciones históricas. No presupone que migración 0013 o el código en PR #130 estén desplegados.

Recursos permitidos: /opt/vinto-mvp-web y enlace current; unidades vinto-mvp-backend.service y vinto-mvp-frontend.service; contenedor exacto vinto-mvp-postgres; puerto local 6544; scripts de /home/ubuntu/vinto-mvp-ops (solo presencia, sin ejecutar).

Fuera de alcance: TVC y otros proyectos del host. No tocar postgres-vinto, vinto-web.service, puerto 6543, /opt/vinto-web, /home/ubuntu/vinto, red vinto_default, ni vhost nginx TVC.

## Prompt para Codex conectado a VINTO-VPS

Actúa como auditor de solo lectura del MVP VINTO en esta sesión SSH. No modifiques el servidor. No ejecutes comandos que escriban archivos, cambien permisos, instalen paquetes, actualicen Git, cambien flags, reinicien servicios, manipulen contenedores, realicen respaldos, apliquen migraciones o alteren PostgreSQL. No leas, muestres, copies ni busques contenidos de .env, claves SSH, tokens, contraseñas o secretos de servicios. No uses set -x ni envíes materiales a redes/repos externos. Ante una necesidad de privilegios adicionales, secretos o comandos mutadores, detente y explica el bloqueo sin resolverlo automáticamente.

PASO A (sin SQL aún): verifica hostname, hora UTC, estado y rutas de unidades vinto-mvp-backend.service y vinto-mvp-frontend.service usando únicamente ActiveState, SubState y FragmentPath, nunca Environment. Consulta si existe /opt/vinto-mvp-web/current, su destino y SHA de checkout activo sin leer configuración. Para rutas privadas usa la identidad vinto-mvp solo si tienes permiso no interactivo legítimo para lectura; no solicites contraseña ni escales permisos de manera interactiva. Verifica mediante filtro exacto si existe vinto-mvp-postgres y su estado con docker ps; no inspecciones variables de entorno de ningún contenedor ni listes contenidos de otros proyectos. Verifica presencia, no ejecución, de deploy.sh, rollback.sh, backup.sh y check-release en el directorio de operaciones propio. Consulta si el código desplegado reconoce WORK_ORDER_LINE_EXECUTION_ENABLED mediante inspección de código, pero no abras backend.env para averiguar el valor efectivo; si no se puede comprobar sin secretos, indica NO VERIFICADO.

PASO B (solo diseñar, NO ejecutar): identifica el mecanismo oficial de acceso al PostgreSQL del MVP. Explica cómo ejecutarías SELECT agregados con REPEATABLE READ READ ONLY y statement_timeout breve para OT in_progress, assignments active, asignaciones por sector/máquina, estado de migración 0013 y acceso MF13 efectivo. No uses PostgreSQL de TVC ni extraigas credenciales. Si exige leer/exportar secretos, detente.

SALIDA: tabla con Comprobación | PASS/FAIL/NO VERIFICADO | Evidencia sanitizada. Incluye SHA activo, unidades propias, contenedor propio, scripts, posibilidad de SQL seguro, bloqueantes y siguiente acción. No incluyas contraseñas, URLs credenciales, nombres de empleados, identificadores de OT, asignaciones, capturas, dumps ni secretos. No afirmes que se ejecutó SQL si no se ejecutó.

## Comandos ilustrativos de fase A (Codex evalúa permisos primero)

    hostname
    date -u +%Y-%m-%dT%H:%M:%SZ
    systemctl show vinto-mvp-backend.service -p ActiveState -p SubState -p FragmentPath --no-pager
    systemctl show vinto-mvp-frontend.service -p ActiveState -p SubState -p FragmentPath --no-pager
    readlink -f /opt/vinto-mvp-web/current
    docker ps -a --filter "name=^/vinto-mvp-postgres$" --format '{{.Names}} {{.Status}}'

Prohibido docker inspect ... Config.Env y systemctl show -p Environment. Si Docker no responde por permisos, marcar NO VERIFICADO. No emplear sudo interactivo.

## Criterios

- Servicios sanos, SHA reconocido, contenedor sano: solo candidato para diagnosticar SQL, NO autorización de merge/despliegue.
- Migración 0013 ausente: puede ser normal antes de E1-09, registrar. El preflight completo de PR #130 no está necesariamente en el checkout activo y no debe copiarse sin plan.
- OT o asignaciones históricas: requieren reconciliación funcional; nunca promover una asignación active a in_production automáticamente.
- Flag efectivo no confirmado: NO VERIFICADO; no cambiarlo.

## Fases posteriores (separadas)

1. Aprobar forma segura de consultas SQL de solo lectura y ejecutarlas con la credencial ya autorizada, sin imprimirla.
2. Reconciliar legado y permisos MF13 por sector/máquina; cerrar E1-08 operativo.
3. Integración GitHub en orden #118, #120, #122, #124, #126, #128, #130 después de revisión de cada diff, sin activar el flag.
4. En E1-09: backup/restaurabilidad, release fijo, migración aditiva 0013, preflight post-migración, QA manual y rollback. Toda fase requiere autorización específica.

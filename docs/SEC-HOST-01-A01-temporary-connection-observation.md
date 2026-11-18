# SEC-HOST-01 A0.1 — Preparación de observación temporal de conexiones PostgreSQL

**Estado: PREPARADO PARA PREFLIGHT READ_ONLY. No autoriza activación.** Este repositorio es público: ningún valor de IP, puerto expuesto, rol operativo, ruta sensible, origen observado, nombre de contenedor ni contenido bruto de registros debe incorporarse a esta rama, la CI o el PR.

## Motivo y límite de evidencia

A0 cerró como INDETERMINATE: los registros existentes no documentan conexiones exitosas de forma útil para atribuir un posible consumidor externo. El hecho de que exista capacidad de acceso externo no demuestra que esté siendo usada; sondeos y fallos de autenticación no implican intrusión exitosa. Cerrar accesos sin atribuir su origen podría afectar consumidores legítimos. El responsable del consumidor externo sigue siendo la fuente preferida de confirmación.

**El operador autorizó preparar A0.1, no ejecutar su cambio.** La nueva observación, si se autoriza por separado, debe tener duración limitada, reversión y no-regresión comprobadas y no registrar SQL ni secretos. A1/A2, QA proxy y D3B4 siguen NO AUTORIZADOS.

## Restricciones oficiales del parámetro

- En versiones PostgreSQL 14–17, log_connections es booleano y normalmente off. Registra intentos y las fases de autenticación/autorización; no es una herramienta de atribución perfecta. Puede generar duplicados según el cliente.
- La configuración debe comprobarse a través de pg_settings (setting, vartype, context, source, sourcefile, pending_restart). El contexto superuser-backend puede cambiarse en configuración y recargarse, pero solo afecta sesiones iniciadas **después** del cambio. Es distinto de postmaster, que exigiría reinicio.
- ALTER SYSTEM modifica postgresql.auto.conf en el clúster y no se revierte con ROLLBACK SQL. Debe registrarse **de forma privada** si existía antes una entrada en ese archivo y restaurarla exactamente. La ejecución futura deberá verificar la configuración efectiva tras ambas recargas.
- PostgreSQL 18+ puede tener semántica distinta. El auditor actual rechaza versiones fuera del intervalo aprobado hasta un nuevo diseño.
- Los mensajes pueden exponer IP/puerto del cliente, usuario, DB, aplicación y marcas temporales. Son **datos de acceso restringido**. No volcar logs a GitHub, tickets públicos o chat sin filtrado.

Documentación: https://www.postgresql.org/docs/17/runtime-config-logging.html, https://www.postgresql.org/docs/17/view-pg-settings.html y https://www.postgresql.org/docs/17/sql-altersystem.html.

## Entregables de esta fase

1. scripts/sec-host-01-a01-observation-preflight.sh — único modo audit, **solo lectura**. Identifica el contenedor por variables suministradas en el host (incluido ID Docker completo previamente observado), y consulta pg_settings con transacciones de solo lectura y timeout. No imprime identificadores, valores de configuración, direcciones o logs.
2. Tests negativos que rechazan start, stop, apply, rollback y cualquier otro modo mutante; pruebas de que el script no modifica configuración ni lee logs.
3. scripts/sec-host-01-a01-restore-policy.mjs — función **pura** de planificación de restauración. Sus tests distinguen una entrada preexistente de auto-configuración (restaurar valor original) de una anulación nueva sobre el archivo regular o defaults (RESET). Fuente/contexto no verificados: BLOCKED.
4. GitHub Actions ejecuta tests sin conectarse a la VPS, escribir GUCs o generar logs.

## Qué deberá informar Codex durante el próximo preflight READ_ONLY

- Versión del servidor objetivo, semántica de log_connections, fuente, contexto y pending_restart.
- Identidad del contenedor real validada por ID completo sin publicar el identificador.
- Ruta efectiva de logs, existencia de protección y retención. El preflight detecta el candidato stderr directo, pero no prueba por sí solo persistencia/privacidad.
- Si el origen remoto que aparecería en los logs conserva IP real o pasa por NAT/proxy Docker. No atribuir automáticamente origen por el solo registro.
- Metadatos privados del modo de restauración, sin imprimir sourcefile ni contenido.
- Estado y periodicidad de consumidores locales y posible externo, sin inventar horarios.
- Mecanismo para armar y probar apagado automático (ej. timer systemd) ANTES de activar la observación. Debe sobrevivir desconexión del operador; de no ser posible, bloquear.
- Destino privado de la evidencia, mínimos permisos y retención, capacidad de disco, y ventana suficiente para incluir un ciclo de actualización confirmado cuando sea posible.

## Plan FUTURO de activación (NO implementado ni autorizado)

| Fase | Gate | Acción bajo autorización independiente |
|---|---|---|
| PRE | Identidad, versión, GUC, logs, origen, restauración y continuidad PASS | Registrar baseline y plan de reversión en almacenamiento root-only, sin copiar a GitHub |
| ARM | Apagado automático comprobado | Armar parada y reversión ANTES del cambio |
| START | Confirmación específica y plazo aprobados | Activar solo registros de conexión, recargar controladamente sin reinicio de contenedor |
| OBSERVE | Ventana, volumen y privacidad | Analizar eventos sin SQL, parámetros, paquetes ni contraseñas |
| STOP | Vencimiento, límite de volumen o incidente | Restaurar valor y fuente original, recargar y verificar nueva sesión |
| VERIFY | No regresión y fin de observación | Comprobar consumidores existentes, configuración efectiva y parada |
| DECIDE | Evidencia suficiente o no | CONFIRMED / NOT_VERIFIED. No inferir desuso por ausencia de conexiones |

Si START falla tras un cambio parcial, el mecanismo futuro aprobado deberá priorizar STOP y evidencia del estado, sin reintentos ciegos. El diseño mutante completo queda condicionado al preflight real y a autorización explícita posterior. **No existe aún un ejecutor START/STOP apto para VPS**.

## Prohibiciones

- No modificar contenedores, redes, firewall, PostgreSQL, pg_hba, ETL o servicios durante este incremento.
- No cambiar log_statement, log_duration, log_disconnections, log_min_duration_statement, formato de logs, log_line_prefix, contraseñas o políticas de acceso.
- No desplegar QA, D3B4, usuarios/grants, ni fusionar a main.
- No generar conexiones artificiales para encontrar IPs; la inspección abre solo una conexión administrativa de lectura normal.
- Nunca presentar CI o PASS_READ_ONLY_WITH_OPERATIONAL_GATES_OPEN como autorización para activar.

**Salida esperada:** preflight host PASS_READ_ONLY_WITH_OPERATIONAL_GATES_OPEN o BLOCKED, seguido de plan específico de inicio/apagado basado en evidencia, sin cambios reales.

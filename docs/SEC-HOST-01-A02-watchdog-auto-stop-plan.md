# SEC-HOST-01 A0.2 — Apagado automático de observación PostgreSQL

**Estado: preparado para tests y revisión. No instalado ni autorizado en VPS.** El operador pidió preparar el apagado automático; la autorización no incluye activar registro de conexiones, instalar systemd, ejecutar ALTER SYSTEM ni modificar otros servicios. No publicar aquí detalles operativos, IPs, puertos expuestos, roles, ID de contenedor ni eventos: el repositorio es público.

## Evidencia

A0.1-PRE en VPS confirmó que log_connections está deshabilitado y admite recarga sin reinicio en PostgreSQL17. Los logs se dirigen a Docker json-file sin rotación configurada. La fuente previa exacta del parámetro y la fidelidad de la IP de clientes externos siguen NO VERIFICADAS. No hay ventana de observación aprobada.

## Entregables

- scripts/sec-host-01-a02-stop-watchdog.py: solo modo tick, sin modo START ni lógica para encender registros. Recibe el contexto operativo exclusivamente de un manifiesto root:0600 en directorio root:0700, valida el ID Docker completo, fechas UTC, baseline y presupuesto de log. Evita symlinks y ejecuciones concurrentes con flock. Persiste fases de estado de forma atómica.
- ops/sec-host-01-a02/sec-a01-watchdog.service: servicio oneshot root con aislamiento systemd, directorio de estado privado y salida sanitizada.
- ops/sec-host-01-a02/sec-a01-watchdog.timer: comprobación cada minuto en UTC, Persistent=true y una comprobación después de arrancar el host; continúa después de perder la sesión de Codex.
- scripts/test_sec_host_01_a02_stop_watchdog.py: pruebas sin Docker/PostgreSQL real para deadline, crecimiento máximo, mínimo disco, estado persistente, reintentos y fallback de emergencia.

## Operación prevista cuando exista autorización independiente

1. Antes de activar logging, comprobar que log_connections=off proviene de default o archivo regular y que NO existe entrada anterior en postgresql.auto.conf. Esta primera versión bloquea el escenario de auto.conf preexistente. El origen debe verificarse en el host, no inferirse del PASS A0.1-PRE.
2. Instalar y probar el timer, validar que corre independiente de Codex y probar en laboratorio el retorno a off y su estado final. No encender logging durante la instalación del watchdog.
3. Registrar estado privado: ID completo del contenedor, credencial de rol administrativo por autenticación local sin revelar password, epoch de inicio y deadline absoluta UTC, tamaño inicial del log, presupuesto de crecimiento, mínimo espacio libre y fase armed.
4. Cada tick observa metadatos de Docker, nunca contenido del log. Si vence la fecha límite, hay crecimiento excesivo, bajo espacio libre o anomalía, persiste estado stopping.
5. El stop ejecuta únicamente ALTER SYSTEM RESET log_connections y recarga. Usa una NUEVA conexión para comprobar off, la fuente de valor original y ausencia de pending_restart. Si todo coincide, marca restored.
6. Si no se logra restauración exacta, intenta ALTER SYSTEM SET log_connections = off como emergencia, recarga y registra OFF_REQUIRES_SOURCE_RESTORE, sin declarar éxito. Si el DB no responde, marca bloqueo; el timer intenta de nuevo. No hay reinicio de PostgreSQL ni cambio firewall.
7. Tras restored, los siguientes ticks no realizan escrituras adicionales.

**Advertencia:** el timer no puede garantizar apagar a la hora exacta si host/systemd/Docker/PG están caídos o la autorización local falla. Un sondeo cada minuto tampoco establece límite duro de tamaño para un log sin rotación: puede superarse entre revisiones. Por ello se necesita presupuesto de disco, control de volumen y respuesta humana antes de iniciar observación.

## Restauración y fuente del parámetro

ALTER SYSTEM RESET log_connections quita solo la entrada temporal de postgresql.auto.conf. Si antes había una entrada en ese archivo, RESET perdería ese estado previo, por lo que el watchdog actual lo rechaza. Si el valor estaba en default o archivo regular, RESET permite regresar al origen original. ALTER SYSTEM no se puede revertir mediante ROLLBACK SQL; una recarga aplica la modificación a nuevas sesiones. Referencias: https://www.postgresql.org/docs/17/sql-altersystem.html y https://www.postgresql.org/docs/17/view-pg-settings.html.

## Resultado del preflight posterior y endurecimiento del candidato

Codex verificó **solo lectura** que la fuente original de la configuración es DEFAULT, con valor deshabilitado, sin anulación preexistente ni reinicio pendiente. Las configuraciones de control de acceso tampoco presentaban cambios nuevos por recargar. La compatibilidad sintáctica de systemd se confirmó; no se probaron unidades instaladas ni la ejecución real con aislamiento. **No se autoriza instalar, armar o activar por este resultado.**

Se aplicaron mejoras al candidato después del preflight: `ExecStart` con Python aislado (`-I`), `TimeoutStartSec=180s`, verificación de archivo de watchdog regular, propiedad root y ausencia de escritura de grupo/otros, comprobación de directorio protegido, y eliminación de condiciones que omitirían silenciosamente un tick si desapareciera el estado. El servicio usa `OnFailure` para dejar una marca local root-only en un archivo fijo y un fallo visible en journal. **No existe un receptor de alerta externa:** esa marca no equivale a notificar a un operador. La activación sigue condicionada a probar quién y cómo recibirá el aviso.

Límites tentativos de control: crecimiento de log **10 MiB**, espacio libre mínimo **20 GiB**, revisión cada minuto y ventana máxima admitida de siete días. Son parámetros propuestos, no desplegados ni autorizados. Incluso siete días podrían no cubrir dos actualizaciones semanales completas; se requiere conocer el ciclo del consumidor o reconocer explícitamente que el resultado puede ser INDETERMINATE.

No se debe usar el temporizador si el archivo de estado falta: ahora esa condición produce un error y activa la marca local. La instalación futura puede colocar archivos root-only y validar las unidades sin habilitar el timer, pero el ensayo sobre PostgreSQL de producción sigue prohibido hasta autorización específica.

## Gates abiertos

- Fuente real y ausencia de override anterior en auto.conf, sin divulgar rutas ni valores.
- Instalación del timer con autorización separada; prueba independiente de systemd real y mecanismo de alarma si STOP devuelve error.
- Duración y fecha límite UTC que cubran un refresco conocido, sin inventar frecuencia Power BI.
- Umbral de crecimiento, espacio libre, acceso y retención privada de logs, y posibilidad de rotación Docker si se decide.
- Validar atribución de IP del cliente o mantener NOT_VERIFIED.
- Verificar preservación TVC/ETL/piloto/QA, acceso a admin Postgres y no regresión.
- Una autorización independiente posterior para instalar/armar y otra para START, ambas con alcance y plazo.

A1/A2, QA proxy y D3B4 permanecen NO AUTORIZADOS. CI es simulación, no instalación ni evidencia de acceso a PostgreSQL real.

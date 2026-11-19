# VINTO OFF-04.5B — Guard y autorización del piloto QA sintético, plan de activación y reversión

**Estado:** candidato de desarrollo aislado, PR Draft apilado sobre #237 (`eec7a18aa16ed53a7ac54501423b6015a2708757`). Seguimiento: #236.
**NO activa servicios, NO despliega, NO aplica migraciones, NO crea usuarios ni permisos, NO habilita captura industrial.** SEC-HOST-01 y OFF-04.2-R3 siguen en backlog. Este documento no contiene identificadores operativos (hosts, IP, puertos, nombres de bases ni rutas del servidor): esos datos viven en el informe privado de inventario.

## 1. Qué se añade
- `backend/app/qa_offline_guard.py`: copia **literal** del guard probado de #219 (cuatro POST exactos). No se amplía; al fusionar #219 el contenido es idéntico.
- `backend/app/qa_offline_pilot.py`: fábrica `create_qa_pilot_app(...)` de una **aplicación QA separada**. No se importa desde `app.main` ni desde ningún otro módulo (prueba estática y control en CI).
- `backend/tests/test_off045b_qa_pilot.py`: 47 pruebas ASGI (SQLite y PostgreSQL desechable).

## 2. Condiciones de activación (todas, y en este orden de fallo cerrado)
| # | Condición | Si falta |
|---|---|---|
| 1 | `APP_ENV` exactamente `qa` | no existe ninguna ruta de capturas: todo 404 |
| 2 | `OFFLINE_QA_PILOT_ENABLED` activo (apagado por defecto) | el guard devuelve 403 a todo POST; GET 404; sin rutas |
| 3 | base del receptor con nombre QA/desechable verificado con `current_database()` | el arranque falla (`database_not_isolated_qa`) |
| 4 | registro explícito de concesiones **sintéticas** (`OFFLINE_QA_PILOT_GRANTS`, JSON estricto, máx. 20) | el arranque falla (`grants_required`) |
| 5 | sesión QA válida | 401 |
| 6 | el usuario autenticado es el autor original | 403 `author_mismatch` |
| 7 | concesión exacta usuario + máquina + formulario + versión (+ snapshot fijado) | 403 |

Una concesión describe un usuario, una máquina y una versión de formulario, y debe declarar `synthetic: true`. Un snapshot de consulta (readiness-only) nunca autoriza: el snapshot de la captura debe ser exactamente el fijado en la concesión. Los indicadores `capture_eligible` y `captures_enabled` no se leen ni se reinterpretan.

## 3. Guard
`pilot_request_permitted` = guard de #219 **más una única** petición: `POST /api/offline/captures` exacta, solo con `APP_ENV=qa` y el flag. Alias, barra final, mayúsculas, codificaciones, otros métodos sobre la misma ruta y cualquier otra escritura siguen en 403.

## 4. Motor `authz`
Puerto `EngineProbe` y adaptador `AuthzEngineProbe` sobre `authorize(...)` con `Operation.QUALITY_MACHINE_CAPTURE` (solo lectura; no cambia permisos industriales). Modo `OFFLINE_QA_PILOT_AUTHZ_MODE`:
- `off`: no se consulta.
- `observe`: se consulta y **solo se registra**; nunca concede ni restringe. Sin concesión del registro, el resultado es 403 aunque el motor permita.
- `enforce`: el motor debe **además** permitir; solo puede restringir. Un fallo del motor es una denegación.

El adaptador está probado con conexión simulada; **no** se ha ejecutado contra una base QA real (acción pendiente, ver §7).

## 5. Contexto
No se evalúa contexto industrial: la captura se considera `same` solo si la concesión fija exactamente esa versión de contexto sintética; si no, queda `unverifiable` (revisión central, HTTP 202). Nunca se informa un cambio como compatible. El resultado es recepción técnica con `industrial_approval=false`.

## 6. Pruebas (CI con datos y credenciales sintéticos)
Flag apagado; entorno distinto de QA; sesión inválida (401); usuario incorrecto y sin concesión (403); snapshot de solo lectura (403); concesión correcta (201, recepción técnica); contexto sin fijar (202); duplicado (una recepción); mismo ID con otro contenido (409); POST operativos y variantes bloqueados; GET solo del autor (404 para otros); `observe` no concede; `enforce` exige ambos; fallos de arranque; concesiones estrictas; mensajes de error sin valores; aislamiento estático; adaptador del motor. Cinco mutaciones del módulo (flag ignorado, `observe` efectivo, snapshot sin comprobar, base sin comprobar, entorno ignorado) son detectadas.

## 7. Plan de activación (NO ejecutar sin autorización por paso)
0. **Prerrequisitos de evidencia:** CI verde del SHA exacto de este PR; inventario VPS vigente (informe privado); respaldo QA reciente verificado.
1. **Aprobación A:** fusionar o integrar el guard de #219 y este desarrollo en la rama de QA (decisión humana; sin merge desde este incremento).
2. **Aprobación B:** servicio QA propio, en puerto de loopback propio, con unidad de servicio, usuario y credenciales de servicio dedicados (nunca compartidos con piloto/TVC), `APP_ENV=qa`, `PG_PRIVILEGE_MODE=hardened`, dos conexiones, flag **apagado**. Verificar arranque y 403 a toda escritura.
3. **Aprobación C:** aplicar la migración propuesta en la base QA con respaldo previo, verificar el esquema y probar el rollback propuesto en una copia.
4. **Aprobación D:** cuenta sintética y concesión mínima en QA (un usuario, una máquina, una versión sintética), `authz` en `observe` y luego `enforce` para esa terna.
5. **Aprobación E:** acceso privado: el vhost HTTPS de QA debe proxyar solo a ese servicio y rechazar por defecto salvo VPN/allowlist, verificado desde dos orígenes.
6. **Aprobación F:** encender el flag y ejecutar el recorrido físico sintético con un dispositivo real.
7. Verificación: una sola recepción por captura, eventos append-only, pendientes locales conservados.

## 8. Plan de reversión
- **Parada inmediata (sin migración):** apagar el flag y reiniciar el servicio QA → todo POST de captura vuelve a 403 y las rutas desaparecen. No requiere tocar la base.
- **Parada completa:** detener el servicio QA y retirar su ruta del vhost (restaurando el marcador previo).
- **Datos:** conservar las filas como evidencia; el rollback de la migración (`DROP SCHEMA` aislado) solo con aprobación explícita y después de exportar la evidencia.
- **Condiciones de parada:** duplicado, fuga entre usuarios, 5xx sostenido, acceso desde fuera de la lista permitida o cualquier escritura fuera de las tablas del esquema aislado.

## 9. Riesgos residuales
- Las concesiones viven en configuración del servicio, no en la base: son una autorización sintética de piloto, no un modelo de permisos.
- Sin evaluación de contexto industrial real (OT, asignación, turno).
- El adaptador del motor no se ha probado con una base QA real.
- QA físico del móvil no ejecutado; la homologación de P1-22 sigue pendiente para cualquier uso real.
- OFF-04.2-R3 (privacidad de cuarentena, retención y recuperación) debe cerrarse antes del primer usuario real en móvil compartido.

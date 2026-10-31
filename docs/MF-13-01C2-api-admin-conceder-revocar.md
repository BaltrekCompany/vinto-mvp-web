# MF-13-01C.2 · API administrativa para conceder y revocar el acceso a un formulario de una máquina

Dos endpoints **POST** en `/api/admin` que permiten a un administrador autorizado (`user.manage`) conceder y revocar, de forma individual, el acceso de un usuario a **un formulario de una máquina**. Reutilizan
`grant_machine_form` / `revoke_machine_form` (no hay SQL duplicado) y las mismas defensas que los POST de sector. **Esta fase administra concesiones pero todavía no las usa**: ninguna captura, orden de trabajo,
asignación, bobina ni liberación de Calidad consulta la tabla, y sin frontend.

## 1. Contrato
`POST /api/admin/users/{user_id}/grants/grant` y `POST /api/admin/users/{user_id}/grants/revoke`. Cabeceras: `Origin` (uno de los permitidos), `Content-Type: application/json`, cookie de sesión.

```json
{"machine_code": "MP1", "form_code": "VINTO-P1-01"}
```
Cuerpo **estricto**: solo esos dos campos; cualquier otro (`actor_id`, `revoked_by`, `request_id`, `user_id`, `permissions`, `profiles`, `sector_code`…) es `422`. El actor sale **solo** de la sesión autenticada, el usuario de la ruta y el
`request_id` lo genera el servidor (una cabecera `X-Request-Id` del cliente se ignora). Los códigos se validan por forma (mayúsculas, dígitos, `_`/`-`) y por **existencia contra PostgreSQL**; el código no tiene listas de máquinas ni formularios.

Respuesta `200` (también cuando no hay cambio):
```json
{"user_id":"…","machine_code":"MP1","form_code":"VINTO-P1-01","operation":"grant","changed":true,"active":true,
 "request_id":"admin-machine-form-grant:…",
 "grant":{"id":"…","state":"active","machine":{…},"form":{…},"granted_at":"…","granted_by":{"id":"…","display_name":"…"},"revoked_at":null,"revoked_by":null,"catalog":{…}},
 "catalog":{"published_version":4,"offered":true,"enabled_for_capture":true,"capture_policies":["production_central"]},
 "context":{"user_active":true,"sector_code":"BOBINAS","sector_granted":true,"sector_operational":true}}
```
- `changed:false` = ya estaba así: no se escribió ni se auditó nada y `request_id` es `null`. `active` = ¿queda una concesión activa de esa terna? `grant` = la fila más reciente de la terna (activa, o la última revocada; `null` si nunca existió).
- `catalog` separa **ofrecido** (`offered`) de **habilitado para captura** (`enabled_for_capture`), con las mismas definiciones que la API de consulta (MF-13-01C.1). Conceder exige *ofrecido*; **no** exige *habilitado* y no inventa políticas de captura
  (p. ej. `VINTO-P1-03` se concede aunque se registre por `/api/bobbins`).
- Cabecera `Cache-Control: no-store`.

### Errores (cuerpo `{"detail", "code"}`; nunca SQL, tokens ni identificadores internos)
| Estado | `code` | Cuándo |
|---|---|---|
| 401 | — | sin sesión válida (o sesión revocada) |
| 403 | — / `ORIGIN_NOT_ALLOWED` | sin `user.manage`; `Origin` ausente, `null` o no permitido (se comprueba **antes** de la sesión) |
| 404 | `USER_NOT_FOUND` / `MACHINE_NOT_FOUND` / `FORM_NOT_FOUND` | no existe (se comprueba en ese orden) |
| 409 | `PAIR_NOT_OFFERED` | **solo al conceder**: el par no se ofrece hoy (formulario, máquina o sector inactivos, o la versión publicada **vigente** no lo vincula; un vínculo que solo existe en una versión histórica no cuenta) |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | el cuerpo no es `application/json` |
| 422 | — | campos extra, faltantes o con forma inválida; id de usuario mal formado |
| 503 | — | PostgreSQL no disponible |

## 2. Reglas
- **Independencia absoluta:** cada terna `(usuario, máquina, formulario)` es una concesión. `VINTO-P1-01` en MP1 no concede MP3; `VINTO-P1-10` se concede por separado en Beloit, Over, Copasa, Perichun y Tubetera (el catálogo vigente decide dónde se ofrece). Conceder no concede
  perfiles, sectores ni otros formularios (una prueba compara usuarios, perfiles, sectores y catálogo antes y después).
- **Revocar** conserva la fila (`revoked_at`/`revoked_by`) y el historial; conceder de nuevo crea una fila nueva. Revocar **sí** se permite sobre un par que ya no se ofrece: una concesión inerte debe poder retirarse.
- **Idempotencia y carreras:** la decide la base de datos (índice único parcial + `ON CONFLICT` / `UPDATE … WHERE revoked_at IS NULL`). Probado con 8 peticiones simultáneas idénticas (una sola fila y un solo evento) y con dos administradores revocando a la vez
  (`revoked_by` es el de la petición que ganó).
- **Auditoría:** cada cambio efectivo deja un evento en `vinto_audit.audit_event` con el administrador autenticado (`actor_id`), `request_id` del servidor y motivo; no hay `DELETE`. Las repeticiones no generan eventos.

### Usuarios inactivos o sin el sector correspondiente (regla existente, **sin cambios**)
`grant_machine_form` nunca exigió que el usuario esté activo ni que tenga el sector de la máquina, y esta API no lo cambia. Una concesión así queda **inerte** hasta que ambas cosas existan; la respuesta lo informa en `context`
(`user_active`, `sector_granted`, `sector_operational`) para que el administrador lo vea. La autorización efectiva futura deberá exigir las tres condiciones (usuario activo, sector concedido y operativo, concesión activa y par ofrecido); hoy no se aplica nada.

## 3. Superficie de escritura directa de `vinto_app` (análisis, sin cambios de privilegios)
**Hechos verificados.** En un clúster con los roles de `backend/roles`, `vinto_app` tiene `SELECT, INSERT, UPDATE` sobre `user_machine_form_grant` (el `GRANT` protegido de la 0007), **sin** `DELETE` ni `TRUNCATE`. Lo que la base ya garantiza aunque se escriba por SQL directo:
identidad inmutable, fila revocada congelada, una fila activa solo cambia al revocarse, `revoked_at` = reloj del servidor, `revoked_by` = actor de la sesión (y la revocación exige actor, 0009), una concesión nace activa y los sellos solo pueden ser el actor. La auditoría es inmutable.

**Lo que NO garantiza la base** (por eso sigue siendo superficie):
1. Un `INSERT` directo **no** pasa por la política de «par ofrecido» (que vive en el servicio): podría crearse una concesión para un par inexistente en el catálogo vigente (inerte, pero engañosa).
2. El actor (`vinto.actor_id`) lo escribe el cliente de la sesión: quien tenga credenciales de `vinto_app` puede afirmar cualquier actor; lo que queda veraz es `audit_event` con `database_actor` (`session_user`), `request_id` y `reason`. Como toda la API comparte un usuario de base de datos, `database_actor` no distingue personas.
3. Un `INSERT` sin actor crea una concesión sin atribuir (sellos NULL; la auditoría lo muestra con `actor_id` NULL).

**Quién puede explotarlo hoy:** solo código con credenciales de `vinto_app` (una inyección SQL o un fallo de la aplicación) o un DBA. La API usa consultas parametrizadas y, desde esta fase, **un único módulo** (`app/admin/grants_write.py`) llama a conceder/revocar (una prueba lo fija).

**Control que debe existir antes de activar la autorización efectiva** (propuesto, no implementado):
1. *Detección:* revisar periódicamente las escrituras fuera de la API —
   ```sql
   SELECT id, action, actor_id, database_actor, request_id, occurred_at FROM vinto_audit.audit_event
   WHERE entity_table = 'user_machine_form_grant' AND action IN ('INSERT','UPDATE')
     AND (actor_id IS NULL OR request_id IS NULL OR request_id NOT LIKE 'admin-machine-form-%' AND request_id NOT LIKE 'machine_form_grant:%')
   ORDER BY id;
   ```
   Resultado esperado hoy: filas solo de pruebas/migraciones; en producción, **0**.
2. *Lectura en la transacción de captura:* la autorización efectiva debe releer la concesión dentro de la misma transacción (el riesgo de carrera descrito en MF13-01A) y tratar como **no concedido** un par que ya no se ofrece, un usuario inactivo o sin el sector.
3. *Decisión de gobernanza sobre funciones `SECURITY DEFINER` (análisis de compatibilidad, para decidir antes de implementar):* mover las escrituras a dos funciones (`owner` `vinto_migrator`, `SECURITY DEFINER`, `search_path` fijo, `REVOKE … FROM PUBLIC`, `GRANT EXECUTE … TO vinto_app`) y retirar
   `INSERT`/`UPDATE` directos a `vinto_app`. *Compatible:* los triggers (`touch_row`, guarda, `record_change`) leen el GUC y `session_user`, que no cambian; `database_actor` seguiría siendo el login real; la semántica `ON CONFLICT` y la concurrencia se conservan; la política «par ofrecido» podría
   imponerse dentro de la función. *Coste y riesgos:* una migración nueva que haga `REVOKE` (la `GRANT` protegida de la 0007 no se reescribe), cambios en `roles/03_table_grants.sql` y en `roles_e2e`, duplicar o mover la política de catálogo al SQL, y vigilar el `search_path` y los `EXECUTE`. *Límite:* el actor seguiría pasándolo
   la aplicación, así que **no autentica a nadie**; reduce la superficie (ningún `UPDATE`/`INSERT` ad hoc con las credenciales de la API). Recomendación: decidirlo cuando se programe la autorización efectiva; no es necesario para esta fase.
4. *Procedimiento manual* de revocación para operadores: ver `docs/MF-13-01B4-atribucion-revocaciones.md`.

## 4. Despliegue
Solo código backend; **sin migraciones ni importaciones**. Requiere las migraciones 0007–0009 ya aplicadas (tabla, endurecimiento y atribución de revocaciones). Sin frontend. Compatible con el código anterior en cualquier orden (los endpoints son nuevos).
Reversión: desplegar la versión anterior; las filas creadas por la API son concesiones normales (se pueden revocar) y no hay nada que deshacer en el esquema. Sin cambios de privilegios ni de filtros en endpoints productivos.

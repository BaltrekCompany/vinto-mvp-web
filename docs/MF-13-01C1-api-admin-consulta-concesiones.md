# MF-13-01C.1 · API administrativa de consulta: catálogo y concesiones máquina-formulario

Cinco endpoints **GET de solo lectura** en `/api/admin`. Mismo permiso (`user.manage`, solo `DATA_BALTREK` hoy) y mismas sesiones que el resto de `/api/admin`; sin sistema de permisos paralelo. Sin POST/PUT/PATCH/DELETE para
concesiones, sin cambios de frontend, de migraciones (0007–0009) ni de catálogo, y **sin activar todavía la autorización efectiva** (las concesiones siguen sin consultarse en las capturas).

Todas las respuestas llevan `Cache-Control: no-store`, no incluyen credenciales, hashes, tokens ni información de sesión (lo comprueba una prueba sobre claves y valores) y se leen en una transacción
`REPEATABLE READ READ ONLY`, es decir, con una instantánea coherente aunque otra sesión conceda o revoque mientras tanto. Errores: `401` sin sesión, `403` sin `user.manage`, `404 USER_NOT_FOUND`, `422` ante un id o un `limit` mal formado.

## 1. Cuatro conceptos que no son lo mismo
| Concepto | Dónde se ve | Significado |
|---|---|---|
| **Publicado** | `published`, `effective_version` | El formulario tiene una versión publicada vigente (la de número más alto). Se informa su número. |
| **Ofrecido** | `offered` | La versión publicada **vigente** (nunca una anterior) vincula el formulario a la máquina, y formulario, máquina y sector están activos. Es exactamente lo que exige `grant_machine_form` para conceder (una prueba lo contrasta par a par) y lo que `production_access` ofrece. |
| **Habilitado para captura** | `enabled_for_capture`, `capture_policies` | Además de ofrecido, existe una política de captura **en código** que acepta el formulario y el sector es operativo (`app/sectors.py`). Ejemplo: `VINTO-P1-03` está publicado y ofrecido en MP1/MP3, pero se registra por `/api/bobbins`, no por la captura central: `capture_policies: []`, `enabled_for_capture: false`. |
| **Concedido** | `GET …/grants` | Existe una fila activa en `user_machine_form_grant`. Cada concesión muestra además el estado **actual** del par (`catalog`), porque una concesión guardada puede haber quedado inerte (par ya no ofrecido); se muestra, no se oculta ni se reescribe. |

`capture_policies` es un rótulo descriptivo de constantes que ya existen, leídas en vivo (no se copian): `production_central` (`capture_service.CENTRAL_FORM_CODES`), `quality_by_bobbin`
(`CENTRAL_BOBBIN_FORM_CODES` + candidatos habilitados) y `quality_by_machine` (`MACHINE_QUALITY_FORM_CODES`). No introduce reglas nuevas.

## 2. Contratos
### `GET /api/admin/catalog`
Sectores → máquinas → formularios que la versión vigente vincula a cada máquina. MP1 y MP3 aparecen con su propia lista (P1-01 en ambas; P1-31 solo en MP3; P1-10 v3 en las cinco rebobinadoras, según el bundle vigente).
```json
{"sectors":[{"code":"REBOBINADO","name":"Rebobinado","active":true,"operational":true,"machines":[
  {"code":"COPASA","name":"COPASA","active":true,"forms":[
    {"code":"VINTO-P1-10","name":"Registro de fardos","area":"production","active":true,"effective_version":3,"published":true,
     "capture_policies":["production_central"],"offered":true,"enabled_for_capture":true}]}]}]}
```
### `GET /api/admin/catalog/forms`
Todos los formularios (también los sin versión publicada: `published:false`, `effective_version:null`) con las máquinas que la versión vigente vincula. `enabled_for_capture` = habilitado en al menos una máquina.
```json
{"forms":[{"code":"VINTO-P1-31","name":"Consumo de químicos","area":"production","active":true,"published":true,"effective_version":2,"capture_policies":["production_central"],
  "enabled_for_capture":true,"machines":[{"code":"MP3","sector_code":"BOBINAS","active":true,"offered":true,"enabled_for_capture":true}]}]}
```
### `GET /api/admin/users/{user_id}`
Perfil(es), permisos **derivados** de los perfiles con la matriz existente y sectores concedidos (con `operational`: concedido no implica operativo).
```json
{"id":"…","username":"…","display_name":"…","active":true,"profiles":[{"code":"OPERACION","name":"Operación"}],
 "permissions":["assignment.read","catalog.read","production.capture","work_order.read"],"sectors":[{"code":"BOBINAS","name":"Bobinas","active":true,"operational":true}]}
```
### `GET /api/admin/users/{user_id}/grants`
Concesiones **activas** por máquina y formulario (orden: máquina, formulario).
```json
{"user_id":"…","total":2,"truncated":false,"grants":[{"id":"…","state":"active",
  "machine":{"code":"MP1","name":"MP1","sector_code":"BOBINAS"},"form":{"code":"VINTO-P1-01","name":"…","area":"production"},
  "granted_at":"…","granted_by":{"id":"…","display_name":"…"},"revoked_at":null,"revoked_by":null,
  "catalog":{"published_version":4,"offered":true,"enabled_for_capture":true,"capture_policies":["production_central"]}}]}
```
### `GET /api/admin/users/{user_id}/grants/history?limit=200`
Todas las filas (activas y `state:"revoked"`, con `revoked_at` y `revoked_by`), de la más reciente a la más antigua. `limit` 1–500 (200 por defecto); `total` son las filas que existen y `truncated` indica si `limit` recortó la respuesta.
`granted_by` es `null` si la fila se creó sin actor (alta directa por SQL). Volver a conceder tras revocar crea una fila nueva: el historial conserva ambas.

## 3. Lo que muestra sobre los puntos pedidos
- **MP1 y MP3 separadas:** son entradas y concesiones distintas aunque compartan `VINTO-P1-01`; revocar una no marca la otra.
- **Vínculo solo histórico:** no se lista ni se ofrece (p. ej. P1-05 v1 en MP1 tras MF-12A). Si existía una concesión guardada de ese par, se muestra `offered:false`.
- **P1-31:** solo MP3, `area: production` tal como está (sin cambiar su área funcional).
- **Calidad:** el catálogo refleja la base: los formularios de área `quality` solo están vinculados a MP1 y MP3; **no se inventa ninguno para Rebobinado ni Conversión** (una prueba lo fija).

## 4. Pendiente de definición funcional (documentado, no resuelto)
La política de disponibilidad de **Calidad en Rebobinado** no tiene hoy contenido que mostrar: el bundle no define formularios `quality` para esas máquinas, y las dos políticas de captura de Calidad (`quality_by_bobbin`,
`quality_by_machine`) están ligadas a Bobinas. Si Calidad debe trabajar con Rebobinado, hay que definir **qué formularios** (publicarlos con área `quality` y vincularlos) y **bajo qué política**; este PR no asume ninguna. Tampoco
decide la regla de Conversión («por ahora no») más allá de lo que ya impone la concesión de sector.

## 5. Dependencias de despliegue
Solo código backend; **sin migraciones ni importaciones nuevas**. Requiere que la base ya tenga la tabla `user_machine_form_grant` (0007) y se recomienda la 0009 (atribución de revocaciones) para que el campo `revoked_by` del historial sea fiable. Frontend
sin cambios. Reversión: desplegar la versión anterior del backend; los endpoints no escriben, así que no hay nada que deshacer.

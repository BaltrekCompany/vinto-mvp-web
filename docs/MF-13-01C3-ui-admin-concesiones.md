# MF-13-01C.3 · Interfaz para administrar accesos por usuario, máquina y formulario

Amplía la consola **existente** de `/admin` (no hay una segunda consola): al seleccionar un usuario aparecen dos secciones claramente diferenciadas. **A. Sectores** queda intacta (sus acciones, permisos y funcionamiento no cambian). **B. Máquinas y formularios**
es nueva e incluye el historial. Solo frontend: no toca el backend, sus migraciones, capturas, bobinas, órdenes ni Calidad, y **no activa la autorización efectiva**. Capturas: `docs/evidence/mf13-01c3/`.

## 1. Qué se puede hacer
1. Ver las máquinas agrupadas por sector (con cuántos formularios ofrece cada una y cuántos tiene concedidos el usuario).
2. Seleccionar una máquina y ver los formularios que su versión publicada vigente le vincula.
3. Ver cuáles están concedidos al usuario.
4. **Conceder** o **revocar** un formulario individual (siempre con confirmación).
5. Consultar el **historial** de concesiones y revocaciones (solo lectura).

Sin asignaciones masivas. Seleccionar una máquina solo cambia lo que se *muestra*: el objetivo de una operación (usuario, máquina, formulario) se fija al abrir la confirmación, de modo que ni cambiar de máquina ni de usuario después puede desviarla.

## 2. Fuente de datos (únicamente los siete endpoints existentes)
| Uso | Endpoint |
|---|---|
| Máquinas por sector y formularios de cada una | `GET /api/admin/catalog` |
| Formularios publicados y sus máquinas (para listar los «no ofrecidos») | `GET /api/admin/catalog/forms` |
| Perfil, estado y sectores del usuario (para detectar la inercia) | `GET /api/admin/users/{id}` |
| Concesiones activas | `GET /api/admin/users/{id}/grants` |
| Historial (límite 200; respeta `truncated`) | `GET /api/admin/users/{id}/grants/history?limit=200` |
| Conceder / revocar | `POST /api/admin/users/{id}/grants/grant` y `/grants/revoke` |

No hay listas estáticas de máquinas ni de formularios, datos ficticios ni almacenamiento local (una prueba lo verifica sobre el código fuente). La petición usa la **misma** pieza administrativa que sectores (`createAdminRequester`: cookie de sesión HttpOnly, sin caché, sin `Origin`
manual, errores mapeados): la autenticación no se duplica. El cuerpo de un cambio es exactamente `{machine_code, form_code}`; el frontend nunca envía `actor_id`, `revoked_by` ni `request_id`.

## 3. Cómo se distingue lo que significa cada cosa
| Mostrado como | Significado |
|---|---|
| **Publicado vN** | hay versión publicada vigente |
| **Ofrecido a la máquina** / *No ofrecido hoy* | la versión vigente vincula el par y formulario, máquina y sector están activos (lo que exige el backend para conceder) |
| **Habilitado: <política>** / *Sin política de captura central* | existe una política de captura **en código** que lo acepta y el sector es operativo. *Sin política* **no** significa que el formulario no exista: puede registrarse por otra ruta especializada (p. ej. el registro de bobinas); se explica en la fila |
| **Concedido** / *No concedido* | hay una concesión activa |
| **Concedido · inerte** | concedido, pero falta algo para que sirva: usuario inactivo, el usuario no tiene el sector de la máquina, el sector no es operativo o el par ya no se ofrece. Se lista el motivo |

**Nada se presenta como acceso operativo efectivo**: un aviso fijo explica que las concesiones se registran y auditan pero todavía no se aplican a las capturas. Un par **no ofrecido** no tiene botón *Conceder* (y se listan aparte, con el motivo, los formularios publicados que la versión vigente no
vincula a la máquina o que no tienen versión publicada); una concesión **inerte** siempre se puede **revocar**, incluso si su par ya no figura en el catálogo de la máquina. Si el usuario no tiene el sector de la máquina se avisa, y **no se le concede automáticamente**. Según el bundle vigente, P1-01 figura de forma independiente en MP1 y MP3, P1-10 en las
cinco rebobinadoras y P1-31 solo en MP3; no se inventan formularios de Calidad en Rebobinado (la pantalla refleja la API).

## 4. Confirmación, envío y errores
- Antes de cambiar, un diálogo muestra **usuario, máquina, formulario y operación** y las advertencias que apliquen. Cancelar no envía nada; mientras se envía se deshabilitan ambos botones (un doble clic es una sola petición) y el diálogo no se puede cerrar.
- Tras **cualquier** respuesta se vuelve a leer el estado desde el backend (concesiones, historial y usuario); no se asume que el cambio se aplicó. Si la respuesta fue *idempotente* (`changed:false`) la interfaz lo dice («ya tenía concedido… No se modificó nada»).

| Resultado | Comportamiento |
|---|---|
| 401 | vuelve al Login y se descarta el estado administrativo (igual que sectores) |
| 403 (permiso u origen) | bloquea las acciones de **ambas** secciones, con su mensaje propio; nunca se confunde con sesión vencida |
| 404 usuario / máquina / formulario | mensaje específico y relectura del catálogo |
| 409 `PAIR_NOT_OFFERED` | «el par no se ofrece»; no se concedió nada; se vuelve a consultar el catálogo |
| 415 / 422 | solicitud inválida, sin reintento automático |
| 503 / red | **resultado incierto**: se relee el estado real y las acciones sobre ese usuario quedan bloqueadas hasta que una relectura completa lo confirme |

**Respuestas tardías.** Los recursos se identifican por sesión + usuario seleccionado: al cambiar de usuario se cancela la petición anterior y su resultado jamás se muestra en la vista del actual; el último resultado y la incertidumbre pertenecen a un usuario y no se muestran si hay otro seleccionado; el controlador se libera al desmontar o cerrar sesión (una respuesta tardía no
cierra la sesión siguiente).

## 5. Seguridad
La pantalla solo existe para quien ya entra en `/admin` (`user.manage`, decidido por la sesión antes de montar la consola); el frontend no decide autorizaciones reales (el backend las exige en cada endpoint). No se guardan cookies, tokens ni credenciales, y no se lee `document.cookie`.

## 6. Código
`lib/vinto/admin-grants.ts` (contratos, validadores estrictos, cliente, reglas, máquina de estados y controlador; **puro**, sin React) · `lib/vinto/admin.ts` (nuevos tipos de fallo y extracción de `createAdminRequester`, sin cambiar su comportamiento) · `lib/vinto/admin-api.ts` y `lib/vinto/use-admin.ts` (cliente y hook) ·
`components/vinto/admin/admin-grants-parts.tsx` (presentación) · `components/vinto/admin/admin-console.tsx` (cableado; la sección es opcional en la vista, así que la administración por sector se puede renderizar sola).

## 7. Pruebas
Nuevas: `scripts/admin-grants.test.mjs` (31: validadores y consistencia, cliente, errores, reglas, controlador, incertidumbre, vista por usuario, salvaguardas de fuente) y `scripts/admin-grants-ui.test.mjs` (15: componentes reales en cada estado). Adaptada una aserción de cableado de `scripts/admin.test.mjs` (todas las lecturas nuevas
alimentan el bloqueo por 403). Las 31 + 17 pruebas existentes de administración siguen pasando.

## 8. Límites y pendientes
- **Sin QA manual** (se hará en la VPS cuando terminen MF13-01 y MF13-02) y **sin autorización efectiva**: las concesiones no restringen nada todavía.
- El historial muestra hasta 200 filas; si hay más se avisa (`truncated`). Los catálogos se leen al seleccionar un usuario (no hay polling).
- Calidad en Rebobinado sigue pendiente de definición funcional (documentado en MF-13-01C.1); la pantalla no inventa nada.
- Despliegue: solo frontend; requiere el backend con MF-13-01C.1 y C.2 y el origen de la interfaz entre los permitidos (`Origin` obligatorio en los POST). Reversión: desplegar la versión anterior.

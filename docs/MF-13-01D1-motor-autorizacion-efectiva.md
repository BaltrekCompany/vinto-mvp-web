# MF-13-01D.1 — Motor central de autorización efectiva

Estado: **implementado y probado, NO conectado a ningún endpoint**. Ninguna ruta productiva lo llama, no hay migración nueva y no se tocó el frontend, el catálogo, los perfiles ni los formularios.

Código: `backend/app/authz/` (`policies.py`, `errors.py`, `engine.py`, `readiness.py`) · informe de solo lectura: `backend/authz_readiness.py` · pruebas: `backend/tests/test_authz_engine.py`.

## 1. Regla

Una operación queda autorizada **solo si se cumplen todas a la vez**:

| # | Condición | Dónde se evalúa |
|---|-----------|-----------------|
| 1 | Usuario existente, activo y autenticado | `vinto_master."user".active`; el llamador entrega un `AuthenticatedUser` y el motor **relee todo de la BD** (ignora permisos/sectores del objeto, que pueden estar desfasados) |
| 2 | Permiso funcional de sus perfiles **activos** (unión de perfiles) | `user_profile` + `profile.active` → `permissions_for_profiles` |
| 3 | Sector de la máquina activo, operativo y **concedido al usuario** | `sector.active`, `is_operational_sector`, `user_sector` |
| 4 | Máquina y formulario activos | `machine.active`, `form.active` |
| 5 | La política de **esa ruta** admite el formulario | `policies.py` (conjuntos disjuntos) |
| 6 | Versión publicada **vigente** (del área de la ruta) vinculada a la máquina | `form_version` (mayor `version_number` publicada) + `form_version_machine`; un vínculo solo histórico no cuenta |
| 7 | Concesión **activa** de la terna exacta (usuario, máquina, formulario) | `user_machine_form_grant` con `revoked_at IS NULL` |

Semántica de seguridad (cubierta por pruebas):

- La concesión **nunca** sustituye el permiso de perfil ni concede el sector; consultar no concede nada.
- Una concesión de MP1 no autoriza MP3; una de un formulario no autoriza otro.
- Una concesión activa cuyo par ya no se ofrece no autoriza nada.
- DATA_BALTREK (administra usuarios) no obtiene autorización de captura por tener o conceder accesos.
- Perfiles múltiples: unión de permisos; un perfil inactivo no aporta.
- Resultado explícito (`Decision`): `allowed` / `forbidden` / `not_found`, con razón interna estable (auditoría) y, si se permite, la versión y la concesión que lo respaldan.
- **Fallo de infraestructura ≠ acceso**: tabla ausente, privilegio faltante, conexión cerrada, bloqueo, fallo de serialización → `AuthorizationUnavailable` (503). Nunca se interpreta como concedido.
- Respuestas públicas fijas (`public_response`): 403 `FORBIDDEN`, 404 `NOT_FOUND`, 503 `AUTHORIZATION_UNAVAILABLE`; sin SQL, sectores, perfiles ni identificadores.
- Un llamador mal formado (sin `AuthenticatedUser`, operación desconocida) es `TypeError`: error de programación, no autorización implícita.

## 2. Políticas por operación (sin modificarlas)

Los conjuntos se leen **en vivo** de las constantes que ya usan los servicios de captura; no se copian ni se amplían.

| Operación | Ruta | Permiso | Área de la versión | Formularios admitidos |
|-----------|------|---------|--------------------|-----------------------|
| `production_capture` | `POST /api/captures` | `production.capture` | production | `capture_service.CENTRAL_FORM_CODES` |
| `bobbin_production` | `POST /api/bobbins` | `production.capture` | production | `{VINTO-P1-03}` (F3) |
| `quality_bobbin_capture` | `POST /api/quality/bobbins/{id}/captures` | `quality.capture` | quality | `CENTRAL_BOBBIN_FORM_CODES` ∪ (candidatos ∩ habilitados) |
| `quality_machine_capture` | `POST /api/quality/machines/{code}/captures` | `quality.capture` | quality | `MACHINE_QUALITY_FORM_CODES` |

Los cuatro conjuntos son **disjuntos** (prueba): `VINTO-P1-03` no se autoriza por la captura central aunque pertenezca al catálogo central, y los formularios de Calidad por máquina no se autorizan por la ruta de Calidad por bobina.

## 3. Matriz de endpoints (42 rutas; obtenida por introspección de la aplicación)

Rutas de **escritura de captura** (las que usarán el motor, en una tarea posterior):

| Endpoint | Permiso actual | Operación del motor | Sobre qué recae la terna |
|----------|----------------|---------------------|--------------------------|
| `POST /api/captures` | `production.capture` | `production_capture` | máquina y formulario del cuerpo |
| `POST /api/bobbins` | `production.capture` | `bobbin_production` | máquina del cuerpo + `VINTO-P1-03` |
| `POST /api/quality/bobbins/{id}/captures` | `quality.capture` | `quality_bobbin_capture` | máquina de la bobina + formulario del cuerpo |
| `POST /api/quality/machines/{code}/captures` | `quality.capture` | `quality_machine_capture` | máquina de la ruta + formulario del cuerpo |

Fuera del alcance del motor (siguen exactamente como están): administración (`/api/admin/*`, `user.manage`), asignaciones (`assignment.*`), órdenes de trabajo (`work_order.*`), autenticación, salud, y **todas las lecturas** (`GET /api/captures*`, `GET /api/bobbins/{id}`, `GET /api/quality/*`, `GET /api/production/machines`, `GET /api/captures/count`).

Decisión abierta (no se concede por defecto): ¿las **lecturas** de capturas/bobinas y la lista de máquinas/formularios disponibles deben filtrarse también por concesión? Hoy el motor no se aplica a ellas; cualquier cambio requiere decisión funcional expresa.

## 4. Concurrencia y revocación

Las rutas de escritura deberán llamar a `require(...)` / `authorize(..., lock=True)` **dentro de la misma transacción que registra la captura**. Con `lock=True` las filas que deciden el resultado se leen con `FOR SHARE` hasta COMMIT/ROLLBACK.

**Por qué `FOR SHARE` y no `FOR KEY SHARE`** (verificado con dos conexiones, no supuesto): la revocación es `UPDATE … SET revoked_at` y no cambia columnas clave (el índice único es parcial), de modo que `FOR KEY SHARE` **no** la bloquea y una captura se registraría con una concesión ya revocada. `FOR SHARE` sí choca con ese UPDATE. Las pruebas `test_for_share_blocks_an_update_of_revoked_at…` y `test_for_key_share_would_NOT_have_been_enough` lo demuestran, y el mutante «FOR KEY SHARE» es detectado.

Resultados demostrados:

- Revocación **confirmada antes** de la captura → denegada (la lectura se reevalúa con `revoked_at IS NULL`).
- Revocación **en curso** (sin confirmar) cuando llega la captura → la captura espera y, al confirmarse, la ve y se deniega (READ COMMITTED).
- Captura **en curso** cuando llega la revocación → la revocación espera a que termine la captura (esta quedó autorizada con una concesión vigente) y la siguiente captura se deniega.
- Reintentos idempotentes: repetir `authorize` en la misma transacción es inofensivo; conceder dos veces no duplica; revocar dos veces es inofensivo.
- Carga mixta (6 hilos: capturas con bloqueos, concesiones y revocaciones sobre 4 usuarios): sin interbloqueos ni decisiones inconsistentes.
- Sin transacción abierta (conexión en autocommit) `lock=True` **falla cerrado** (`NO_TRANSACTION`): fuera de `connection.transaction()` los bloqueos se liberarían al terminar cada sentencia. Bajo `REPEATABLE READ` un conflicto da `40001` → no disponible (falla cerrado).

### Qué se bloquea y qué no (límite de privilegios del rol real)

PostgreSQL exige privilegio `UPDATE` para **cualquier** bloqueo de fila (`FOR SHARE` y `FOR KEY SHARE`). Con los privilegios reales de `vinto_app` (`backend/roles/03_table_grants.sql`), verificado en PostgreSQL 17:

| Tabla | Privilegios de `vinto_app` | ¿Bloqueable? |
|-------|----------------------------|--------------|
| `user`, `profile`, `user_profile`, `sector`, `machine`, `user_machine_form_grant` | SELECT, INSERT, UPDATE | **Sí** — se bloquean |
| `user_sector` | SELECT, INSERT, DELETE | No (`42501`) |
| `vinto_config.form`, `form_version`, `form_version_machine` | SELECT | No (`42501`) |

Un primer diseño bloqueaba todas las tablas; con el rol real habría devuelto 503 **siempre**. Las pruebas `RestrictedRoleTests` reproducen esos privilegios y demuestran que el motor funciona y que el bloqueo de la concesión sigue impidiendo la revocación concurrente. Una prueba estática vigila que lo bloqueado coincida con lo que el archivo de roles concede.

**Riesgos residuales (documentados, no resueltos aquí):**

1. *Retiro de un sector concurrente a una captura* (`DELETE` de `user_sector`, no bloqueable). Mitigación sin tocar privilegios, para la integración: que la administración de sectores tome `SELECT … FROM "user" WHERE id = … FOR UPDATE` antes del DELETE; choca con el `FOR SHARE` del motor sobre la fila del usuario.
2. *Cambios del catálogo o de los vínculos durante una captura*: solo los hace el importador de referencias fuera de línea. Operativamente, importar en ventana sin capturas.
3. Los `UPDATE` de la fila de usuario (p. ej. desactivarlo) esperan hasta el fin de la captura en curso: efecto buscado, de duración breve.

### Orden de adquisición de bloqueos (fijo)

`usuario → perfiles del usuario → máquina y su sector → concesión` (la fila más disputada, al final). Quien modifica estas filas (administración de concesiones, desactivación de usuarios) toca **una sola** fila de autorización por transacción, así que no puede cerrar un ciclo con este orden. Orden global recomendado para las rutas al integrar: bloqueo asesor `vinto-capture-id` (ya existente) → motor → bloqueos asesores de máquina/asignación (ya existentes) → inserciones. Verifíquese contra cada servicio de captura al integrar (fuera del alcance de esta tarea).

## 5. Compatibilidad entre rutas

Verificada por pruebas, sin modificar políticas: captura central, F3 (`/api/bobbins`), Calidad por bobina y Calidad por máquina son operaciones distintas con conjuntos disjuntos. Los candidatos de Calidad por bobina siguen la constante viva `ENABLED_BOBBIN_CANDIDATE_FORM_CODES` (hoy iguales a los cuatro candidatos); **este cambio no habilita ni deshabilita ninguno**. Antes de activar, confirmar con producto si esa habilitación debe mantenerse.

## 6. Plan de activación (propuesto; nada se ejecutó)

No existe un entorno QA separado: la activación ocurre en el VPS existente, por lo que se hace gradual, reversible y con prueba previa.

1. **Medir el impacto (solo lectura).** Ejecutar `python authz_readiness.py` contra la base real (requiere autorización explícita del destino y de la credencial). Informa por operación cuántas ternas ya están cubiertas, cuáles **quedarían bloqueadas** (usuario con perfil y sector, máquina/formulario ofrecidos, sin concesión) y el total por usuario. Los usuarios reales pueden no tener concesiones individuales: este informe los identifica.
2. **Preparar las concesiones iniciales.** Producto/Baltrek revisa la lista y decide quién recibe qué; se conceden desde la interfaz/API de administración (con actor y motivo auditados). El informe no crea concesiones.
3. **Validar que ningún operador autorizado queda bloqueado.** Repetir el informe hasta que `would_be_blocked` solo contenga ternas que se decidieron no conceder.
4. **Endurecer privilegios (ver §7)** antes de activar.
5. **Modo de observación (opcional, explícito).** En una tarea posterior: el motor se evalúa *después* de la decisión actual y solo registra la decisión (operación, usuario, máquina, formulario, razón) sin cambiar la respuesta. Debe estar activado por un indicador de configuración, limitado a operaciones nombradas y a una ventana de tiempo, ser auditable, y **nunca presentarse como autorización efectiva**.
6. **Activación controlada por operación**, una a la vez, con indicador de configuración por operación, en una ventana de baja actividad, con la administración lista para conceder en caliente.
7. **Reversión.** Apagar el indicador de la operación; el motor solo lee, así que no hay migración que deshacer. Las concesiones creadas permanecen. Si la causa fuera un 503 de infraestructura, el indicador apagado devuelve el comportamiento actual.

## 7. Escritura directa de `vinto_app` sobre la tabla de concesiones (propuesta; no se cambió ningún privilegio)

Hoy `vinto_app` tiene `SELECT, INSERT, UPDATE` sobre `user_machine_form_grant` (0007). Los triggers (0008/0009) exigen actor para revocar y bloquean borrado/reescritura de historia, pero el rol puede **insertar directamente** una concesión sin pasar por el servicio (sin validar que el par se ofrece ni que el actor sea administrador) y el actor es un valor declarado por la sesión.

Propuesta, a decidir antes de activar:

1. Retirar `INSERT, UPDATE` directos de `vinto_app` sobre la tabla y exponer dos funciones `SECURITY DEFINER` (conceder/revocar) propiedad de un rol dedicado, que validen el par ofrecido y reciban el actor explícito; `vinto_app` solo tendría `SELECT` + `EXECUTE`.
2. Como paso intermedio, privilegios por columna: `UPDATE (revoked_at, revoked_by)` únicamente.
3. Reconocer el límite: `vinto_app` también puede escribir `user_profile` y `user_sector` (por diseño actual), de modo que quien comprometa la aplicación puede escalar por otras vías; endurecer solo esta tabla reduce, no elimina, ese riesgo.

## 8. Ambigüedades documentadas (no se concede acceso por defecto)

- **Reintento de una captura ya guardada**: se vuelve a autorizar; una revocación posterior lo deniega. Es lo seguro, pero puede rechazar el reenvío de un operador cuyo acceso se acaba de retirar.
- **Lecturas** de capturas/bobinas/máquinas: sin concesión exigida hoy (ver §3).
- **Candidatos de Calidad por bobina**: el motor sigue la constante viva (ver §5).
- **Formulario compartido MP1/MP3** (`VINTO-P1-01`): una definición y versión, concesiones independientes por máquina (decisión de MF-13-01A, respetada).

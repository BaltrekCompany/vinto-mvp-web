# MF-13-01D.3B.2 — Integración del rol de identidad

Estado: **implementado y probado en bases PostgreSQL efímeras. NO aplicado en ningún entorno persistente, ni ejecutado por `deploy.sh`. No revoca ningún privilegio a `vinto_app`** (eso es D.3B.4). Sin la variable nueva, el comportamiento es exactamente el anterior.

Fase 2 del diseño aprobado en `docs/MF-13-01D3B-endurecimiento-privilegios-concesiones.md` (§5 y §7). Planificación general: `docs/MF-13-PLAN-release-unico.md`.

## 1. Qué cambia

La aplicación pasa a tener dos conexiones con propósito distinto:

| Conexión | Rol | Rutas |
|----------|-----|-------|
| Negocio (`get_connection`, `DATABASE_URL`) | `vinto_app` | Resolución de sesiones (`current_user`, `/api/auth/me`, `require_permission`), capturas, bobinas, Calidad, órdenes, asignaciones: todo lo que ya existía |
| Identidad (`get_identity_connection` / `open_identity_connection`, `IDENTITY_DATABASE_URL`) | `vinto_identity` | `POST /api/auth/login`, `POST /api/auth/logout`, **toda** la API `/api/admin/*` (usuarios, sectores y concesiones máquina-formulario, lecturas incluidas), `manage_user.py` y `create_user.py` |

`require_permission(USER_MANAGE)` sigue resolviendo la sesión con el rol de negocio; la escritura administrativa se ejecuta después con el de identidad (dos conexiones por petición administrativa).

## 2. Configuración

| Variable | Obligatoria | Efecto |
|----------|-------------|--------|
| `IDENTITY_DATABASE_URL` | No | Ausente o vacía: las rutas de identidad usan `DATABASE_URL` (comportamiento anterior, estado de reversión). Presente: usan SOLO esta URL |
| `IDENTITY_TEST_DATABASE_URL` | No | Igual, para los CLI con `--target test` (conserva la guarda de nombre `*_test`) |
| `IDENTITY_PASSWORD` | Solo al ejecutar `00c` | Contraseña del rol, leída del entorno del proceso `psql`; nunca en la línea de comandos |

Reglas de la conexión (`backend/app/database.py`):
- **Sin retroceso silencioso:** con la URL definida, si la conexión falla se responde `503 {"status":"error","database":"unavailable"}`; nunca se intenta `DATABASE_URL`. Un retroceso ocultaría una mala configuración justo antes del corte y, después del corte, fallaría de todos modos.
- Los registros no contienen URL, usuario, host ni contraseña; se registra una sola vez por proceso el modo (`dedicated`/`shared`).
- `logout` abre su conexión dentro del manejador (no como dependencia) para seguir borrando la cookie si la conexión falla; ahora con la de identidad.
- `PG_PRIVILEGE_MODE` no cambia: la variable es opcional en ambos modos.

`deploy/mvp/env/backend.env.example` incluye las dos variables **comentadas**: no se activan hasta que `00c` y `03c` estén aplicados y verificados.

## 3. Privilegios del rol de identidad

`backend/roles/00c_create_identity_role.sql` crea `vinto_identity` (LOGIN, sin superusuario/CREATEDB/CREATEROLE, `search_path` vacío, idempotente, con detección de colisión de nombre). `backend/roles/03c_d3b2_identity_role_grants.sql` (`vinto_migrator`) **solo concede**, en una transacción, con guardas y verificación final, lo que la fase `D3B2` del prototipo aprobado define (una prueba exige que las sentencias coincidan):

| Objeto | `vinto_identity` |
|--------|------------------|
| `vinto_master.user`, `user_profile`, `user_machine_form_grant` | `SELECT`, `INSERT`, `UPDATE` |
| `vinto_master.user_sector` | `SELECT`, `INSERT`, `DELETE` |
| `vinto_master.profile` | `SELECT` + `UPDATE (active, updated_at, updated_by)` |
| `vinto_master.*` y `vinto_config.*` restantes | `SELECT` |
| `vinto_auth.credential`, `session` | `SELECT`, `INSERT`, `UPDATE` |
| `vinto_auth.auth_event` | `SELECT`, `INSERT` |
| `vinto_audit.audit_event` | `INSERT` (los disparadores de auditoría son `SECURITY INVOKER`) |

No puede: `DELETE` de concesiones máquina-formulario, modificar o borrar auditoría, tocar `vinto_txn` ni el catálogo. La auditoría registra `session_user`, así que cada escritura queda atribuida al rol de login real.

## 4. Autorización administrativa y revocación concurrente

**Verificación previa (comportamiento anterior):** `require_permission(USER_MANAGE)` comprobaba la sesión en una transacción y la escritura se hacía en otra: un administrador desactivado en medio podía completar una operación ya iniciada. Con dos conexiones esa separación es más visible, así que se cierra:

`backend/app/admin/actor.py::require_actor_authorized` se ejecuta **dentro de la misma transacción de la escritura** (`change_grant` y `change_machine_form_grant`) y comprueba que el actor sigue activo y conserva `user.manage` por un perfil activo, tomando `FOR KEY SHARE` sobre su usuario, `user_profile` y `profile`:
- `deactivate_user` toma `FOR UPDATE`: **espera** a que la escritura en curso confirme, o ve su propia desactivación ya confirmada y la siguiente escritura se rechaza con `403 ACTOR_NOT_AUTHORIZED` ("Permiso insuficiente") sin escribir nada.
- `FOR KEY SHARE` **no** choca con el `FOR NO KEY UPDATE` de `revoke_sector` (D.3A) ni con el `FOR SHARE` del motor de autorización: dos administradores que se modifican mutuamente no se interbloquean (prueba con tres hilos concurrentes).
- No comprueba la sesión: un `logout` en paralelo no invalida una operación ya iniciada (la desactivación del usuario sí, porque revoca sus sesiones). Es el comportamiento de siempre.

Las rutas siguen exigiendo sesión válida (401) y `user.manage` (403): probado sin cookie, con operador y con la sesión resuelta por el rol de negocio.

## 5. Reversión

1. **Conexión (suficiente por sí sola):** quitar `IDENTITY_DATABASE_URL` y reiniciar. Vuelve el rol único. Probado: sin la variable la conexión de identidad es idéntica a la anterior.
2. **Privilegios (opcional):** `backend/roles/rollback/ROLLBACK_D3B2.sql` quita a `vinto_identity` lo concedido por `03c`. **Se niega a continuar si D.3B.4 está aplicado** (`vinto_app` sin el DML de identidad): primero `ROLLBACK_D3B4`, para que nunca quede un estado en que ningún rol pueda administrar usuarios. El rol no se elimina.
3. Revertir el código es revertir el PR; con la variable ausente no es necesario.

**Prohibido:** quitar `IDENTITY_DATABASE_URL` mientras D.3B.4 siga aplicado (login y administración fallarían con `42501`).

## 6. Pruebas

`backend/tests/test_d3b2_identity_role.py` (50 pruebas), además de las 161 de auth/admin/CLI ya existentes, que pasan sin cambios:

| Qué | Prueba |
|-----|--------|
| Sin la variable = comportamiento anterior; con ella, solo esa URL; con fallo, 503 sin retroceso ni filtrar datos | `ConnectionLayerTests` |
| Qué ruta usa qué conexión; nada de negocio usa identidad | `WiringTests`, `CliSelectionTests` |
| `03c` = fase `D3B2` del prototipo, aditivo, idempotente, sin privilegios de más; `ROLLBACK_D3B2` y su guarda | `IdentityScriptsTests` |
| Revocación concurrente del actor, sin interbloqueos; cuatro capturas en `enforce` con el negocio tras el corte | `ActorRecheckTests` |
| API completa con **roles LOGIN reales** (`session_user` distinto): login, `/me`, logout, concesiones de sector y de máquina-formulario, auditoría con el rol de identidad, 401/403, actor revocado entre comprobación y escritura, CLI `create_user` y `manage_user` | `ApiSharedModeTests` (sin la variable), `ApiDedicatedModeTests` (con la variable), `ApiAfterTheCutTests` (con la variable y el corte D3B4 aplicado en la base de **prueba**) |
| URL de identidad rota: 503, un único intento, sin escrituras, sin retroceso, cookie borrada en `logout` | `ApiDedicatedFailureTests` |

Mutantes comprobados: quitar la revalidación del actor, volver a cablear `login` al rol de negocio o añadir un retroceso a `DATABASE_URL` hacen fallar las pruebas.

**Versión de PostgreSQL:** las pruebas locales se ejecutaron en **PostgreSQL 16.15**. `.github/workflows/d3b1-postgres17.yml` ahora también ejecuta esta suite en un servicio `postgres:17` (y falla si no es 17.x), pero **no se ha ejecutado**: no hay compatibilidad con PostgreSQL 17 verificada hasta que ese flujo pase.

## 7. Riesgos y límites

1. **Sin D.3B.4 no hay protección:** `vinto_app` conserva todo; un SQL arbitrario con el rol de negocio aún puede escalar privilegios. Este PR deja lista la separación, no la activa.
2. **Dos secretos en el mismo host** y dos conexiones por petición administrativa (coste mínimo, tráfico de baja frecuencia).
3. **Actor declarado por la aplicación** (`vinto.actor_id`): sin cambios; depende de la integridad del código que usa el rol de identidad.
4. Un compromiso del proceso completo posee ambas credenciales (no cubierto, ver §3 del diseño).
5. La importación de referencias sigue exigiendo `REFERENCE_DATABASE_URL` para D.3B.1 (ya documentado); no depende de este cambio.
6. Un fallo de la conexión de identidad deja sin login ni administración (sin degradación silenciosa a propósito); la aplicación de negocio con sesiones ya abiertas sigue funcionando.

## 8. Configuración requerida para el futuro despliegue

Nada de esto se ejecuta con este PR. En el release único (ver el plan): crear `vinto_identity` (`00c`) y concederle (`03c`) antes de desplegar el código; desplegar con la variable ausente y comprobar que nada cambió; definir `IDENTITY_DATABASE_URL` y reiniciar; verificar con ambos roles (D.3B.3); solo entonces el corte (D.3B.4). `deploy.sh` no ejecuta `00c`, `03c` ni los rollbacks; una prueba lo exige.

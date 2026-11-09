# USR-05 — Interfaz administrativa de usuarios

Estado: implementación aislada en PR, **sin merge ni despliegue**. Baseline: USR-01…04 integrados en main.

## Alcance
Se amplía la consola existente /admin con una sección «Gestión de cuentas» y acciones por usuario:
- **Crear** cuenta: username, nombre, un perfil activo del endpoint GET /api/admin/profiles, contraseña de 12–256 caracteres. Sin concesiones implícitas.
- **Editar** nombre y perfil: PATCH /api/admin/users/{id}; username inmutable y revocación de sesiones cuando cambia el perfil.
- **Restablecer contraseña**: POST /api/admin/users/{id}/reset-password; nunca se imprime ni se persiste el secreto.
- **Desactivar/reactivar**: POST /api/admin/users/{id}/deactivate|reactivate con motivo. Revocación de sesiones, nuevo login y protección servidor del último administrador.
- Conserva la administración existente de sectores y máquina–formulario; no modifica reglas industriales, perfiles, catálogos, OT ni permisos.

## Contratos y seguridad
- Todo está detrás de la compuerta /api/auth/me + permiso user.manage, con revalidación del backend en las escrituras.
- Fetch con credentials: include, cache: no-store, sin leer cookies ni establecer encabezados de identidad/Origin/actor.
- API sin datos de demostración, usuario seleccionado validado, catálogo real de perfiles y parsers cerrados que descartan respuestas inconsistentes.
- La confirmación es explícita, no hay envío doble y la navegación entre usuarios se bloquea durante la operación. Los controladores se liberan al salir de la sesión.
- Tras cada respuesta, se releen las listas centrales. Si hubo un fallo de transporte, el resultado se considera **incierto**; se bloquean nuevas acciones hasta una relectura manual comprobada.
- Formularios de contraseña con autocomplete=new-password, doble captura y limpieza de estado, sin almacenamiento persistente ni exhibición en la UI.

## QA obligatorio
- scripts/usr-05-admin-users.test.mjs: contratos, métodos y rutas HTTP, datos mínimos, errores 401/403/409/415/422/503, validación, reentrancia y descarte de respuesta tardía.
- scripts/usr-05-admin-users-ui.test.mjs: render de formularios y controles activos, bloqueados e inciertos, sin acceso real al backend.
- Regresiones previas de consola y concesiones, TypeScript, ESLint y compilación frontend.
- GitHub Actions: .github/workflows/usr-05-admin-ui.yml.
- Gate de revisión: **no merge hasta CI PASS y auditoría del diff**; despliegue por VPN independiente, con respaldo y rollback.

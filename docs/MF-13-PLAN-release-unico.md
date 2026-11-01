# MF-13 — Planificación: un único release controlado y QA manual sobre ese release

Estado: **planificación; no autoriza ningún despliegue ni ningún cambio en la VPS.** Sustituye cualquier referencia anterior a un entorno de QA persistente separado.

## 1. Decisión del proyecto

- **No se construye un entorno QA persistente.** El desarrollo se completa en el repositorio con pruebas locales/efímeras y CI, y se despliega **una sola vez, de forma controlada**, en la infraestructura productiva de VINTO, que hoy **no tiene usuarios finales operando**.
- El **QA manual** se hace sobre ese mismo release, con acceso restringido (solo el equipo de aceptación).
- Los usuarios finales se abren **después de la aceptación** del QA manual.
- Se conservan: pruebas locales/efímeras, CI con PostgreSQL 17, reversión probada de cada fase y la **protección absoluta de TVC** (ningún paso toca `postgres-vinto`, `vinto-web.service`, `/opt/vinto-web`, `vinto_default` ni credenciales/datos de TVC).
- No se duplican despliegues ni infraestructura.

## 2. Hoja de ruta

| Hito | Contenido | Estado |
|------|-----------|--------|
| MF-13-01D.3A | Sincronización de la revocación de sectores con las capturas | Fusionado |
| MF-13-01D.3B.1 | `vinto_app` pierde `INSERT`/`UPDATE` de tabla sobre `profile`, `machine`, `sector` (script, rollback, guarda de `postgres-grants`) | Fusionado (PR #99). No aplicado en la VPS |
| **MF-13-01D.3B.2** | Rol de identidad: `IDENTITY_DATABASE_URL`, login/logout/administración/CLI con la conexión de identidad, revalidación del actor, scripts `00c`/`03c`/rollback | **Implementado en este PR** (`docs/MF-13-01D3B2-integracion-rol-identidad.md`). No aplicado en la VPS |
| MF-13-01D.3B.3 | Puerta de verificación con ambos roles (login, logout, sesiones, administración, concesiones, auditoría y las cuatro capturas) | **Pendiente de completar antes del release.** Hoy hay evidencia en bases efímeras con PostgreSQL 16; falta PostgreSQL 17 (CI) y repetirla sobre la instalación del release |
| MF-13-01D.3B.4 | Corte: `vinto_app` pierde el DML de identidad (`D3B4` del prototipo, con guardas y reversión) | **Pendiente. Se ejecuta dentro del release único, solo con D.3B.3 aprobada** |
| MF-13-02 | Frontend por permisos (la interfaz se muestra y se restringe según los permisos del usuario) | Pendiente |
| Release único | Un solo despliegue controlado en la VPS con todo lo anterior | Pendiente de autorización explícita |
| QA manual | Aceptación sobre ese release, acceso restringido | Posterior al release |
| Apertura | Acceso a usuarios finales | Posterior a la aceptación del QA manual |

"Finalizar" D.3B.2, D.3B.3 y D.3B.4 significa, para cada una, cumplir sus criterios de la §3; este documento no las da por cumplidas salvo D.3B.2 en su implementación.

## 3. Criterios de finalización

| Fase | Criterio |
|------|----------|
| D.3B.2 | Código y scripts fusionados; 50 pruebas propias y las existentes en verde; CI PostgreSQL 17 en verde; sin la variable, comportamiento idéntico al anterior |
| D.3B.3 | Con `IDENTITY_DATABASE_URL` definida **y el script `D3B4` aplicado en una base aislada**: login, logout, `/me`, administración (usuarios, sectores, concesiones), CLI y las cuatro capturas aprueban; `current_user` de cada conexión es distinto; el ensayo de `ROLLBACK_D3B4` devuelve la matriz anterior; aprobación humana registrada |
| D.3B.4 | Aplicado en el release, en una transacción, con las guardas del script; verificación con `07_verification_queries.sql`; `ROLLBACK_D3B4` disponible y ensayado |

## 4. Orden del release único (a ejecutar solo con autorización explícita)

1. Respaldo verificado y confirmación de TVC (`TVC_BACKUP_CONFIRMED`); ninguna fase toca TVC.
2. Aprovisionamiento con el procedimiento existente (`postgres-roles`, `migrate`, `postgres-grants`, que ya falla cerrado si D.3B.1 está aplicado) y, a mano, `00c` y `03c`; `03b` si se decide adoptar D.3B.1.
3. Despliegue del código **sin** `IDENTITY_DATABASE_URL`: comprobar que nada cambió.
4. Definir `IDENTITY_DATABASE_URL` y reiniciar: puerta D.3B.3 sobre la instalación.
5. Corte D.3B.4 (con ventana corta y `ROLLBACK_D3B4` a mano).
6. Frontend MF-13-02 y `healthcheck`.
7. Entrega a QA manual restringido.

Puntos de reversión: quitar `IDENTITY_DATABASE_URL` (solo antes del corte), `ROLLBACK_D3B4` y luego quitar la variable (después del corte), `rollback.sh version <sha>` del despliegue. Orden prohibido: quitar la variable con el corte aplicado.

## 5. Condiciones previas a pedir el release

- `REFERENCE_DATABASE_URL` definida (o `PG_PRIVILEGE_MODE=hardened`) antes de D.3B.1.
- CI en PostgreSQL 17 en verde (o una instancia 17 aislada); hoy solo hay evidencia en 16.15.
- Revisión humana de los PR y autorización explícita para tocar la VPS.

## 6. Qué no se hace

No hay QA persistente, no se duplican despliegues, no se toca la VPS, TVC, credenciales reales ni datos operativos hasta la autorización del release, y no hay merge automático.

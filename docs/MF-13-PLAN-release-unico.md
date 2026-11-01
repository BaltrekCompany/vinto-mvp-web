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
| MF-13-01D.3B.2 | Rol de identidad: `IDENTITY_DATABASE_URL`, login/logout/administración/CLI con la conexión de identidad, revalidación del actor, scripts `00c`/`03c`/rollback | Fusionado (PR #100). No aplicado en la VPS |
| **MF-13-01D.3B.3** | Puerta de verificación con ambos roles (login, logout, sesiones, administración, concesiones, auditoría y las cuatro capturas) | **Automatizada en este PR** (`docs/MF-13-01D3B3-D3B4-puerta-y-corte.md`): la aprobación es válida con la evidencia de PostgreSQL 17 (CI). **Se repite sobre la instalación en el punto de control C5 del release** |
| **MF-13-01D.3B.4** | Corte: `vinto_app` pierde el DML de identidad (`03d` y `ROLLBACK_D3B4`, con guardas y reversión) | **Scripts preparados y probados en este PR. NO ejecutado.** El corte real exige una aprobación independiente (punto C6) durante el release único, con D.3B.3 aprobada |
| MF-13-02 | Frontend por permisos (la interfaz se muestra y se restringe según los permisos del usuario) | Pendiente |
| Release único | Un solo despliegue controlado en la VPS con todo lo anterior | Pendiente de autorización explícita |
| QA manual | Aceptación sobre ese release, acceso restringido | Posterior al release |
| Apertura | Acceso a usuarios finales | Posterior a la aceptación del QA manual |

"Finalizar" cada fase significa cumplir sus criterios de la §3. Estado: D.3B.2 implementada y fusionada; D.3B.3 y D.3B.4 **preparadas en código**; su finalización (puerta aprobada en PostgreSQL 17 y repetida en la instalación, y corte con su aprobación) ocurre en el release único. Preparar `03d` no autoriza su ejecución.

## 3. Criterios de finalización

| Fase | Criterio |
|------|----------|
| D.3B.2 | Código y scripts fusionados; 50 pruebas propias y las existentes en verde; CI PostgreSQL 17 en verde (cumplido); sin la variable, comportamiento idéntico al anterior |
| D.3B.3 | Con `IDENTITY_DATABASE_URL` definida **y el script `D3B4` aplicado en una base aislada**: login, logout, `/me`, administración (usuarios, sectores, concesiones), CLI y las cuatro capturas aprueban; `current_user` de cada conexión es distinto; el ensayo de `ROLLBACK_D3B4` devuelve la matriz anterior; aprobación humana registrada |
| D.3B.4 | Aplicado en el release, en una transacción, con las guardas del script; verificación con `07_verification_queries.sql`; `ROLLBACK_D3B4` disponible y ensayado |

## 4. Orden del release único (a ejecutar solo con autorización explícita)

Detalle paso a paso, puntos de control y reversiones: `docs/MF-13-RELEASE-unico-procedimiento.md`.

1. Respaldo verificado y confirmación de TVC (`TVC_BACKUP_CONFIRMED`); ninguna fase toca TVC.
2. Aprovisionamiento con el procedimiento existente (`postgres-roles`, `migrate`, `postgres-grants`, que falla cerrado si D.3B.1 o D.3B.4 están aplicados) y, a mano, `03b`, `00c` y `03c`, con el preflight `08_release_preflight.sql` antes de cada fase.
3. Despliegue del código **sin** `IDENTITY_DATABASE_URL`: comprobar que nada cambió.
4. Definir `IDENTITY_DATABASE_URL` y reiniciar: puerta D.3B.3 sobre la instalación.
5. Corte D.3B.4 **solo con la aprobación independiente (C6)**, con ventana corta y `ROLLBACK_D3B4` a mano; `ROLLBACK_D3B4` siempre ANTES de quitar `IDENTITY_DATABASE_URL`.
6. Frontend MF-13-02 y `healthcheck`.
7. Entrega a QA manual restringido.

Puntos de reversión: quitar `IDENTITY_DATABASE_URL` (solo antes del corte), `ROLLBACK_D3B4` y luego quitar la variable (después del corte), `rollback.sh version <sha>` del despliegue. Orden prohibido: quitar la variable con el corte aplicado.

## 5. Condiciones previas a pedir el release

- `REFERENCE_DATABASE_URL` definida (o `PG_PRIVILEGE_MODE=hardened`) antes de D.3B.1.
- CI en PostgreSQL 17 en verde (o una instancia 17 aislada); hoy solo hay evidencia en 16.15.
- Revisión humana de los PR y autorización explícita para tocar la VPS.

## 6. Qué no se hace

No hay QA persistente, no se duplican despliegues, no se toca la VPS, TVC, credenciales reales ni datos operativos hasta la autorización del release, y no hay merge automático.

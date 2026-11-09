# USR-06 — QA integral y preparación de release

Estado: propuesta aislada. **Prohibido interpretar el CI como autorización para migrar, activar o reiniciar producción.**

## Baseline y principio de integridad
- `main` al comienzo de USR-06: `c714681424d4c07bad255b224b5657c5efa0cb1f` (USR-01 a USR-05 fusionados).
- Último release identificado en VPS el 09/11/2026: `c10d0c8fde5fd3c48f454dfdf50098356268b000`; confirmar de nuevo de forma independiente.
- El código USR-02 requiere `0024_user_one_profile.sql`; USR-03 requiere `0025_credential_username_immutable.sql`. **No inferir esquema productivo a partir de CI aislado.**
- No confundir `backend/migrate.py --status` del release actual con `deploy.sh check-release <target>` del release nuevo. El primero conoce solo migraciones contenidas en su checkout; el segundo exige un release objetivo completamente preparado.

## Puertas obligatorias
1. **G0 — Código:** diff sin cambios no autorizados, commit SHA completo y fijo, firmas CI; USR-06 integrado en main solo tras PR revisado.
2. **G1 — Laboratorio aislado:** PostgreSQL 17 aplica todas las migraciones y `--check` PASA; suites de USR-02/03/04 + autenticación + grants; regresión MP3/E1-08; 108 pruebas frontend, tsc, eslint y build; bash -n de scripts. CI usa exclusivamente runner y base descartables.
3. **G2 — Inventario VPS solo lectura:** identificar release `current`, procesos, versiones, endpoints health y lista de backups verificados sin mostrar credenciales. Confirmar el historial real de migraciones y anomalías de perfiles antes de aplicar 0024. Confirmar modo de base/identidad desde configuración sin imprimir secretos.
4. **G3 — Preparación del release exacto:** artefacto frontend construido de SHA exacto, venv y enlace de configuración, comprobación de checksum, disco suficiente y backup verificable; los procedimientos mutables requieren autorización posterior.
5. **G4 — Migración explícita:** solo tras backup *restaurado y verificado* + gate sin anomalías; ejecutar procedimiento `migrate-release` para el SHA objetivo con aprobación separada. NO se automatiza en USR-06.
6. **G5 — Activación aprobada:** sin tocar TVC; verificar D2/E1 y banderas existentes, evaluar compatibilidad rollback del esquema, ejecutar activate y comprobar salud; gate de reversión listo. NO se automatiza en USR-06.
7. **G6 — QA manual controlado:** usuario administrador existente (sin modificar último admin), usuario operativo de QA específico; creación, visualización sin grants, asignación sector/máquina-formulario, edición de nombre/perfil, reset clave, cierre de sesión, baja/reactivación con motivo, historial, negativas de permiso (403), validaciones (422), 409 del último administrador, y regresiones MP3 y E1. No probar operaciones destructivas en cuentas reales.
8. **G7 — Post-release:** confirmar commit activo, health backend + DB + frontend, sesiones nuevas, audit logs agregados, y sin regresión de OT/capturas ni E2-D2. Registrar resultados con timestamps.

## Política de seguridad/rollback
- No publicar `.env`, contraseñas, token de sesión, dump, SQL con datos personales ni identificadores de usuarios reales.
- **No aplicar `preflight.sh infra` a ciegas** a un VPS activo: ese script exige que 3100/8100/6544 estén libres y puede producir un falso NO-GO sobre servicios sanos. Utilizar inspección específica de instalación activa.
- Migraciones 0024/0025 son cambios de esquema transaccionales sin downgrade automático. Restaurar la versión anterior de la aplicación NO revierte el esquema. El rollback debe comprobar compatibilidad y disponer de estrategia específica, no asumir reversibilidad automática.
- GitHub merge, preparación de release, migración, activación y rollback son decisiones **independientes**.
- No hacer QA productivo de auto-desactivación del único administrador.

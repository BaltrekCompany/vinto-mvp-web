# VINTO E2-D2 — Recuperación y reversión (B2-B)

**Estado del documento:** contrato técnico para revisión; no constituye orden de despliegue. D2 continúa OFF. Solo aplica a código y migraciones 0019–0022 instalados y con QA validado en la versión exacta.

## Estados y acciones permitidas

| Handoff | Operación de recuperación | Regla fundamental |
| --- | --- | --- |
| `pending` | Supervisión cancela con motivo; si bandera D2 ON, Jefatura puede continuar publicación autorizada | Sin nueva versión; nunca borrar la reserva histórica |
| `published` | Supervisión reintenta reasignar, incluso con D2 OFF; con candados OT -> máquina -> asignación -> E1 -> handoff | No crear segunda versión ni actualizar el snapshot publicado |
| `reassigned` | Operación acusa por E2-C1 la **asignación nueva y versión exacta**, incluso con D2 OFF | Bloqueo de inicio/activación/captura hasta el acuse |
| `acknowledged` | Supervisión puede iniciar línea según condiciones E1; el acuse está archivado | No reescribir ni reutilizar recibos |
| `cancelled` | No hay relevo abierto; la línea conserva el flujo de E1 | La cancelación solo procede antes de publicar |

No existe transición de `published` a `cancelled`; esa acción perdería la relación con una versión inmutable. Si no hay turno, permisos o consistencia de máquina para terminar el relevo, **no efectuar un rollback de código**: dejar `published`, identificar el bloqueo y reintentar con Supervisión cuando se resuelva la condición; nunca borrar la versión ni saltar directamente a E1.

## Consulta segura para Supervisión

`GET /api/work-orders/handoffs/{handoff_id}` requiere `assignment.manage`, sesión autenticada y alcance de **toda** la OT. Responde solo con el estado, referencias técnicas, versiones y acción sugerida; no se debe compartir el resultado con otros sectores. Funciona con D2 OFF para facilitar recuperación de reservaciones anteriores. No es endpoint de reparación automática.

## Preflight de rollback / desactivación / habilitación

Con la versión y sus migraciones ya instaladas, un operador autorizado ejecuta el módulo del backend **como el usuario de servicio**, con su configuración existente y sin argumentos secretos:

```bash
cd /opt/vinto-mvp-web/current/backend
./.venv/bin/python -m app.work_orders.handoff_rollout_cli rollback
./.venv/bin/python -m app.work_orders.handoff_rollout_cli disable
./.venv/bin/python -m app.work_orders.handoff_rollout_cli enable
```

El módulo se ejecuta en **REPEATABLE READ READ ONLY**, valida checksums de migraciones 0019–0022, trigger SQL de E1 y estado agregado de reservas. No imprime URLs, contraseñas, IDs de OT, usuarios ni capturas.

- `0`: puerta técnica sin bloqueos. **No equivale a autorización de despliegue**.
- `2`: existen reservas abiertas, falta una migración/checksum o trigger exigido: NO-GO.
- `3`: no hay acceso seguro a base de datos/configuración: NO-GO.

**Limitación conocida:** el CLI todavía no está conectado automáticamente a `deploy/mvp/scripts/rollback.sh` ni a cualquier cambio de `.env` o de systemd que desactive flags. Hasta integrar y probar esa puerta operativa de extremo a extremo, el rollback/habilitación D2 es **NO-GO**. Ejecutar el preflight manual no elimina la necesidad de esa integración.

## Puertas previas a habilitar D2

1. Migraciones 0019–0022 aditivas y checksum exacto; DB backup comprobado mediante restauración de prueba.
2. Pruebas PostgreSQL 17 de permisos y concurrencia `start_line / reassign / E2-C1 receipt / F3/F6`, sin regresiones E1, E2-B/C/D1.
3. Backfill cero; ninguna OT operativa modificada por la preparación.
4. Preflight agregado libre de reservas abiertas, rollback seguro ensayado con un release anterior compatible y puerta integrada al script.
5. QA manual por Jefatura, Supervisión y Operación en entorno autorizado; D2 OFF hasta aprobación explícita.
6. Si existen reservas abiertas, se prohíbe **deshabilitar el flag para desbloquear** o retroceder a un release sin guardas; el trigger E1 es una defensa adicional, no la única.
7. Registrar versión exacta del release, controles, hora y actores de la QA sin difundir identificadores de OT personales.

## Contrato de notificaciones

El acuse de E2-C1 sigue siendo por usuario de Operación + asignación nueva + versión publicada. E2-C2 conserva el aviso para Supervisión. Ni el acuse global de otra OT ni el de otro operador sustituyen la evidencia requerida para completar el relevo. La aceptación no realiza capturas ni inicia producción automáticamente.

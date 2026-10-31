# MF-13-01B.3 · Endurecimiento de las concesiones usuario–máquina–formulario

Revisión de los riesgos de integridad de la infraestructura del PR #83 (migración 0007, `app/auth/machine_form_grants.py`) **antes** de exponer una API administrativa. Sin endpoints, sin pantallas, sin conectar las
concesiones a las capturas, sin tocar P1-10, P1-31, Calidad ni perfiles. La migración 0007 no se modifica.

## 1. Resultado del preflight
Los riesgos **no estaban controlados**: se reprodujeron en una base PostgreSQL 17 aislada antes de corregir nada (sondas de solo SQL/servicio, ver §4). Hay dos correcciones: una de servicio y una migración nueva (0008).

## 2. Control 1 · Qué formularios se pueden conceder
| | `grant_machine_form` en 0007 | `production_access.production_machines` | Después (este PR) |
|---|---|---|---|
| Formulario activo | no se comprobaba | `f.active` | **se exige** |
| Máquina y sector activos | no se comprobaba | `m.active AND s.active` | **se exige** |
| Versión | **alguna** versión publicada vinculada a la máquina | la **más reciente** publicada | la **más reciente** publicada |

Efecto del desajuste: un par que solo una versión **anterior** vincula (p. ej. P1-05 v1 en MP1 tras MF-12A, que dejó la v2 solo en MP3), o con formulario/máquina inactivos, se podía conceder aunque la API de
disponibilidad no lo ofreciera. Eran concesiones inertes pero engañosas, y habrían cobrado vida si luego se retirara la versión vigente.

**Política aplicada (`_require_offered`):** formulario activo + máquina activa + sector de la máquina activo + la versión publicada más reciente del formulario vinculada a la máquina; si no, `FormNotLinkedToMachineError` con el
motivo. Una prueba la contrasta con `production_access` sobre las 18 máquinas × los 14 formularios centrales: **el conjunto concedible es idéntico al ofrecido**.

- No se borra ni se modifica ninguna versión histórica ni el catálogo. Retirar la versión vigente hace que la anterior pase a ser la efectiva (la política sigue al estado publicado).
- Una concesión ya guardada cuyo par deja de ofrecerse **queda almacenada e inerte y se puede revocar** (revocar no exige que el par siga ofrecido).
- Diferencia deliberada: `production_access` filtra además por `area = 'production'` y por la lista central; el servicio de concesiones es agnóstico al área y a esa lista (no importa módulos de capturas ni de sectores). Para todos los
  formularios del bundle las versiones de un mismo formulario comparten área, así que no hay diferencia observable.

## 3. Control 2 · Integridad histórica (migración 0008)
Auditoría de `user_machine_form_grant` y de sus triggers de 0007 (`a_guard`, `immutable_truncate`, `z_touch`, `audit_changes`). `touch_row` ya restauraba `created_at`/`created_by` en un UPDATE; pero:

| # | Hueco en 0007 (reproducido) | Corrección en 0008 |
|---|---|---|
| 1 | Una fila **revocada** aún aceptaba UPDATEs: `updated_at` / `updated_by` cambiaban después de la revocación. | Una fila revocada queda **congelada**: ningún UPDATE, de ninguna columna. |
| 2 | La revocación tomaba `revoked_at` del llamador (+10 años, o pasado) y `revoked_by` de cualquier usuario. | `revoked_at` = reloj del servidor; con actor en sesión, `revoked_by` **debe** ser ese actor. |
| 3 | Una fila **activa** aceptaba UPDATEs que no revocaban (p. ej. falsificar `updated_by`). | Lo único que puede cambiar una fila activa es revocarse; `updated_by` pasa a ser quien revoca. |
| 4 | Una fila podía **nacer revocada** (solo lo frenaba un accidente de tiempos del CHECK) y `created_by`/`updated_by` se podían falsificar sin actor en sesión. | Una concesión nace activa; `created_by`/`updated_by` solo pueden ser el actor de la sesión (o NULL). |

La 0008 solo hace `CREATE OR REPLACE FUNCTION vinto_audit.guard_user_machine_form_grant()` y `CREATE TRIGGER a_guard_insert`. **No cambia tablas, columnas, restricciones, índices, privilegios ni filas**: lo que ya esté
guardado queda idéntico (una prueba lo verifica sobre una base en 0007 con filas activas y revocadas). Se mantienen `DELETE`/`TRUNCATE` rechazados, identidad inmutable, concesión, revocación, idempotencia, concurrencia y auditoría.

SQL directo sin actor en sesión sigue funcionando (scripts de administración), pero ya no puede atribuir una fila a otra persona: los sellos quedan en NULL.

## 4. Evidencia de la reproducción previa (base aislada, antes de corregir)
Sondas sobre 0007: concesión de P1-05 en MP1 con la v1 como único vínculo → aceptada; con formulario inactivo → aceptada; con máquina inactiva → aceptada; `INSERT` con `created_by` ajeno → aceptado; revocación con
`revoked_at` +10 años y `revoked_by` distinto del actor → aceptada; `UPDATE` de `updated_by` en fila revocada → aceptado; `UPDATE` de una fila activa sin revocar → aceptado.

## 5. Análisis de impacto
| Tema | Impacto |
|---|---|
| Endpoints y capturas | **Ninguno**: nada de `app/` consume el módulo (lo comprueba una prueba). La autorización real sigue siendo sector + perfil. |
| Datos existentes | Ninguno: 0008 no toca filas. La tabla se espera vacía (ningún código escribe en ella; 0007 no insertó nada); **no se verificó contra ninguna base real**. |
| Compatibilidad código/BD | Cualquier orden: el servicio nuevo funciona sobre una base en 0007 (solo lee el catálogo) y el servicio anterior funciona sobre una base en 0008 (ya enviaba `revoked_by` = actor y `revoked_at` = `clock_timestamp()`). |
| Privilegios | Sin cambios (`vinto_app`: SELECT, INSERT, UPDATE; nunca DELETE). |
| Cliente directo con `UPDATE` ad hoc | Ahora se rechaza (23514) todo lo que no sea revocar. Es el objetivo; ningún código de la aplicación lo hacía. |
| Rendimiento | Una consulta de catálogo más por concesión (administrativa, baja frecuencia) y un trigger de INSERT. |

## 6. Despliegue y reversión (futuro, solo con autorización expresa)
1. Preflight (`migrate.py --check`: debe indicar solo la 0008 pendiente), respaldo verificado. 2. `migrate.py`. 3. Verificar `--check` en verde y que `user_machine_form_grant` conserva su número de filas. 4. Desplegar el servicio.
Reversión: no se reescribe ninguna migración. Antes de usarse, restaurar el respaldo; después, una migración nueva que restituya el cuerpo anterior de la función (no recomendado: reabre los huecos del §3).

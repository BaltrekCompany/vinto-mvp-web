# MF-13-01B.2 · VINTO-P1-10 «Registro de fardos» en las cinco rebobinadoras

## 1. Decisión y alcance
**Decisión funcional confirmada:** `VINTO-P1-10` está disponible para **Beloit, Over, Copasa, Perichun y Tubetera**. Resuelve la pregunta abierta H1-03 / decisión #4 de M2-B2 («solo COPASA» o «todas»), que
`docs/M5-B0-decisiones-VINTO.md` y `docs/M4-B1-homologacion-rebobinado.md` dejaban pendiente.

Cambio **aditivo**: versión 3 con **los mismos campos y reglas** que la 2; solo cambia el vínculo con las máquinas. Sin numeración automática, sin cambios de peso, sin firmas, sin campos nuevos, sin migraciones,
sin cambios de permisos, perfiles, concesiones ni Calidad.

## 2. Archivos y versiones
| Archivo | Cambio |
|---|---|
| `backend/seed_data/forms/VINTO-P1-10.json` | `version_number` 2 → **3**; `machines` `["COPASA"]` → `["BELOIT","OVER","COPASA","PERICHUN","TUBETERA"]`; `definition_checksum` recalculado (`e35676ab…` → `8649ed42…`). Campos y grupos idénticos. |
| `backend/seed_data/manifest.json` | `sha256` y `bytes` de ese archivo; `sha256` de procedencia de `lib/vinto/p1-10.ts`. Nada más. |
| `lib/vinto/p1-10.ts` | La nota de la máquina deja de decir «Por confirmar: qué máquinas pueden usar P1-10». Sin cambios de lógica. |
| `backend/tests/mf13_p110_v2.json` | Copia exacta de la v2 publicada en producción (para simular el estado previo). |
| Pruebas | Nuevas: `backend/tests/test_mf13_p110_rebobinado_machines.py` (18) y `scripts/mf13-p110-machines.test.mjs` (8). Adaptadas (fijaban «P1-10 v2 / solo COPASA»): `test_mf07`, `test_mf08`, `test_mf09`, `test_mf10`, `test_mf11`, `test_mf12a`, `test_import_reference` (1946 → 1950 registros), `test_bundle_validation` (huella del bundle) y `scripts/mf10-rebobinado-conversion.test.mjs`. |

No cambian `backend/app/**`, el frontend funcional, la migración 0007, perfiles, concesiones, Calidad ni TVC/ETL. `VINTO-P1-10` ya estaba en `CENTRAL_FORM_CODES` y la pantalla `p110` ya se enruta por
(sector, formulario), no por máquina: la disponibilidad nueva sale del backend (`GET /api/production/machines`).

**Por qué una versión nueva.** El importador es solo aditivo: una versión publicada es inmutable y cambiarle las máquinas manteniendo el número es un **conflicto** (lo demuestra
`test_widening_the_machines_of_v2_in_place_would_be_a_conflict_which_is_why_the_version_is_new`).

## 3. Matriz antes / después de P1-10
| Máquina | Antes (v2) | Después (v3) | Otros formularios de la máquina |
|---|---|---|---|
| BELOIT | no | **sí** | P1-07 (sin cambios) |
| OVER | no | **sí** | P1-07 (sin cambios) |
| COPASA | sí | sí | P1-07 (sin cambios) |
| PERICHUN | no | **sí** | P1-30 (sin cambios) |
| TUBETERA | no | **sí** | P1-29 (sin cambios) |
| Las otras 13 (MP1, MP3 y Conversión) | no | no | sin cambios |

Versiones: la **v2 sigue publicada y vinculada solo a COPASA** (sus capturas siguen ligadas a ella). Las capturas nuevas de las cinco máquinas usan la **v3**. Total de campos del bundle: 464 (sin cambio);
registros de importación en una base vacía: 1950 (+4 vínculos de máquina).

## 4. Qué se verificó (PostgreSQL 17 aislado)
- **Disponibilidad:** P1-10 v3 ofrecida a las cinco rebobinadoras, cada una con sus otros formularios; ninguna otra máquina; una sesión sin concesión de REBOBINADO no ve ninguna.
- **Captura** mediante asignaciones válidas de cada máquina (OT publicada + activación): 201, versión 3, máquina y artículo correctos, valores tal como se digitan.
- **Rechazo** en máquinas no vinculadas (MP1, GAMBINI): 409 `FORM_NOT_AVAILABLE`, sin filas. Campos obligatorios, claves inexistentes (`numero_de_fardo`, `firma`…): 422.
- **Histórico:** una captura v2 de COPASA se lee, se lista y su reintento idempotente se acepta; el historial muestra v2 y v3; las capturas existentes no se reescriben.
- **Idempotencia y autorización existentes:** reintento 200 sin duplicar; reuso del id con otro contenido 409; anónimo 401; Jefatura, Supervisión y Calidad 403; operador sin sector REBOBINADO 404.
- **Importación:** dry-run sobre el estado previo (v2 solo COPASA): 0 conflictos, 1 versión, 4 campos, 5 vínculos; la v2, sus campos y vínculos quedan idénticos; los demás formularios no se tocan; segunda importación
  idempotente.

## 5. Riesgos y pendientes
| Riesgo / pendiente | Tratamiento |
|---|---|
| Un operador de COPASA ve P1-10 v3 en vez de v2 (mismos campos). | Sin cambio de contrato: el payload de la v2 es válido en la v3; las capturas antiguas conservan la v2. |
| Orden frontend/backend. | Sin dependencia: el frontend actual ya es agnóstico a la versión y a la máquina; ofrece P1-10 solo donde el backend lo publica. |
| Retirar P1-10 de una máquina más adelante. | Reversible retirando la v3 y publicando otra versión; requiere autorización expresa. |
| Reglas de P1-10 aún sin confirmar (numeración, peso, responsable, firma). | Siguen fuera de alcance; no se inventó ninguna. |
| La autorización por usuario–máquina–formulario (MF-13-01B.1, tabla `user_machine_form_grant`) **no** se aplica todavía. | Hasta entonces el alcance es el de sector + perfil, como hoy. |
| La suite completa del backend ya falla en este entorno sobre `main` (reloj/turno). | Ver el PR: comparación de fallos contra `main`, sin declarar PASS general. |

## 6. Importación controlada y despliegue (futuro, solo con autorización expresa)
1. **Preflight:** versión activa, servicios, sin despliegues concurrentes, sin borradores abiertos de P1-10; confirmar que `vinto_piloto` (o la base destino) está en la 0007 (`migrate.py --check`).
2. **Respaldo** verificado (`backup.sh create-and-verify`) con restauración de prueba.
3. **Dry-run** contra la base destino: `python import_reference.py --target dev` (no escribe). Debe informar **0 conflictos**, `form_version` +1, `field` +4, `form_version_machine` +5 y nada más.
4. **Aplicar** con `--apply` solo si el dry-run coincide exactamente.
5. **Verificar:** `GET /api/production/machines` con un operador de Rebobinado muestra P1-10 v3 en las cinco máquinas; una captura de prueba por máquina en una base de QA; las capturas v2 de COPASA siguen legibles.
6. **Reversión:** la importación es aditiva; antes de usarse en producción se revierte restaurando el respaldo. Una vez con capturas v3 no se borra: se publica una versión posterior.

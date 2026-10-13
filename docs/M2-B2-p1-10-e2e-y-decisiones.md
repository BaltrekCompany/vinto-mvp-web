# M2-B2 · VINTO-P1-10 central de extremo a extremo (entorno aislado) y matriz de decisiones

**Estado: técnicamente funcional SOLO en un entorno de prueba aislado. NO homologado ni operativo para VINTO.** P1-10 no está en `CENTRAL_FORM_CODES`, Rebobinado no es un sector operativo, `backend/seed_data` no contiene P1-10 y DEV no se tocó. Las reglas industriales no confirmadas no se decidieron: las pruebas y la interfaz las dejan visibles como pendientes.

## Qué se construyó
| Pieza | Dónde | Notas |
|---|---|---|
| Motor | `backend/app/capture_service.py` (M2-A) | **Sin cambios.** P1-10 entra por la política `CENTRAL_FORM_CODES` (parcheada solo en pruebas) |
| Fixtures de prueba | `backend/tests/m2b2_fixtures.py` | Sector REBOBINADO, máquina COPASA y turnos **ficticios**; definición candidata de P1-10 con solo los 4 campos manuales como texto/textarea |
| Pruebas backend | `backend/tests/test_m2b2_p110_central.py` | 16 pruebas en base efímera |
| Servidor E2E aislado | `backend/tests/e2e_p110_server.py` | Base `*_test` nueva, usuarios de prueba, configuración habilitada solo en ese proceso; se niega a arrancar contra DEV |
| Contrato del cliente | `lib/vinto/p1-10.ts`, `lib/vinto/p1-10-api.ts` | Parser estricto con `expectedFormCode = VINTO-P1-10`, validación estructural, intento inmutable, reconciliación |
| Cliente HTTP genérico | `lib/vinto/captures-api.ts` | `postCaptureOf` / `getCaptureOf` / `listCapturesOf` (parser por formulario); F6 conserva su API pública. **Se corrigió** que el listado F6 aceptara `formCode` con el parser F6 |
| Componente | `components/vinto/p1-10-capture.tsx` | Reutiliza el kit y el núcleo de M2-B1. `P110Preview` sigue siendo la vista informativa separada |
| Recorrido E2E | `scripts/e2e/p110-e2e.mjs` + `scripts/e2e/harness-page.tsx.txt` | El harness es una página **temporal** (no es ruta del producto) que se copia a `app/qa-harness/` solo en un worktree de QA |

## Cómo reproducir el E2E (solo en un worktree de QA)
1. Backend aislado (contenedor desechable con el worktree montado y `CORS_ORIGINS` = origen del frontend de QA): `python tests/e2e_p110_server.py` (puerto ≠ 8000, origen ≠ 8787; escribe credenciales de prueba EFÍMERAS en `E2E_OUT`).
2. Copiar `scripts/e2e/harness-page.tsx.txt` a `app/qa-harness/page.tsx`, construir con `NEXT_PUBLIC_API_URL=http://127.0.0.1:8190` y servir en otro puerto (8796).
3. `node scripts/e2e/p110-e2e.mjs <creds.json> <carpeta-de-evidencias>`.
4. Eliminar el harness y detener el contenedor (que borra las bases efímeras).
El script aborta si la API/frontend son los de DEV, si la base no termina en `_test`, si el backend no sirve esa base o si el navegador llama al puerto 8000; solo lee DEV con `SELECT` para comprobar que no cambió.

## Matriz de decisiones para VINTO
Bloqueo = impide operar P1-10 con datos reales. Presentación/validación = no impide el registro técnico, pero cambia cómo se captura o se valida.

| # | Decisión pendiente | Qué se necesita de VINTO | ¿Bloquea la operación? | ¿Afecta presentación / validación? | Comportamiento hoy (aislado) |
|---|---|---|---|---|---|
| 1 | **Numeración y formato del fardo** | ¿Manual o correlativo central? Alcance (máquina/día/turno), formato, reinicio, huecos, correcciones | **Sí** si el correlativo es central (requiere numerador y migración); no si es manual | Formato y unicidad cambian la validación | Texto libre, sin formato ni unicidad; no se genera número |
| 2 | **Tipo y características del peso** | Tipo definitivo, decimales, unidad, rango, bruto/neto, tolerancias | No, mientras se acepte texto | **Sí** (validación, ordenación, agregados) | Texto tal cual (sin conversión, coma/punto intactos); un número JSON se rechaza (422) |
| 3 | **Relación producto ↔ línea de OT** | ¿Debe coincidir con el artículo de la línea, salir de catálogo o ser libre? | No | **Sí** (validación y selector) | Texto libre; el artículo de la línea se muestra como contexto |
| 4 | **Máquinas permitidas** | «Todas las rebobinadoras» frente a COPASA (el catálogo candidato conoce BELOIT, OVER, COPASA, PERICHUN, TUBETERA) | **Sí** (define `form_version_machine` y quién puede capturar) | No | Solo COPASA en el fixture; sin máquina vinculada = 409 `FORM_NOT_AVAILABLE` |
| 5 | **Responsable y firma/aprobación** | ¿Quién es el responsable? ¿Qué es una firma válida, quién aprueba y se puede corregir? | **Sí** si la ficha exige aprobación para considerarse válida; no para un registro técnico | **Sí** | Pendiente: no se capturan ni se simulan; se muestra el usuario autenticado solo como identificación, no como responsable ni firma |
| 6 | **Fecha operativa frente a fecha calendario** | Cuál es la fecha de la ficha | No | **Sí** (presentación y reportes) | Se usa la fecha operativa de la asignación como contexto informativo |
| 7 | **Turnos y datos maestros de Rebobinado** | Horarios reales y vigencias, máquinas, artículos-máquina aprobados; habilitar el sector | **Sí** (sin turno resoluble no hay asignación ni captura) | No | Turnos FICTICIOS de prueba; el sector solo es operativo dentro del servidor E2E |

**Bloquean la operación hoy:** 7 (datos maestros y turnos), 4 (máquinas) y, según el alcance de la ficha, 1 (si el correlativo es central) y 5 (si exige aprobación). **Solo afectan presentación o validación:** 2, 3 y 6 (y el formato de 1 si el número es manual).
Además, la habilitación técnica (añadir `VINTO-P1-10` a la política y habilitar `REBOBINADO` en `app/sectors.py`) es un cambio de código revisado y aparte, posterior a las decisiones anteriores.

## Qué NO se hizo (a propósito)
Correlativo definitivo, firma digital, genealogía, inventario, activar Rebobinado en DEV, rutas públicas de QA, el hotfix de `/admin`, despliegue.

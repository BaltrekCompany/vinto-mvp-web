# QA-3F-01 — Integración E2E de los tres frentes (Bobinas, Rebobinado, Conversión) y Calidad

## 1. Qué es esto y qué NO es

Esta es una prueba de **integración técnica**: demuestra que los tres frentes (Bobinas, Rebobinado, Conversión) y Calidad pueden operar
**simultáneamente, en la misma instancia de FastAPI/React y en la misma base de datos PostgreSQL 17**, sin interferirse entre sí.

NO es:
- una homologación industrial de Rebobinado ni de Conversión (sus contratos — P1-10, P1-16 — siguen siendo **candidatos**, sin aprobar por VINTO);
- una certificación de preparación para producción;
- una regresión exhaustiva de cada frente por separado (esas ya existen: `scripts/e2e/b0-e2e.mjs` para Bobinas/Calidad, `scripts/e2e/m4a-e2e.mjs`
  para Rebobinado, `scripts/e2e/m6a-e2e.mjs` para Conversión; esta prueba las reutiliza en un recorrido representativo, no las repite).
- una autorización para desplegar ni para habilitar los tres sectores en la configuración real.

La habilitación de los tres sectores es **exclusiva de un proceso de prueba efímero**. `backend/app/sectors.py` (`DEFAULT_OPERATIONAL_SECTORS =
(SECTOR_BOBINAS,)`) y `backend/app/capture_service.py` (`CENTRAL_FORM_CODES = frozenset({FORM_CODE})`) **no se modificaron**.

## 2. Identidad de la corrida probada

| | |
|---|---|
| SHA probado | `f4ba7d4ec097f505c95650585600491a788de9c9` (`main`, PR #50 — INT-02B) |
| Árbol de trabajo | con cambios (los archivos nuevos de este incremento, sin comprometer todavía) |
| Identificador de corrida (ejemplo reportado) | `20261015T144250Z-c157d03f` |
| PostgreSQL | 17.11 (Debian), contenedor exclusivo `vinto-qa3f01-pg`, puerto `127.0.0.1:55440`, datos en tmpfs (sin volumen) |
| Bases efímeras | `vinto_qa3f01_7d0b2f0088a1_test` (fase habilitada) y `vinto_qa3f01_01923f90206f_test` (fase cerrada) — nunca `vinto` ni `vinto_test` |
| Backend | `backend/tests/e2e_qa3f01_server.py`, puerto `127.0.0.1:8192` |
| Frontend | build real (sin ruta de QA), `127.0.0.1:8799` |
| Navegador | Chrome 155 (headless, CDP), un puerto de depuración y un perfil temporal por sesión |
| Node | v24.20.0 — Python 3.12.10 |

Cada corrida completa (`node scripts/e2e/qa3f01-run.mjs <directorio-evidencias>`) genera su propio subdirectorio `<runId>/` con capturas de
pantalla, `entorno-qa3f01-<fase>.json`, `resultados-qa3f01-<fase>.json` y `corrida.json` (veredicto final + verificación de limpieza).

## 3. Políticas de prueba (solo en el proceso efímero)

`backend/tests/e2e_qa3f01_server.py` verifica, **antes de decidir si parchea algo**, que la configuración real es exactamente
`sectors._OPERATIONAL == ("BOBINAS",)` y `capture_service.CENTRAL_FORM_CODES == frozenset({"VINTO-P1-06"})`; si no lo es, se niega a arrancar
(`refuse(...)`, código de salida 2). Solo entonces:

- **Fase A — habilitada** (`E2E_3F=on`, por defecto): `sectors._OPERATIONAL = (BOBINAS, REBOBINADO, CONVERSION)` y
  `capture_service.CENTRAL_FORM_CODES = {VINTO-P1-06, VINTO-P1-10, VINTO-P1-16}`, **solo en la memoria de ese proceso Python**.
- **Fase B — política cerrada** (`E2E_3F=off`): no se aplica ningún parche; se sirve la configuración real tal cual.

Calidad (P1-19/P1-20, y la política INT-01A que filtra los formularios candidatos por bobina) **no depende de `sectors._OPERATIONAL` ni de
`CENTRAL_FORM_CODES`**: su propia política (`backend/app/quality/capture_service.py`) no se tocó en ningún momento de esta prueba.

Los sectores/máquinas de Rebobinado (COPASA) y Conversión (GAMBINI/WALLY) y los contratos candidatos P1-10/P1-16 se instalan reutilizando,
**sin modificarlos**, los fixtures ya existentes `backend/tests/m2b2_fixtures.py` (M2-B2/M4-A) y `backend/tests/m6a_fixtures.py` (M6-A).

## 4. Formularios y recorridos probados

| Frente | Formulario | Rol que lo captura | Resultado |
|---|---|---|---|
| Bobinas | F3 (`VINTO-P1-03`, registro de producción de bobinas) | Operación | 1 bobina creada en MP1, Calidad queda `pending` |
| Bobinas | P1-06 (`VINTO-P1-06`, control de fardos) | Operación | 1 captura `submitted` en MP1 |
| Calidad | P1-19 (`VINTO-P1-19`, control de humedad) | Calidad | 1 captura `submitted`, área `quality`; `quality_release` sigue `pending` |
| Rebobinado | P1-10 (`VINTO-P1-10`, candidato) | Operación | 1 captura `submitted` en COPASA |
| Conversión | P1-16 (`VINTO-P1-16`, candidato) | Operación | 1 captura `submitted` en GAMBINI, 3 detalles tipados |

No se probaron P1-29, P1-11/P1-12/P1-13 ni los demás candidatos (regresión ya cubierta por `m4a-e2e.mjs`/`m6a-e2e.mjs`/`m6b/m6c/m6d-e2e.mjs`), ni
P1-20 (ya cubierto por `b0-e2e.mjs`), conforme al alcance mínimo pedido.

## 5. Recorridos por rol (fase habilitada)

1. **Jefatura**: crea y publica, en la MISMA sesión de navegador/base, la OT de MP1 (Bobinas), la de COPASA (Rebobinado) y la de GAMBINI
   (Conversión); confirma que Bobinas · Programación sigue sin mostrar las máquinas de los otros dos frentes.
2. **Supervisión**: activa las tres asignaciones (una por frente); cada una resuelve máquina, turno y fecha operativa por backend.
3. **Operación**: captura F3 + P1-06 en MP1, P1-10 en COPASA y P1-16 en GAMBINI, **todo en el mismo navegador/sesión de API**, por la
   navegación normal (sin ruta de QA ni formulario sintético).
4. **Calidad**: ve la bobina de MP1 pendiente en la bandeja central, registra P1-19 y consulta el historial (`Ver controles`), reutilizando el
   visor de INT-02B.
5. **Integración transversal** (sección D del guion): las tres OT coexisten (cada una `in_progress` tras activar su asignación); el backend
   publica cada sector con SUS formularios exclusivamente (P1-10 nunca en Conversión, P1-16 nunca en Rebobinado); las tres asignaciones activas
   quedan cada una asociada a SU máquina; el conteo de capturas por formulario es exactamente 1 por cada uno de los cinco (F3/P1-06/P1-10/P1-16/P1-19,
   sin cruces ni duplicados); un reintento idéntico de P1-16 por la API es `200 already_submitted` sin crear otra fila; `quality_release` sigue
   `pending` sin decisión; y un usuario con concesión **solo de BOBINAS** no ve Rebobinado ni Conversión operativos aunque el backend los tenga
   habilitados en esta prueba (la concesión por sector sigue siendo la autoridad, no el backend por sí solo).
6. **Fase cerrada** (servidor idéntico, sin ningún parche): `GET /api/production/machines` solo publica BOBINAS; capturar P1-10/P1-16 por la
   API es `422 UNSUPPORTED_FORM`; consultar la asignación activa de COPASA/GAMBINI es `422` (sin alcance); la navegación muestra Rebobinado y
   Conversión «no está habilitado» para Jefatura y Operación, sin formularios ni OT candidata, sin ningún POST de escritura y sin ningún
   respaldo local; Bobinas sigue operando con su programación central (MP1/MP3); no se escribió ninguna OT ni captura de los otros dos frentes.

## 6. Verificaciones HTTP y SQL (resumen)

- **HTTP**: `GET /api/production/machines` (disponibilidad real por sector/máquina/formulario), `GET /api/work-orders`,
  `GET /api/assignments/active`, reintento idéntico de captura (idempotencia), rechazos `422 UNSUPPORTED_FORM` en la fase cerrada.
- **SQL** (solo lectura, `BEGIN READ ONLY`, dentro del contenedor exclusivo): `current_database()` antes de la primera escritura; conteo de
  capturas por `form.code` (sin cruces); estado de `quality_release` (sin decisión, nunca tocado); asignaciones activas por máquina; sesiones
  revocadas tras cada logout.
- Ambas fases terminaron con **0 sesiones activas** tras los logouts (`vinto_auth.session`).

## 7. Resultados ejecutados

| Suite | Resultado |
|---|---|
| Node completo (`node --test scripts/*.test.mjs`) | **709/709 OK** (sin cambios en `lib/`/`components/`; se ejecutó como regresión) |
| TypeScript (`tsc --noEmit`) | **sin errores** |
| Lint (`eslint .`) | **0 errores**, 3 advertencias preexistentes sin relación con este incremento |
| Build (`npm run build`) | **OK** |
| Backend focalizado (OT, asignaciones, sectores, captura, Calidad, Conversión candidata) — PostgreSQL 17 efímero `vinto_test` vía `docker compose` | **242/242 OK** (`test_work_orders_api/service`, `test_assignments_api/service`, `test_sector_authorization`, `test_sector_scope`, `test_capture_api`, `test_quality_capture_api`, `test_m6a_conversion_p116`) |
| **QA-3F-01 (este incremento)** — PostgreSQL 17 exclusivo y efímero, contenedor propio | **Fase habilitada: 59/59 · Fase cerrada: 16/16 · Total 75/75** |
| Regresión E2E-B0 (Bobinas + Calidad, política REAL) — PostgreSQL 17 exclusivo y efímero, contenedor propio | **114/114 OK** |

Ningún backend focalizado ni E2E-B0 mostró regresiones: los tres frentes conviviendo en un mismo proceso de prueba no alteran el comportamiento
de Bobinas/Calidad con la política real.

## 8. Aislamiento entre frentes (verificado)

- El backend publica cada sector **solo** con sus propios formularios (`D1`): nunca aparece P1-10 en Conversión ni P1-16 en Rebobinado.
- Las OT y asignaciones de cada frente quedan asociadas **exclusivamente** a su máquina (`D2`, `D3`); no se mezclan líneas base, turnos ni
  fechas operativas entre sectores.
- Los conteos de capturas por formulario son exactos (`D4`): ninguna captura de un frente aparece bajo el formulario de otro.
- La concesión de sector del usuario sigue siendo la autoridad de disponibilidad (`D7`/`D8`), independiente de que el backend tenga los
  sectores operativos en esta prueba: un usuario sin la concesión de Rebobinado/Conversión no los ve, aunque otro usuario sí pueda operarlos.
- `localStorage` nunca recibe OT, asignaciones ni capturas centrales de ninguno de los tres frentes (`A15`, `B13`, `C12`, `E6`); no hay
  respaldo local ni demo en ningún caso.
- `quality_release` permanece `pending`, sin `decided_by` ni `decided_at`, durante y después de las capturas de los tres frentes (`A11`, `A21`,
  `D5`).

## 9. Configuración real: verificada intacta

- Antes de cualquier parche, el servidor de prueba comprueba `sectors._OPERATIONAL == ("BOBINAS",)` y
  `capture_service.CENTRAL_FORM_CODES == frozenset({"VINTO-P1-06"})`; si no lo son, se niega a arrancar.
- La fase cerrada (`E2E_3F=off`) ejecuta exactamente esa configuración real, sin ningún parche, y confirma que Rebobinado/Conversión quedan
  rechazados (422) y sin navegación operativa.
- `backend/app/sectors.py`, `backend/app/capture_service.py`, `backend/app/quality/capture_service.py` (`ENABLED_BOBBIN_CANDIDATE_FORM_CODES`),
  `backend/seed_data` y los catálogos/roles/permisos productivos **no se modificaron** en este incremento.

## 10. Fallos y limitaciones

- No se repitió la regresión exhaustiva de cada frente por separado (fault injection de red, reintentos con petición/respuesta perdida, móvil,
  matriz completa de permisos): esa cobertura ya existe en `b0-e2e.mjs` / `m4a-e2e.mjs` / `m6a-e2e.mjs` / `m6b/m6c/m6d-e2e.mjs` y no se duplicó.
- No se probó P1-29 (Rebobinado) ni P1-11/P1-12/P1-13 (Conversión): fuera del alcance mínimo pedido para esta integración.
- La corrida reportada se ejecutó con el árbol de trabajo "sucio" (los archivos nuevos de este mismo incremento, `backend/tests/e2e_qa3f01_server.py`,
  `scripts/e2e/qa3f01-run.mjs`, `scripts/e2e/qa3f01-e2e.mjs`, sin comprometer todavía en el momento de la corrida): es inherente a validar un
  arnés de prueba nuevo antes de su propio commit; el SHA reportado es el de `main` sobre el que se construyó (`f4ba7d4`).
- Ningún fallo quedó sin resolver: las tres iteraciones de ajuste (estado `in_progress` tras activar la asignación, código interno `VINTO-P1-03`
  de F3, y el selector de Programación que Operación no ve por no tener `canManageOrders`) corrigieron el GUION de prueba, nunca un contrato ni
  una regla industrial.

## 11. Pendientes de VINTO para habilitar realmente los tres frentes

- Homologación industrial de Rebobinado (P1-10, P1-29 y los demás candidatos) y de Conversión (P1-16, P1-11/P1-12/P1-13): catálogo de
  máquinas real, turnos vigentes, relaciones artículo-máquina, y los contratos de campos/cálculos pendientes ya documentados en cada
  definición candidata (`lib/vinto/p1-10.ts`, `p1-16.ts`, etc.).
- Decisión de VINTO sobre `ENABLED_BOBBIN_CANDIDATE_FORM_CODES` para los candidatos de Calidad por bobina (P1-21/P1-24/P1-25/P1-28), que esta
  prueba no tocó.
- Cambio de código revisado en `backend/app/sectors.py` (`DEFAULT_OPERATIONAL_SECTORS`) y en `backend/app/capture_service.py`
  (`CENTRAL_FORM_CODES`) para habilitar REBOBINADO/CONVERSION y sus formularios en la configuración real — nunca una variable de entorno ni un
  interruptor en tiempo de ejecución.
- Q-LIB / liberación oficial de Calidad sigue sin existir; no se toca en este incremento.
- Sin despliegue cloud: esta prueba demuestra el circuito técnico local, no autoriza ni valida ningún entorno de nube.

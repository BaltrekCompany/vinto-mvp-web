# M6-A — Primer circuito central CANDIDATO de Conversión (VINTO-P1-16)

Estado: **candidato técnico, NO homologado, NO habilitado.** Conversión sigue sin ser un sector operativo y VINTO-P1-16 sigue fuera de la política de captura central. Todo lo que sigue funciona únicamente en una base efímera `*_test` y en un proceso de prueba que lo habilita explícitamente.

Base: `origin/main` `575ee05` (PR #29). La homologación de Conversión es **independiente** del paquete M5-B0 (que solo cubre Bobinas y Rebobinado).

## 1. Qué se entrega

| Pieza | Archivos |
|---|---|
| Shell central común por sector (Rebobinado ya no está atado a su sector) | `components/vinto/sector-central.tsx` (antes `rebobinado-central.tsx`); `rebobinado-central.tsx` y `conversion-central.tsx` son envolturas de una línea con `code="REBOBINADO"` / `code="CONVERSION"` |
| Disponibilidad por sector verificada por el backend | `lib/vinto/availability.ts`: `sectorView`, `conversionView`, `CONVERSION_*`; `FORM_SCREENS` añade `VINTO-P1-16 → p116` |
| Cliente y pantalla de P1-16 (kit React existente) | `lib/vinto/p1-16.ts`, `p1-16-api.ts`, `components/vinto/p1-16-capture.tsx`, `P116History` en `central-form-history.tsx` |
| Home | `app/page.tsx`: `front === "Conversión"` usa `ConversionCentral`; estados `convCapture` / `p116Attempt` / `p116Context`, limpiados al perder la sesión y al cerrarla |
| Fixtures de prueba (solo `*_test`) | `backend/tests/m6a_fixtures.py` |
| Pruebas backend | `backend/tests/test_m6a_conversion_p116.py` (24) |
| Pruebas Node | `scripts/p1-16-capture.test.mjs` (15) y 4 en `scripts/availability.test.mjs` |
| Servidor y recorrido E2E | `backend/tests/e2e_m6a_server.py`, `scripts/e2e/m6a-e2e.mjs` |

**No cambia el motor.** `capture_service`, `work_orders`, `assignments`, `shifts` y `production_access` no se modificaron: P1-16 usa tres campos manuales, un tipo `text` con opciones y un `decimal`, que el motor ya soportaba. No hay migraciones.

**No se tocó:** `backend/seed_data`, `backend/app/sectors.py` (`DEFAULT_OPERATIONAL_SECTORS = (BOBINAS,)`), `CENTRAL_FORM_CODES = {VINTO-P1-06}`, concesiones o permisos reales, DEV, producción ni el checkout local. Una prueba (`availability.test.mjs`) vigila esas tres configuraciones y que `forms/VINTO-P1-16.json` no exista en el bundle oficial.

## 2. Inventario de Conversión (hechos del repositorio)

**Máquinas** (`GROUPS` en `app/page.tsx`): Gambini, Sincro II, Sincro III, OMET I, OMET II, 8.2, 8.5, 8002, Serv 4, Wally, Pañuelera. El exportador las declara como sector candidato (`CONVERSION_SECTOR`, códigos técnicos `GAMBINI`, `SINCRO_II`, `8_2`, `PANUELERA`…). `backend/seed_data` solo contiene MP1 y MP3.

**Formularios legacy** (`lib/vinto/form-definitions.ts`), con los conteos de campos **corregidos** (verificados contra la definición):

| Formulario | Máquinas permitidas | Total | Automáticos | Manuales | Calculados |
|---|---|---:|---:|---:|---:|
| P1-11 Consumo de bobinas | Gambini, Sincro II, Sincro III | 61 | 5 | 34 | 22 |
| P1-12 Producción diaria de papel higiénico | Gambini, Sincro II, Sincro III | 37 | 9 | 20 | 8 |
| P1-13 Producción diaria de servilletas y especiales | OMET I/II, 8.2, 8.5, 8002, Serv 4, Wally, Pañuelera | 31 | 8 | 18 | 5 |
| P1-16 Registro de control de merma | `todas` | 14 | 5 | 8 | 1 |
| **Total** | | **143** | **27** | **80** | **36** |

> Corrección: el diagnóstico previo de esta sesión informó 39 automáticos y 41 calculados (suma incorrecta por un filtro de formularios demasiado amplio). Los valores de la tabla son los correctos; el total de 143 no cambia.

**Datos de apoyo** (catálogos legacy, sin homologar): 98 relaciones artículo-máquina y 74 artículos únicos, sin solape con Bobinas ni Rebobinado; unidades `Pack` y `UN`; turnos del legacy Mañana 06–14, Tarde 14–22 y Noche 22–06; pesos nominales de los 74 artículos; 59 de ellos con receta.

## 3. P1-16: definición legacy frente a la pantalla actual

| | Definición (`form-definitions.ts`) | Pantalla actual (`WasteCapture`, `app/page.tsx`) |
|---|---|---|
| Unidad de registro | Una ficha por turno con una columna de kg por tipo de merma | **Una pesada** por envío |
| Campos manuales | `numero_correlativo`, `hoja_doble_kg`, `servilleta_kg`, `toalla_kg`, `carton_kg`, `hoja_simple_kg`, `plastico_kg`, `observacion` | `tipo_merma`, `origen_merma`, `peso_merma_kg` |
| Calculado | `total_merma_kg` | ninguno |
| Automáticos | fecha, turno, grupo, operador, máquina | los resuelve la asignación |
| Origen de la merma (Logs / Cola / Máquina) | no existe | existe |
| Observación y correlativo | existen | no existen |

Las dos descripciones son incompatibles. **VINTO debe decir cuál es la ficha real** (decisión C-1 abajo).

## 4. Hipótesis de la captura candidata

Se implementa exclusivamente la interpretación de la pantalla actual, y **solo como fixture de prueba**:

- `tipo_merma`: elección entre Hoja doble, Hoja simple, Servilleta, Toalla, Cartón y Plástico (claves `hoja_doble`, `hoja_simple`, `servilleta`, `toalla`, `carton`, `plastico`). Tipo `text` con opciones en el motor.
- `origen_merma`: Logs, Cola o Máquina (`logs`, `cola`, `maquina`). Tipo `text` con opciones.
- `peso_merma_kg`: decimal. El cliente acepta coma o punto y envía punto. **No** valida unidad, rango ni decimales.

El backend deriva de la asignación y de la sesión máquina, turno, fecha operativa, OT, línea, artículo y usuario (campos ya soportados). **No se inventan** correlativos, firmas, grupos ni totales; la propia pantalla muestra esos puntos como pendientes y el payload solo lleva `capture_id`, `form_code`, `assignment_id`, `device_key` y los tres valores. La definición candidata se instala únicamente en bases efímeras; nunca entra en el bundle oficial.

**Turnos de hipótesis:** Mañana 06:00–14:00, Tarde 14:00–22:00, Noche 22:00–06:00, con la fecha operativa del turno nocturno igual al día en que empieza (la misma regla que Bobinas). Son los horarios que usa el frontend legacy; no están confirmados.

## 5. Cómo se comporta

- **Navegación:** Home enruta el frente Conversión al shell central. El backend (`GET /api/production/machines`) decide qué sectores, máquinas y formularios ve la sesión: concesión del usuario, sector operativo, máquina activa y formulario publicado y vinculado a la máquina. La asignación activa y el permiso de captura se verifican igual que en Rebobinado.
- **Sin disponibilidad:** se muestra «Conversión no está habilitado» en Programación, Ejecución y Seguimiento, sin formularios ni creación de OT y sin datos demo, OT locales o registros legacy como respaldo.
- **Registros locales existentes:** el código central no lee ni escribe `vinto-ot`, `vinto-asg` ni `vinto-p1-records`, no borra nada y no convierte registros legacy en centrales. Los que existan en el navegador permanecen intactos (el E2E siembra un registro legacy y comprueba que se conserva y no se muestra). Como efecto de enrutar Conversión al shell central, las pantallas legacy de Conversión dejan de ser accesibles desde la navegación; es la misma decisión que M4-A tomó para Rebobinado.
- **Envío:** `POST /api/captures` con `capture_id` UUIDv4 fijo por intento, reintento idempotente (200 `already_submitted`), reconciliación por `GET` tras un timeout, intento pendiente que bloquea los campos y se conserva al volver, 409 `ASSIGNMENT_STALE` / `ASSIGNMENT_NOT_ACTIVE` con mensaje claro y retorno a Ejecución, 401 que vuelve al login limpiando intentos, historial central con parser estricto.

## 6. Pruebas ejecutadas

Línea base de `origin/main` medida en este entorno: backend 870 pruebas (2 fallos propios del entorno, ver abajo) y Node 451 OK.

| Prueba | Resultado |
|---|---|
| Backend `test_m6a_conversion_p116` (focalizada) | **24 OK** |
| Backend suite completa | **894 pruebas, 892 OK**; los 2 fallos son `test_db_guard.RealConnectionTests` (requieren DEV, ver §9) y fallan igual en `origin/main` con la misma configuración (870 pruebas, mismos 2 fallos) |
| Node (`node --test scripts/*.test.mjs`) | **470 OK** (451 + 19 nuevas) |
| `tsc --noEmit` | único error: el TS2322 heredado de `app/page.tsx` (sin errores nuevos) |
| `eslint .` | 0 errores; 2 avisos, ambos heredados (`m4a-e2e.mjs`, `export-seed-data.mjs`) y ninguno nuevo |
| `build` (sin ruta de QA; rutas `/` y `/admin`) | OK |
| E2E Conversión **habilitada** (`m6a-e2e.mjs`, Chrome real + FastAPI + PostgreSQL efímero) | **53/53** |
| E2E Conversión **deshabilitada** (configuración real) | **13/13** |
| Regresión M4-A Rebobinado habilitada (`m4a-e2e.mjs` sin cambios funcionales) | **49/49** (en M4-A fueron 50: falta solo el chequeo de DEV, omitido a propósito) |
| Regresión M4-A Rebobinado deshabilitada | **12/12** (13 en M4-A; mismo motivo) |

`m4a-e2e.mjs` recibió un único cambio: la variable `E2E_DEV_READ=off` omite las lecturas de solo `SELECT` sobre DEV (comprobación Z9) para no abrir ninguna conexión a DEV. `m6a-e2e.mjs` nunca las hace.

### Cobertura de los puntos A–L solicitados

| | Cubre |
|---|---|
| A | J1–J8: Jefatura crea y publica OT de Conversión desde la interfaz |
| B | K1–K3: Supervisión activa asignaciones |
| C | O1–O4: Operación abre P1-16 con el contexto de la asignación |
| D, E | O7–O11: envío, `POST` 201 + `GET` 200, detalles tipados en PostgreSQL, auditoría |
| F | O12–O13: Seguimiento recupera el registro con parser específico |
| G | R1–R4: reintento idempotente (respuesta perdida, petición perdida, reenvío por API, conflicto 409) |
| H | X2–X5 (asignación vencida, con el formulario abierto y al entrar) y backend `ShiftTests` (los tres turnos, cruce de medianoche, `stale`) |
| I | X6–X7: sector sin concesión; con y sin Rebobinado concedido |
| J | D1–D9: sector deshabilitado (configuración real) |
| K | X1 (formulario no vinculado), backend `test_an_unpublished_form_is_not_available` |
| L | J11–J12, D6–D7, L1 y la regresión M4-A |

## 7. Matriz inicial de decisiones industriales de Conversión

Ninguna está resuelta ni se asume aprobada. «Bloquea» = impide operar con datos reales; «Afecta» = cambia presentación o validación.

| # | Decisión pendiente | Bloquea / Afecta | Comportamiento hoy (prueba) |
|---|---|---|---|
| C-1 | **Qué es P1-16:** columnas de kg por tipo con correlativo y total (definición) o una pesada por registro (pantalla) | Bloquea | Pantalla (hipótesis) |
| C-2 | Correlativo de merma: ¿existe, manual o central, alcance y formato? | Bloquea si es central (requiere numerador y migración) | No existe |
| C-3 | Total de merma y cualquier fórmula | Afecta | No se calcula |
| C-4 | Firma de operador y de encargada, «grupo» y «encargado de turno»: el modelo central no los tiene | Bloquea si la ficha exige aprobación | No se capturan ni se simulan |
| C-5 | Unidad, rango y decimales del peso | Afecta | Solo decimal válido |
| C-6 | Máquinas permitidas de P1-16 (`todas`) y de P1-11/P1-12/P1-13 | Bloquea | GAMBINI de prueba |
| C-7 | Horarios, vigencia y regla de fecha operativa de los tres turnos | Bloquea | Hipótesis 06–14 / 14–22 / 22–06 |
| C-8 | ¿Horario por sector o por máquina? (el modelo actual es por sector) | Bloquea si difiere | Por sector |
| C-9 | Lista oficial de máquinas, artículos y relaciones artículo-máquina (98 relaciones candidatas); unidad `Pack` y clase `BLANCOS` | Bloquea | Fixture ficticio |
| C-10 | Qué hacer con los registros legacy de Conversión que ya existen en navegadores: descartar, conservar o importar | Afecta | Se conservan intactos y no se muestran |
| C-11 | Conversión de cantidades y peso nominal (maestro `INArticulo-MFMatrialOP`) | Afecta | No se usa |

## 8. Pendientes para P1-11, P1-12 y P1-13

No se implementan en M6-A. Cada uno necesita antes la decisión C-1 equivalente (definición o pantalla), porque **definición y pantalla actual difieren en los cuatro formularios**:

- **P1-12 (papel higiénico):** la definición es una producción diaria con balances de empaque, subempaque, bolsa, segundas y asas, merma y totales; la pantalla registra un pallet por envío (jabas, hora inicio y fin) con peso total = jabas × peso nominal del maestro y un número de pallet aleatorio generado en el cliente (`PAL-AAAAMMDD-XXXXXX`), que no es un correlativo central. Decidir: unidad de registro, correlativo, peso nominal, y si los 8 calculados (saldos, mermas, total) se calculan en cliente, servidor o no.
- **P1-13 (servilletas y especiales):** definición con consumo de bobina, producción, empaque e insumo (31 campos, 5 calculados); la pantalla es una ficha `NapkinSheet`. Mismas preguntas más la receta (15 de los 74 artículos no la tienen).
- **P1-11 (consumo de bobinas):** 61 campos, 22 calculados y 8 «condicional / repetible» (bobinas y rodelas inferior/superior). Sería el primer uso de **grupos repetibles en Conversión**. Depende de la fórmula de consumo (la pantalla usa `saldo inicial + ingreso − saldo final`, y «ingreso» no está en la definición) y de si el N.º de bobina sigue siendo texto libre o se vincula a las bobinas centrales de Bobinas/Rebobinado (hoy no hay servicio de consumo; ver M5-A).
- **Común:** el motor rechaza los campos `automatic` y `calculated`; los automáticos deben salir del contexto de la asignación (como en P1-10/P1-29) y los calculados necesitan una decisión de dónde calcularse antes de ser publicados.

## 9. Limitaciones

- Es un circuito **candidato**: ningún contrato, turno, máquina ni artículo está homologado por VINTO.
- Solo se probó una máquina con formulario (GAMBINI) y otra sin él (WALLY) en un fixture ficticio; las 11 máquinas reales y sus 98 relaciones no se importaron.
- Los `GROUPS` y los catálogos estáticos del frontend legacy no se tocaron: siguen en el código para los frentes que aún los usan (Calidad y los módulos legacy no migrados) y como referencia histórica.
- Las dos pruebas de `test_db_guard` (`test_dev_database_is_rejected`, `test_name_inside_connection_string_is_not_trusted`) necesitan conectarse a DEV en solo lectura y **no se ejecutaron** en este entorno: se corrió con `DATABASE_URL` apuntando a la base de pruebas para no abrir ninguna conexión a DEV. Fallan igual en `origin/main` con esa configuración (baseline medida).
- Las bases efímeras se crean en el mismo servidor PostgreSQL del entorno local (instancia de DEV) como en M2–M4; se eliminan al terminar y no se verificó modificación de la base `vinto`.

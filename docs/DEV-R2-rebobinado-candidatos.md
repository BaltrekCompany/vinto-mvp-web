# DEV-R2 · Fichas candidatas de Rebobinado: VINTO-P1-30 y VINTO-P1-07

Estado: **candidatas, NO homologadas**. Habilitadas solo en pruebas; Rebobinado sigue **no operativo** en la configuración real.

## Qué existe
- Captura central candidata de los campos **manuales** de las dos definiciones legacy, sobre el motor de Producción existente (`POST /api/captures`, `GET /api/captures/{id}`, `GET /api/captures?form_code=`), con contexto de **asignación**.
- Frontend: `lib/vinto/p1-30.ts`, `p1-07.ts`, `rebobinado-candidates.ts`; pantallas y historiales reutilizados (`CandidateFormCapture`, `CandidateHistory`, `SectorCentral`).
- Las fichas se ofrecen solo si `GET /api/production/machines` publica el formulario para la máquina de la sesión. Con la configuración real el backend no expone Rebobinado y no se ofrece nada.

## Contratos (fuente única: `lib/vinto/form-definitions.ts`)
- **P1-30** (PERICHUN): 15 campos = 10 manuales + 5 automáticos. `peso_de_bobina` y `numero_mrp` son TEXTO.
- **P1-07** (COPASA / BELOIT / OVER): 41 campos = 36 manuales + 5 automáticos. Incluye 21 pesos de crías individuales: `peso_cria_1`..`peso_cria_11` y `peso_cria_13`..`peso_cria_22`. **`peso_cria_12` no existe y no se inventa.** Obligatoriedad y tipos legacy sin cambios; la agrupación en pantalla es solo visual.

## Lo que NO se hace
- Las horas de inicio / término / final **no tienen fuente aprobada**: no se generan ni se sustituyen por `captured_at`.
- `numero_de_bobina` (P1-30) y `etiqueta_numero_de_bobina` (P1-07) son texto: no crean ni buscan bobinas ni identifican una bobina madre.
- **Un circuito de captura P1-07 NO equivale a una genealogía funcional** (ver `M5-A-p107-genealogia.md`): no se crean bobinas hijas, no se consumen madres, no hay relaciones madre-hija, correlativos, balances de masa, movimientos de inventario ni cambios en `quality_release`.
- No se calcula ningún peso, velocidad, resistencia ni total.

## Brechas pendientes de VINTO
- P1-30: horas de inicio y término; identidad y alcance del número de bobina; relación con MRP; validaciones y rangos.
- P1-07: horas de inicio y final; identidad de la bobina madre; genealogía madre-hija; cardinalidad y condicionalidad de los pesos de crías; catálogos de productos y destinos; reglas de corte, rendimiento y mermas.
- Máquinas y turnos oficiales de Rebobinado (el seed aprobado solo contiene MP1 y MP3; las máquinas y turnos de Rebobinado existen únicamente en fixtures `*_test`).

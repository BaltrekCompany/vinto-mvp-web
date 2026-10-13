# M3-A · Motor central de grupos repetibles

Estado: implementado en el motor de captura de producción (`capture_service`) y en el kit de frontend, **solo probado con un formulario SINTÉTICO en bases efímeras**. Ningún formulario industrial usa todavía grupos; no se habilitó ningún sector ni formulario nuevo; no hay migraciones (se reutilizan `field_group`, `capture_group_row` y `capture_detail`).

## Contrato HTTP (el envelope no cambia)
`POST /api/captures` conserva `{capture_id, form_code, assignment_id, device_key, values}`. En un formulario **con grupos**, `values` lleva los campos simples en el primer nivel y los grupos en la propiedad **reservada** `_groups`:

```json
{
  "lote": "L-001",
  "nota": "texto",
  "_groups": {
    "detalle": [ { "item": "A", "cantidad": 2, "peso": "1.50", "tipo": "a" }, { "item": "B", "cantidad": 5 } ],
    "extras":  [ { "etiqueta": "x", "valor": "0.10" } ]
  }
}
```
- **Orden:** la posición en la lista es el orden (`row_number = posición + 1`). El orden es contenido: el mismo `capture_id` con las filas reordenadas es un conflicto.
- **Respuesta:** `values` repite esa forma. `_groups` aparece **solo** si la versión publicada declara grupos y trae **todos** los grupos declarados (lista vacía si no hay filas). Las filas no exponen ids, `row_number` ni metadatos. Decimales como texto, enteros como número.
- **F6 y P1-10 no cambian:** al no declarar grupos, su payload y su respuesta no incluyen `_groups`, y enviar `_groups` a un formulario sin grupos es un `campo desconocido` (422), como cualquier otra clave.
- **Colisión:** ninguna definición puede tener un campo llamado `_groups` (la definición se rechaza con 409 `UNSUPPORTED_FORM_DEFINITION`).

## Validación (todo contra la definición publicada en PostgreSQL)
| Regla | Resultado |
|---|---|
| Grupo no declarado en la versión | 422 `_groups.<código>: grupo no declarado` |
| `_groups` no es objeto / un grupo no es lista / una fila no es objeto | 422 con la ruta (`_groups.detalle[2]: la fila debe ser un objeto`) |
| Menos filas que `min_rows` (incluye grupo ausente) / más que `max_rows` | 422 (`se requieren al menos N filas` / `máximo N filas`) |
| Grupo no repetible con más de una fila | 422 |
| Campo obligatorio por fila | 422 `_groups.detalle[2].item: obligatorio` |
| Tipos, opciones y decimales | los mismos que en los campos simples (`_normalize`) |
| Clave desconocida en la fila; ids, `row_number`, `group_row_id`, `field_group_id`, `created_by`, `revision`… | 422 `campo desconocido` |
| Campo de un grupo enviado en el primer nivel | 422 (se envía dentro de `_groups`) |
| Fila sin ningún valor | 422 `la fila no tiene valores` |
| Campos automáticos/calculados | siguen sin soportarse (409 `UNSUPPORTED_FORM_DEFINITION`) |
- Los mensajes nombran campos y filas, **nunca valores ni SQL**.
- **Límites:** son los de la definición. Solo cuando un grupo no declara `max_rows` se aplica un **tope técnico** de 1000 filas (`TECHNICAL_MAX_GROUP_ROWS`, no es una regla industrial).
- P1-03 y Calidad siguen rechazando definiciones con grupos (`load_fields` sin `allow_groups`).

## Persistencia, idempotencia y lecturas
- Una transacción: `capture` (draft) → `capture_group_row` + `capture_detail` por fila (grupos por `display_order`, filas por posición) → detalles simples → `submitted` (revisión 1). Cualquier fallo revierte todo (capturas, filas, detalles, dispositivo y auditoría). Los triggers existentes de cardinalidad y obligatorios siguen siendo la última defensa.
- Se conservan el contexto de la asignación, `production.capture`, sector operativo ∩ concedido, formulario publicado y máquina permitida, el orden de locks y la política `CENTRAL_FORM_CODES`.
- **Idempotencia:** el reintento se compara contra el contenido **completo**, filas incluidas y en orden: idéntico = 200 sin filas nuevas; cualquier celda, fila de más/menos, orden o campo distinto = 409. Omitir un grupo opcional equivale a enviarlo vacío.
- **Lecturas:** `GET /api/captures/{id}` y el listado con `form_code` reconstruyen simples + grupos + filas en su orden.

## Frontend reutilizable
- `lib/vinto/capture-groups.ts` (puro): `GroupSpec`/`GroupFieldSpec`, borradores por fila con clave local (`rowKey`, nunca se envía), `addRow`/`removeRow`/`setCell` inmutables que respetan mínimo, máximo y repetible, `validateGroup`/`buildGroups` (normaliza enteros y decimales como texto, errores con fila y campo, filas vacías), `buildGroupedValues`, `parseGroups`/`groupedValuesParser` (lectura estricta de `_groups` con el código de formulario esperado).
- `capture-kit.tsx`: `RepeatableGroup` (encabezado, contador y límites, filas numeradas, Agregar/Eliminar, errores por grupo y por fila, estado vacío, diseño móvil).
- `capture-core.ts`: `freezeAttempt` ahora hace copia **profunda** y congelada, así que agregar, eliminar o editar filas después no modifica un intento pendiente; el reintento envía exactamente el mismo payload (mismo `capture_id` y mismas filas en el mismo orden).

## Cómo añadir un formulario con grupos (cuando exista el contrato aprobado)
1. Definición aprobada en el bundle (formulario, versión, `field_group` con `repeatable/min_rows/max_rows`, campos con `field_group_id`, máquinas).
2. Una línea en `CENTRAL_FORM_CODES` (y el sector operativo, si aplica): cambio de código revisado.
3. En el frontend: una `GroupSpec[]` + un componente con `RepeatableGroup` (ejemplo tipado en `scripts/e2e/harness-grouped-page.tsx.txt`).
4. Pruebas con la definición real en una base efímera, como en `backend/tests/test_m3a_repeatable_groups.py`.

## Formularios V1 que podrían aprovechar el motor (lectura preliminar de las definiciones legacy, NO son decisiones)
La matriz legacy no declara grupos; esta lista sale de textos y claves de `lib/vinto/form-definitions.ts` y debe confirmarse con VINTO:
| Formulario | Indicio | Nota |
|---|---|---|
| **P1-29** Producción Tubetera (Rebobinado) | «Registrar una línea por cada rodela/lote de materia prima con su identificación y peso» | Candidato claro a un grupo de filas |
| **P1-07** Producción de bobinas refiladas (Rebobinado) | familia numerada `peso_cria` ×21 y `formato` ×3 | Filas por cría/formato; sector no operativo |
| **P1-11** Consumo de bobinas (Conversión) | «detalle repetible» | Toca consumo/genealogía: fuera de este incremento |
| **P1-01 / P1-02** Operación y parámetros de máquina (Bobinas) | «Mostrar como detalle repetible…» y familias numeradas (tanques, bombas) | Detalles repetibles por componente |
| P1-13 Producción diaria de servilletas (Conversión), P1-31 Consumo de químicos (Bobinas) | sin indicio explícito de filas (P1-31 menciona «fila» en otro contexto) | Revisar con VINTO |
| P1-19/20/24/25/27 (Calidad) | «detalle repetible» | Calidad usa su propio motor; no es este incremento |
Los formularios de un solo registro (F6, P1-10, P1-03) no necesitan grupos.

## Fuera de alcance
Centralizar P1-07/P1-11/P1-13/P1-29, bobinas hijas, genealogía, consumo o descuento de inventario, recetas, activar sectores, importar datos reales, reglas industriales y el hotfix de `/admin`.

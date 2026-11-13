# VINTO P1-11 V4 — Saldos opcionales en Consumo de bobinas

**Fecha:** 2026-11-13 (Lima)  
**Base:** `main` `f42cfd6c553a346971d4dfb8ad4a7b8e66ffcd92` (PR #182)  
**Entorno:** desarrollo GitHub / QA aislado; **sin merge ni despliegue VPS** hasta gates formales.

## Decisión funcional aprobada

- En **cada una de las tres posiciones** de P1-11, `saldo_inicial_kg`, `ingreso_kg` y `saldo_final_kg` son **opcionales**.
- La **posición 1** sigue siendo obligatoria. `posicion`, `tipo_material` (según receta del producto) y `numero_bobina` siguen siendo obligatorios en las posiciones que se registran.
- Las posiciones 2 y 3 siguen siendo opcionales. Si se empieza a llenar una, debe incluir sus tres datos de identificación y respetar el catálogo de materiales.
- Cálculo de vista de solo lectura: **saldo inicial + ingreso - saldo final**. Celda vacía equivale a **0 solamente en pantalla**, pero no se guarda un cero inexistente ni un campo `consumo_kg`.
- Si se digita un número decimal no válido, se bloquea ese envío (y el preview no lo trata como 0). Se permiten resultados de consumo negativos; sin reglas nuevas de inventario.

## Implementación y preservación histórica

- **V4 aditiva**: `backend/seed_data/forms/VINTO-P1-11.json` declara versión 4 y marca únicamente los tres saldos como `required=false`. Recalculados definition checksum y manifest SHA-256. No hay migración SQL.
- **V3 histórica inmutable**: definición exacta en `backend/tests/cv_p111_v3.json`, conserva los tres saldos obligatorios; el parser interpreta V3 según la definición histórica y V4 según la nueva.
- Frontend: `lib/vinto/p1-11-v3.ts` contiene ambas especificaciones, el formulario usa V4, conserva tres espacios, receta y posiciones, e indica qué campos son opcionales. `lib/vinto/p1-11.ts` hace parseo por versión sin alterar otras fichas.
- Backend: validación estricta por versión publicada en PostgreSQL; la API permite campos de saldo ausentes desde V4 y preserva ausencias al devolver la captura.
- Se conserva **P1-13** sin cambios; ya tiene los saldos opcionales y comparte la fórmula visual.
- La importación de referencias debe ser idempotente, exclusivamente aditiva para la nueva versión P1-11. No se reescriben capturas previas.

## QA de salida previo a merge

1. CI de P1-11 frontend (Node), TypeScript, ESLint y build.
2. PG17 real: creación P1-11 V4 con cero, uno o dos saldos; posiciones 1, 2, 3; respuesta y persistencia sin ceros inventados.
3. Regresiones P1-11 V3 históricas y V1/V2 de MF-11.
4. Importación V2 -> V3 -> V4 con checksums y filas anteriores preservadas; dry-run e idempotencia.
5. Sin permisos ampliados, sin migraciones, sin cambios a recetas ni P1-13.

**Producción:** exige respaldo verificado, dry-run de importación con 0 conflictos, autorización de apply, artefacto exact SHA, D2, activación controlada y QA visual. No realizar cambios en VPS desde esta rama.

# VINTO — Revisión formal de PR #181 y gate E1-08
**Fecha:** 2026-11-13 (Lima)  
**Repositorio:** BaltrekCompany/vinto-mvp-web  
**PR:** https://github.com/BaltrekCompany/vinto-mvp-web/pull/181  
**Rama:** feat/vinto-formas-p125-p116-20261113  
**Base productiva:** `19d2058652734d4a51268449d482522b2b2315e8`  
**Último commit revisado al escribir esta acta:** `6b84c361c2a415a6ffc206e797f0c5dd0867b3e0`

## 1. Dictamen

**NO-GO provisional para merge y despliegue.** No se ha autorizado ni ejecutado merge ni cambios en la VPS. La aprobación requiere comprobar los siete workflows en **PASS sobre el mismo SHA** y cerrar las regresiones del backend E1-08 sin suprimir ensayos ni ampliar la línea base histórica.

## 2. Hechos verificados

En el commit `af25d791d0acbbf2541c4e283b2be27785d11844`, GitHub Actions mostró seis workflows PASS y un workflow FAIL:

- PASS: RG-MP3-01 contrato aislado, CV-P111-v3, CV-P112-01, CV-P113-01, RB-CRIA-01 y foco E1-08 de 55 pruebas.
- FAIL: **E1-08 Sector execution integration QA**, únicamente en su trabajo backend; el trabajo frontend, TypeScript, ESLint y Next.js build fue PASS.
- El backend amplio ejecutó 2,447 tests y marcó **55 resultados nuevos de FAIL/ERROR respecto de la línea base histórica *pre-E1*** (`scripts/e1-backend-regression-baseline.json`, origen `86e4ec4f`). Esto **no prueba por sí solo 55 defectos funcionales nuevos**; también incluye expectativas y datos de prueba que anteceden a los releases actuales. No se permite ignorarlos: es una barrera técnica bloqueante hasta resolverlos o demostrar mediante evidencia independiente que ya existían en `main`.

## 3. Clasificación de hallazgos

| Grupo | Causa observada | Tratamiento |
| --- | --- | --- |
| F3 / P1-03 | Fixtures anteriores al PR #180 omiten `metraje` y `codigo_de_tubete` ahora obligatorios | Actualizar **fixtures** con valores ficticios válidos, sin flexibilizar validación de negocio |
| P1-05 Tubetes | Tests anteriores intentan crear capturas o concesiones después de la baja funcional | Exigir denegación (409) y cero nuevas filas; pruebas históricas con contexto aislado cuando corresponda |
| P1-16 V4 Merma | Esperas antiguas de V3, horas o conteos por versión | Distinguir historial V1–V3; V4 sin horas. La unicidad del correlativo está definida en código para V3+ |
| P1-07 / P1-10 / P1-25 | Matrices de versión y etiquetas obsoletas | Actualizar oráculos de versión a V5/V4/V4 respectivamente sin cambiar claves persistidas |
| MF-06 / MF-11 | Fixtures históricas reconstruidas desde el catálogo contemporáneo, que no tiene los mismos campos | Reconstrucción estrictamente en bases efímeras, con contratos previos inalterados |
| Otras suites antiguas | Aserciones de un catálogo anterior a CV-P111/P112/P113 y otros incrementos | Investigar caso por caso; no añadir exenciones genéricas al gate |

## 4. Cambios de esta revisión

- `ee3734c0`: corrección de fixtures F3 en múltiples módulos de prueba.
- `6d3ec82d`: ensayos de retirada P1-05 y correlativo P1-16 V4.
- `d1ca5385`: catálogo de concesiones y registros de administración, P1-10 V4.
- `b6711437`: expectativas de versiones históricas y dos campos obligatorios de F3.
- `d9472166`: versión histórica P1-16 V2 en comparación del importador y corrección del mapa de versiones.
- `6b84c361`: reconstrucción de P1-24 V4 y P1-16 V2 en pruebas aisladas.

Las modificaciones de esta etapa están dirigidas al **QA**, sin cambios de reglas industriales en producción. Toda modificación de pruebas debe revisarse por calidad y semántica, no únicamente por pasar CI.

## 5. Riesgos y controles

1. No destruir versiones ni capturas previas de P1-05; no reabrir su POST ni concesiones.
2. Mantener campos F3 de metraje y tubete obligatorios en el backend.
3. Mantener P1-10 V4 (Tipo cerrado, sin horas) y P1-16 V4 (sin horas) en el frontend y catálogo PostgreSQL.
4. Preservar identificador `formato_3` de P1-07 aunque su título sea «Cortes».
5. No modificar `scripts/e1-backend-regression-baseline.json` para absorber nuevos fallos.
6. Revisar que todo test histórico siga verificando los contratos de la época correspondiente y no sustituya las pruebas del comportamiento vigente.

## 6. Condiciones para cerrar el PR

- **QA CI:** 7/7 workflows PASS sobre un mismo commit final; especialmente backend E1-08, su foco de 55 casos y PostgreSQL 17.
- **Revisión formal:** sin desactivaciones de seguridad, sin borrados o migraciones destructivas, con diffs y comentarios del PR revisados.
- **Integración:** decisión explícita de merge tras gates completos.
- **Despliegue:** por separado, con preflight de solo lectura, backup nuevo verificado por restauración, importación de referencias dry-run y aplicación autorizada, artefacto frontend íntegro, activación y QA funcional.

**Estado de esta acta:** documento de revisión y trazabilidad; NO equivale a certificación PASS ni aprobación de producción.

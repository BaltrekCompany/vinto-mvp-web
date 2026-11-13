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


## 7. Continuación autorizada: corrección administrativa P1-05 (13/11/2026)

**Permiso:** desarrollo, QA y documentación exclusivamente en la rama del PR #181; **sin merge, importación ni despliegue VPS**.

### Diagnóstico comprobado en el SHA `116bf260d64b8062261a46685996323cf5df8527`

- Las ejecuciones aisladas USR-02, USR-03 y USR-04 terminaron FAIL en la misma prueba `HistoricalLinkTests.test_a_link_that_only_a_historical_version_has_is_not_offered_nor_listed`.
- La API `/api/admin/catalog` seguía incluyendo P1-05 en la lista de MP3 aunque `Catalog.pair(...).offered` ya era `false`; `/api/admin/catalog/forms` seguía mostrando MP3 bajo P1-05. La expectativa aprobada para baja funcional es **cero máquinas ofrecidas**.
- El control de seguridad **sí** rechazaba nuevas concesiones por `_require_offered` y las capturas por `assert_form_machine`; por eso el ajuste correcto es en la proyección administrativa y no en los registros de `vinto_config.form_version_machine`.

### Corrección aplicada en la rama (sin producción)

- `596ea36b`: las vistas `catalog_tree` y `catalog_forms` excluyen solo los códigos de `RETIRED_CAPTURE_FORMS` de sus asociaciones operativas. Se conserva la fila del formulario, su versión publicada y `Catalog.pair` para leer el estado inerte de concesiones existentes. No se modifican filas de BD.
- `b5205cac`: las expectativas de catálogo en `test_admin_grants_read_api.py` no tratan los formularios retirados como opciones ofertables. Se conserva la prueba de historial P1-05, las pruebas de rechazo y la igualdad entre oferta y política de concesión.
- **No** se excluyen por este mecanismo las máquinas inactivas ni otros formularios con `offered=false`: son estados distintos de una baja funcional. No se alteran `RETIRED_CAPTURE_FORMS`, permisos, formularios anteriores ni migraciones.

### Puerta de salida de esta corrección

Se requieren nuevos resultados CI en el SHA final y PASS verificado de USR-02/03/04, E1-08 amplio frontend/backend y foco 55 regresiones, además de las suites de formularios/PostgreSQL17. Si alguna falla, registrar diagnóstico exacto y mantener **NO-GO**. Los PASS de commits anteriores no certifican este cambio.

**Estado en el momento de registrar este avance:** código y oráculos actualizados, certificación CI del nuevo HEAD todavía pendiente; PR sigue **Draft / NO-GO**.


## 8. Gate E1-08 amplio: seis resultados nuevos (revisión 13/11/2026)

**Evidencia de GitHub Actions:** [run 43497030950](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/43497030950) sobre `571b2b15f86a1b54d97bb008b74b2740ce1fccbd`. De 13 workflows, 12 PASS y uno FAIL: `E1-08 Sector execution integration QA`, **frontend PASS**, **backend FAIL**. El gate diferencial ejecutó **2463 tests**, 7 FAIL históricos, 103 ERROR históricos, 6 omitidos auditados y **6 FAIL/ERROR nuevos** contra la línea base pre-E1. Las excepciones históricas **no** se modificaron.

### Causas exactas (seis resultados bloqueantes)

1. `test_bobbin_authz.VersionTests.test_a_vigente_version_of_another_area_or_not_offered_denies_and_writes_nothing`: la prueba intentaba crear P1-03 V2, que ya existe por el PR #180; conflicto `form_version_form_id_version_number_key`.
2. `test_mf11_calidad_conversion.DefinitionTests.test_hours_are_one_required_manual_time_pair_in_each_conversion_form`: fixture de P1-11 procedente de V3 (sin horas y con `tipo_material`), en lugar del contrato **V2** de MF-11.
3. `test_mf11_calidad_conversion.HoursTests.test_p1_11_hours_and_the_bobbin_rows_keep_working`: se enviaba una fila de cinco campos a P1-11 V3, que exige `tipo_material`; HTTP 422.
4. `test_mf11_calidad_conversion.HoursTests.test_p1_13_has_a_single_pair_of_general_hours`: se enviaban campos del P1-13 V2 histórico a la versión contemporánea V4 (Tipo y N.º bobina), con HTTP 422.
5. `test_mf11_calidad_conversion.HoursTests.test_p1_13_is_available_in_all_its_machines`: misma incompatibilidad de fixture/versión de P1-13.
6. `test_mf11_calidad_conversion.ProductionImportScenarioTests.test_the_bundle_adds_only_the_seven_new_versions_and_is_idempotent`: el fixture P1-11 V3 cambiaba el total de campos a 101, cuando MF-11 V2 históricamente crea 102.

### Cambios correctivos implementados (solo rama PR #181)

- `31a1a79b`: se preserva `backend/tests/cv_p111_v2.json`, **copia textual de** `backend/seed_data/forms/VINTO-P1-11.json` en el commit previo `83c3a257`, blob `fe47e6bfe46251cf83a6ad4c5931ebbc928cae87`. Conserva campos originales, horas, cinco columnas de bobinas y checksum auténtico.
- `9feaced2`: la prueba MF-11 usa esa definición histórica de P1-11 V2; el caso P1-13 conserva la fixture auténtica `cv_p113_v2.json`. Solo dentro de la BD PostgreSQL17 efímera del ensayo se retiran de la vista publicada versiones posteriores de P1-11 y P1-13 para ejercitar V2, tal como ya se hacía con P1-12, P1-16 y P1-24. No cambia el catálogo productivo ni sus validaciones.
- `5e55ac4c`: la prueba negativa F3 asigna versiones de prueba mayores que la máxima ya almacenada, evitando duplicar P1-03 V2; conserva verificaciones de autorización 403 y cero escrituras.

**Control de integridad:** no se han alterado `scripts/e1-backend-regression-baseline.json`, políticas de producción, migraciones, fórmulas, permisos ni versiones históricas de base productiva. No se ha deshabilitado ningún test. Las únicas retiradas de versiones ocurren en bases `*_test` desechables, dentro del ensayo histórico.

**Estado:** correcciones disponibles para ejecutar CI sobre el SHA final; **NO-GO** hasta que E1-08 frontend/backend, el foco de 55 y el resto de workflows resulten PASS sobre ese mismo SHA. Sin merge y sin VPS.


## 9. Segundo ciclo de QA E1-08 — dos checks bloqueados por un único contrato histórico

**Evidencia:** [RG-MP3-01 E1-08 focus, run 43501669699](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/43501669699) y [USR-06 readiness, run 43501669798](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/43501669798). Ambos ejecutaron las **mismas 55 pruebas** del foco MP3/E1-08 sobre `15fdd6a938cb63a06af0eca4116723f0d1b278b5`; 54 PASS, **1 FAIL**, 0 ERROR y 0 SKIP. El fallo repetido se origina en `test_mf11_calidad_conversion.DefinitionTests.test_the_seven_new_versions_and_no_other_form_changes`: la fixture auténtica histórica `P1-11 V2` ya fue restaurada, pero la tabla `VERSIONS` del propio ensayo aún esperaba `P111: 3`.

**Corrección acotada:** commit `ae84ce3d`. Se cambia solo la expectativa `VERSIONS[P111]` de 3 a 2 en el ensayo histórico MF-11, dejando `NEW_VERSION[P111] = 3` y la versión real publicada V3 **sin cambios**. No se desactivan pruebas, no se modifican reglas de negocio, esquemas, migraciones, permisos ni baselines de regresiones. Tampoco se modifica la VPS.

**Gate:** la integración E1-08 amplia seguía ejecutándose cuando se revisó el fallo; este cambio requiere nueva ejecución de los 13 workflows sobre el SHA actualizado. Mantener **NO-GO** hasta que el foco de 55, USR-06, E1-08 amplio y restantes suites cierren todos en PASS.


### Aclaración del contrato histórico MF-11 (comparación con commit `83c3a257`)

La comparación contra el archivo de pruebas original del commit `83c3a257` reveló que en este escenario el par coherente era **`VERSIONS[P111] = 2` y `NEW_VERSION[P111] = 2`**. El commit `8b2355a0` restaura la segunda constante, que se utiliza para importar/leer V2 y ejercitar V1 como versión anterior dentro de la base efímera. Dejar `NEW_VERSION[P111] = 3` habría provocado nuevas discrepancias en pruebas de lectura e importación de MF-11. La ficha **P1-11 V3 productiva no se modifica** ni se reclasifica; solo se reproduce el contrato histórico original de 2026-11-11 para verificar compatibilidad.

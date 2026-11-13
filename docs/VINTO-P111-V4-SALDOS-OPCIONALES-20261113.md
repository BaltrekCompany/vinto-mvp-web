# VINTO P1-11 V4 — Saldos opcionales en Consumo de bobinas

**Fecha de cierre:** 13 de noviembre de 2026 (Lima)  
**Estado:** CIERRE FUNCIONAL CONFIRMADO POR EL RESPONSABLE — PR fusionado, importación aditiva validada, funcionamiento de interfaz confirmado.  
**PR:** [#183 — P1-11 V4 saldos opcionales](https://github.com/BaltrekCompany/vinto-mvp-web/pull/183)  
**Commit de release:** `771ff334179d470605f6295e6cb29a5ce7dbf18f` (merge confirmado en `main`, 2026-11-13 22:42:47 UTC)  
**Base anterior:** `f42cfd6c553a346971d4dfb8ad4a7b8e66ffcd92` (PR #182)

## 1. Alcance funcional aprobado

- Formulario: `VINTO-P1-11` **Consumo de bobinas**, versión **V4**.
- En cada una de las tres posiciones se permiten vacíos en `saldo_inicial_kg`, `ingreso_kg` y `saldo_final_kg`. Esos tres campos **no son obligatorios**.
- La **posición 1** es obligatoria. Las posiciones 2 y 3 son opcionales.
- En **cada posición efectivamente registrada**, se requieren `posicion`, `tipo_material` (perteneciente a receta del artículo de la OT) y `numero_bobina`.
- El consumo de la pantalla es **saldo inicial + ingreso − saldo final**. El saldo sin informar equivale a **0 únicamente para el cálculo visual**. No se guarda cero inventado ni un campo derivado de consumo en la captura.
- Un valor decimal no vacío inválido sigue rechazándose. Se permiten consumos calculados negativos, sin crear nuevos movimientos de inventario ni reglas industriales.
- **P1-13, recetas, permisos, máquinas y otras pantallas no se modificaron** para este ajuste.

## 2. Implementación y preservación histórica

- El catálogo oficial `backend/seed_data/forms/VINTO-P1-11.json` publica **V4 aditiva**: únicamente los tres saldos pasan de `required=true` a `required=false`.
- `definition_checksum` V4: `918886b3336d09d5bbc43eb2507b7bc032d3035bc9c958005c55dbda0b42b4e6`.
- `source_checksum` del bundle completo: `8037ea9d876c45e255bc62dd9dcc34ee8066f75541bcfbc21aee355d1aba353b`.
- La definición **V3** se mantiene para capturas históricas, con los saldos obligatorios. La fixture original se conserva en `backend/tests/cv_p111_v3.json`.
- El parser frontend interpreta V3 y V4 de manera diferenciada. El backend valida los campos según la versión de formulario publicada en PostgreSQL.
- **No hubo nueva migración SQL**: se conservaron las migraciones 0001–0031 ya aplicadas.

## 3. QA formal de GitHub

Todos los workflows finalizados con `success` sobre el HEAD revisado de PR #183, `87394de8384c46104bf14298462de96dc171b54d`:

| Control | Ejecución | Resultado |
| --- | --- | --- |
| P1-11 frontend, API PostgreSQL17 y regresiones históricas | [43520585128](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/43520585128) | PASS |
| P1-12 pallets | [43520585111](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/43520585111) | PASS |
| P1-13 servilletas | [43520585097](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/43520585097) | PASS |
| RG-MP3-01 contratos y permisos | [43520585148](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/43520585148) | PASS |
| RB-CRIA-01 crías y Calidad | [43520585135](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/43520585135) | PASS |
| E1-08 regresiones históricas | [43520585078](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/43520585078) | **PASS: 55 tests, 0 failures, 0 errors, 0 skipped** |

En revisiones intermedias se corrigieron expectativas estáticas de `VINTO-P1-11=3` a `=4` en pruebas del catálogo vigente, sin omitir regresiones ni modificar el comportamiento V3 histórico.

**Artefacto Linux exact-SHA** creado en GitHub Actions: [workflow 43526851613](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/43526851613), `success`, `head_sha=771ff334179d470605f6295e6cb29a5ce7dbf18f`. Manifiesto transferido a VPS y verificado por instalador; SHA-256 del tarball `ff198165b6aa3aaf138c4826247da168133787d0b3b0d085cba096a173111adc`.

## 4. VPS y base de datos — evidencia operativa aportada

Ambiente: `vinto_piloto` (PostgreSQL17), VINTO MVP; sin alteraciones previstas a TVC.

Evidencia **aportada por el operador** en los registros de terminal de esta conversación:

- Release candidato `771ff334179d470605f6295e6cb29a5ce7dbf18f` instalado en `/opt/vinto-mvp-web/releases/<sha>` con checksum y frontend verificados: `P183_RELEASE_CANDIDATO=PASS`.
- Migraciones 0001–0031 ya aplicadas: `P183_ESQUEMA=PASS`; no se ejecutó ninguna migración nueva.
- D2 `D2_OPS_GATE_ROLLBACK=PASS`, `open_handoff_count=0`, `blockers=[]`.
- Dry-run oficial V4 en `vinto_piloto`: **15 altas aditivas, 0 conflictos, 0 escrituras**.
- Importación real autorizada sin respaldo nuevo: **batch `3aae631a-8772-4662-9466-2652f1feffa6`**.
- Altas: 1 `form_version`, 3 `form_version_machine`, 1 `field_group`, 7 `field`, 3 `option`. Sin altas en artículos, artículos/máquinas, usuarios, roles o recetas.
- Dry-run posterior al apply: `CONSISTENT / NO CHANGES`, 0 escrituras; `VINTO_P183_CATALOGO_CONSISTENTE=PASS`.
- Salud de backend, base y frontend `PASS` **antes de la activación**: `VINTO_P183_LISTO_PARA_ACTIVACION=PASS`.

**Confirmación funcional posterior:** el responsable informó expresamente **“Ya está funcionando bien”** y pidió el cierre en GitHub el 13/11/2026. Se registra como **QA funcional confirmado por el usuario**.

**Límite de evidencia:** no se adjuntó en esta conversación la salida completa del comando de activación, el `current` posterior ni el QA SQL post-activación. Por tanto, este documento no presenta esos tres controles como comprobaciones independientes de la VPS; la confirmación final se apoya en el reporte funcional del responsable.

## 5. Decisión sobre respaldo y riesgo aceptado

Por decisión explícita del responsable se preparó y ejecutó **sin generar respaldo nuevo**, al considerarse una modificación pequeña. **No se interpreta como eliminación general del requisito de respaldos futuros.**

El respaldo verificado anterior disponible en los registros de esta secuencia era:
`/home/ubuntu/vinto-mvp-backups/vinto-mvp-vinto_piloto-20261113-222345-2673626.dump`.

Ese respaldo **precede** a la importación V4 y puede no incluir capturas realizadas posteriormente. Ninguna recuperación automática de PostgreSQL desde ese respaldo queda autorizada por este cierre. La eventual reversión de código tampoco equivale a revertir el catálogo ni garantiza preservar nuevas capturas.

## 6. Cierre y operación

- **Desarrollo:** cerrado por merge del PR #183.
- **Pruebas automáticas:** PASS, seis de seis workflows.
- **Catálogo V4:** importado, consistente e idempotente tras la aplicación.
- **Validación funcional:** confirmada por el usuario.
- **Nuevas modificaciones solicitadas para P1-11 V4:** ninguna al cierre.
- **Pendiente documental opcional, sin bloquear el cierre funcional:** anexar en una revisión posterior el log de `current`/healthcheck después de la activación, si se requiere auditoría técnica completa.
- **Operación:** mantener la política habitual de monitoreo y respaldo; no repetir la importación `--apply` si el catálogo permanece consistente.

**Conclusión:** P1-11 V4 se da por cerrado funcionalmente con trazabilidad de GitHub, QA aislado PASS, importación controlada y conformidad expresada por el responsable. Este documento es exclusivamente de cierre; no incluye modificaciones funcionales.

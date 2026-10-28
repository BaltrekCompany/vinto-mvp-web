# MF-11 · Calidad y Conversión (P1-26 v3, P1-27 v2, P1-24 v4, P1-11 v2, P1-12 v3, P1-13 v2, P1-16 v2)

## 1. Objetivo
Atender, con versionado aditivo y sin tocar capturas históricas, las observaciones **MD_Ejec 33, 35, 46, 48 y 51** del Excel funcional `MvP (Producción + Calidad) - v2.xlsx` (hoja `MD_Ejec.`), con las decisiones funcionales confirmadas. El Excel original **no se modifica**. Base: `main` tras MF-10 (PR #79, `e51e9a6`).

## 2. Observaciones atendidas
| Obs. | Formulario (máquinas) | Cambio | Estado |
|---|---|---|---|
| 33 | **P1-26** Medición de secos (MP1, MP3) → **v3** | Campo «**Absorción de humedad**»: decimal digitado, **opcional**, unidad visible **%**, justo después de «Masa seca». No se calcula, sin rango ni límite. «% Cantidad de seco» no cambia. | Implementada |
| 35 | **P1-27** Análisis de agua para caldero (MP1, MP3) → **v2** | Campo «**Alcalinidad total**» (clave `alcalinidad_total`): decimal digitado, **opcional**, **sin unidad**, sin rango ni fórmula, en la sección «Purga de caldero» tras «Purga caldero cloruros». | Implementada |
| 51 | **P1-24** Propiedades físicas en húmedo (MP1, MP3) → **v4** | «Crepado» → «**Crepado (%)**» con la unidad % junto al campo. Misma clave, tipo (decimal) y obligatoriedad (obligatorio). Sin rango 0–100 ni conversión de valores. | Implementada |
| 46 | **P1-13** Producción diaria de servilletas y especiales (8 máquinas) → **v2** | «**Hora inicio**» y «**Hora fin**» generales, obligatorias. | Implementada |
| 48 | **P1-11** Consumo de bobinas → **v2**, **P1-12** Producción diaria de papel higiénico → **v3**, **P1-13** → v2 (mismo par que la 46), **P1-16** Registro de control de merma → **v2** | Mismas «Hora inicio» y «Hora fin» generales. | Implementada |

Ninguna observación quedó bloqueada. Las observaciones **no se declaran cerradas** hasta superar el QA manual en producción.

## 3. Cambios por formulario (anterior → nuevo)
| Formulario | Versión anterior | Versión nueva | Campos (anterior → nuevo) | Cambio |
|---|---|---|---|---|
| P1-26 | v2 | **v3** | 5 → 6 | + `absorcion_de_humedad` (decimal, opcional) |
| P1-27 | v1 | **v2** | 23 → 24 | + `alcalinidad_total` (decimal, opcional, sin unidad) |
| P1-24 | v3 | **v4** | 12 → 12 | `crepado`: etiqueta «Crepado» → «Crepado (%)» (solo etiqueta y unidad visual) |
| P1-11 | v1 | **v2** | 1 + grupo de 5 → 3 + grupo de 5 | + `hora_inicio`, `hora_fin`; el grupo repetible `bobinas` no cambia |
| P1-12 | v2 | **v3** | 20 → 22 | + `hora_inicio`, `hora_fin` (las demás reglas de MF-10, incluido «Formato» de texto libre, siguen) |
| P1-13 | v1 | **v2** | 18 → 20 | + `hora_inicio`, `hora_fin` (un único par para las observaciones 46 y 48) |
| P1-16 | v1 | **v2** | 8 → 10 | + `hora_inicio`, `hora_fin` |

El % de P1-26 y P1-24 es **solo visual** (`suffix` en el frontend): no se añade ninguna unidad al catálogo del seed (`units.json` no cambia), igual que el «% Cantidad de seco» de MF-08.

## 4. Campos nuevos
| Campo | Formulario | Tipo | Obligatorio | Unidad | Posición |
|---|---|---|---|---|---|
| `absorcion_de_humedad` | P1-26 v3 | decimal digitado | No | % (visual) | tras `masa_seca` |
| `alcalinidad_total` | P1-27 v2 | decimal digitado | No | ninguna | tras `purga_caldero_cloruros` |
| `hora_inicio`, `hora_fin` | P1-11 v2, P1-12 v3, P1-13 v2, P1-16 v2 | hora (HH:MM) digitada | **Sí** | — | primeros campos; sección «Horas de producción» |

**Alcalinidad total y la clave calculada legacy.** La definición legacy de P1-27 (`form_27_analisis_de_agua_para_caldero`) declara `purga_caldero_alcalinidad_total` como campo **calculado** sin fórmula. Esa clave **nunca se importó** al seed (ni v1 ni v2) y el backend sigue rechazando cualquier valor enviado con ella (422, campo desconocido). La alcalinidad nueva es un campo **manual** con clave **distinta** (`alcalinidad_total`): no hay colisión, duplicado ni cálculo.

## 5. Horas generales de producción (obs. 46 y 48)
- HH:MM, **hora local de planta digitada**; obligatorias; aceptan `00:00` y `23:59`; se rechazan `24:00`, `12:60`, `7:30`, texto y vacío.
- Se guardan tal como se digitaron (hora sin zona): **sin conversión a UTC**, **sin duración**, **sin exigir fin > inicio**, **sin fecha adicional** al cruzar la medianoche (la fecha operativa sigue siendo la de la asignación).
- Son distintas de la hora automática de registro (`captured_at`) y de las horas de **pallet**.
- **Horas de pallet:** la definición vigente (seed y backend) de P1-12 y P1-13 **no contiene campos de pallet**: las horas «Hora inicio/fin del pallet» solo existían en la pantalla de hipótesis anterior (`components/vinto/p1-12-capture.tsx`, `P112_LABELS`), que no está conectada a la aplicación y **no se modifica**. Por eso en P1-13 hay **un único par** de horas (las observaciones 46 y 48 no crean campos duplicados; hay una prueba que lo comprueba).
- No hay integración con TVC ni nuevas reglas de duración.
- P1-11 usa su propio componente con grupo repetible: las horas se añadieron allí (sección «Horas de producción», antes del grupo de bobinas) y en su historial.

## 6. Conservación de capturas históricas
- Versionado aditivo e idempotente: las versiones anteriores y sus capturas quedan publicadas e intactas; el backend usa la versión publicada más alta para capturas **nuevas** y cada captura conserva su `form_version_id`.
- No se añaden horas, absorción, alcalinidad ni porcentajes retroactivamente. El parser de cada captura recibe **su** versión (`sinceVersion`, `renamedAt`, y en P1-11 `parseSimpleFor(version)`): las capturas v1/v2 se leen sin exigir los campos nuevos.
- P1-24: el historial muestra «Crepado» (v3 y anteriores, con `labelFor`/`renamedAt`) y «Crepado (%)» (v4); el valor almacenado no se transforma.
- No se toca Crepado de **P1-20 ni P1-25**.

## 7. Pruebas y resultados
| Suite | Resultado |
|---|---|
| Backend nuevo `backend/tests/test_mf11_calidad_conversion.py` (PostgreSQL efímero, formularios reales del bundle; 25 pruebas) | **OK** |
| Backend suite completa (`python -B -m unittest discover -s tests -p "test_*.py"` en `vinto-test-py`) | ver §7.1 |
| Frontend nuevo `scripts/mf11-calidad-conversion.test.mjs` (16 pruebas) | **OK** |
| Frontend suite completa (`node --test scripts/*.test.mjs`) | 773 pruebas, 751 OK, **22 fallos idénticos a `main`** (mismos nombres; son preexistentes: por ejemplo «alcance: …» que buscan políticas vacías) |
| `tsc --noEmit` / ESLint | sin errores |

Pruebas existentes adaptadas (los formularios cambiaron de versión o de número de campos): `p1-11-capture`, `p1-22-p1-26-capture`, `p1-24-p1-25-capture`, `p1-27-p1-28-capture`, `mf08-quality-machine-forms` y `mf10-rebobinado-conversion` (frontend); las pruebas de backend que enumeran versiones (ver §7.1).

Cubierto por las pruebas nuevas:
- **Calidad:** absorción y alcalinidad aceptan decimales (incluido 0 y valores grandes sin rango), pueden quedar vacías/nulas y no se guardan; el cálculo de «% Cantidad de seco» sigue igual; la clave calculada legacy se rechaza; las versiones anteriores siguen disponibles y legibles; «Crepado (%)» con misma clave/tipo/obligatoriedad y sin rango.
- **Conversión:** horas obligatorias y de formato HH:MM, `00:00`/`23:59`, fin anterior a inicio aceptado, valores guardados tal cual (`time`), un solo par en P1-13, formularios de MF-05 a MF-10 intactos, P1-13 operativo en sus 8 máquinas y P1-16 en las suyas.
- **Importación:** escenario de producción (todas las versiones anteriores ya instaladas) con dry-run y apply, y segunda importación idempotente.

### 7.1 Suite completa de backend
Se ejecutó cada módulo `backend/tests/test_*.py` por separado (`cd backend/tests && python -B -m unittest <módulo>`, PostgreSQL local de pruebas recreado limpio). Resultado: **todos los módulos OK salvo dos que fallan igual en `main` en este entorno local** (no relacionados con MF-11): `test_db_guard` (3 fallos: el nombre de la base de pruebas local) y `test_capture_count_authorization` (1 fallo). Los módulos que enumeraban versiones o conteos se adaptaron: `test_seed_bundle`, `test_bundle_validation` (huella del bundle), `test_import_reference` (472 campos, 1936 registros), `test_mf06`, `test_mf07`, `test_mf08`, `test_mf09` y `test_mf10`. En MF-08 y MF-10 la base efímera retira la versión nueva y publica la anterior (`restore_previous`) para seguir probando esos paquetes.

## 8. Dry-run en entorno aislado (cifras esperadas)
Sobre una base efímera con el estado de producción previo a MF-11 (todo el bundle vigente con las siete versiones anteriores) el importador informa exactamente:

| Concepto | Crear |
|---|---|
| `form_version` | **7** |
| `field` | **102** (6 + 24 + 12 + 8 + 22 + 20 + 10; en P1-11 se cuentan 3 campos + 5 del grupo) |
| `form_version_machine` | **31** (2 + 2 + 2 + 3 + 3 + 8 + 11) |
| `field_group` | **1** (grupo `bobinas` de P1-11 v2) |
| `option` | **8** (6 del punto de muestreo de P1-26 v3 + 2 posiciones del grupo de P1-11 v2) |
| Conflictos | **0** |

`manifest.json`: `form_fields` 462 → **472** (las siete versiones nuevas como últimas versiones del bundle; las anteriores solo existen ya en la base). Sin migraciones.

## 9. Pendientes y exclusiones
Fuera de MF-11 (no se implementó): observación 11 (renombres de tanques); Crepado en P1-20 y P1-25; rango 0–100 para Crepado; unidad o fórmula de la alcalinidad total; cálculo de la absorción de humedad; duración entre hora inicio y fin; integración de horas con TVC; rediseño de recetas, mermas y catálogos; permisos y proceso de liberación/rechazo de Calidad; actualización de Monday o del Excel maestro; cambios sobre `vinto-web`, TVC, ETL o sus bases de datos.

## 10. Pasos de QA manual (después del despliegue)
1. **P1-26** (QA.CALIDAD, MP1 y MP3): «Absorción de humedad» aparece tras «Masa seca» con la unidad %, sin asterisco; registrar con y sin valor; «% Cantidad de seco» se sigue calculando; el historial muestra la absorción solo en las capturas nuevas.
2. **P1-27** (QA.CALIDAD): «Alcalinidad total» en «Purga de caldero», sin unidad ni asterisco; registrar con y sin valor.
3. **P1-24** (QA.CALIDAD, bobina MP1/MP3): «Crepado (%)» con la unidad %; aceptar cualquier decimal; capturas anteriores se ven como «Crepado». Comprobar que P1-25 y P1-20 siguen con «Crepado».
4. **Conversión** (QA.OPERACION, p. ej. Gambini, Sincro II/III y las máquinas de servilletas): en P1-11, P1-12, P1-13 y P1-16 aparecen «Hora inicio *» y «Hora fin *» al inicio; probar `00:00`, `23:59`, fin anterior a inicio (se guarda sin avisos de orden), formato incorrecto y envío sin hora (se rechaza).
5. **P1-13:** un solo par de horas.
6. Historial de P1-11, P1-12, P1-13, P1-16: capturas anteriores legibles sin horas; las nuevas con sus horas.
7. Confirmar que P1-01, P1-06, P1-07, P1-10, P1-18, P1-21, P1-22, P1-25, P1-29 y P1-30 no cambiaron.

## 11. Procedimiento propuesto de publicación (NO ejecutado)
Solo con autorización expresa, como en MF-05 a MF-10: preflight; respaldo `backup.sh create-and-verify` con restauración aislada; artefacto de frontend con checksum y arranque aislado; instalación sin activar; **dry-run** esperando exactamente las cifras del §8 (si difiere, detenerse); importación aditiva como usuario `vinto-mvp`; activación con `deploy/mvp`; healthcheck; verificación de las siete versiones publicadas, de sus vínculos de máquina, de las capturas históricas intactas, de los demás formularios sin cambios y de que `vinto-web`/TVC/ETL no se tocaron. Rollback de código con el procedimiento oficial; marcar versiones como `retired` o restaurar datos requiere autorización expresa.

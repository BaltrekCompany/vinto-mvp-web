# MF-12A · P1-01 v4 (Release/Coating y campos rojos/azules) y disponibilidad de P1-05 / P1-31 por máquina

## 1. Objetivo
Atender, con versionado aditivo y sin tocar capturas históricas, las observaciones **MD_Ejec 9, 14 y 20** del Excel funcional `MvP (Producción + Calidad) - v2.xlsx` (hoja `MD_Ejec.`), con las decisiones D1, D2 y D10 aprobadas. El Excel original **no se modifica**. Base: `main` tras MF-11 (PR #80, merge `b24013e`). Esta entrega es **solo un PR revisable**: no se despliega ni se importa nada en producción.

## 2. Observaciones atendidas y decisiones
| Obs. | Formulario | Cambio | Decisión |
|---|---|---|---|
| **9** | **P1-01 v4** (MP1 y MP3) | «Dosificación Release» se conserva tal cual. Se añaden tres campos de **texto libre, opcionales, sin unidad ni rango**: **Frecuencia Release**, **Dosificación Coating** y **Frecuencia Coating**, junto a «Dosificación Release» en la sección «Químicos». | **D1**: las tres claves y su obligatoriedad (opcionales) quedan como las aprobadas; no se asume otra obligatoriedad ni unidad. |
| **14** | **P1-01 v4** (la misma versión) | Se retiran los cuatro campos **rojos** y dos de los **azules**; los otros dos azules pasan a **claves nuevas**. Ver §3. | **D2**: un único campo por concepto; el histórico no se reinterpreta. |
| **20** | **P1-05 v2** y **P1-31 v2** | Mismos campos que v1, vinculadas **solo a MP3**: dejan de ofrecerse y de aceptar capturas nuevas en MP1. | **D10**: bloqueo completo (tarjeta **y** acceso directo a la API), no solo visual. |

## 3. Matriz de campos de P1-01 (v3 → v4; 73 → 70 campos)
| Campo (clave) | v3 | v4 | Comentario |
|---|---|---|---|
| `dosificacion_release` | texto, obligatorio | **igual** | no cambia |
| `frecuencia_release` | — | texto, **opcional**, sin unidad | nuevo (obs. 9) |
| `dosificacion_coating` | — | texto, **opcional**, sin unidad | nuevo (obs. 9) |
| `frecuencia_coating` | — | texto, **opcional**, sin unidad | nuevo (obs. 9) |
| `apertura_purga_prensa` | texto, obligatorio | **retirado** (rojo) | solo historial |
| `presion_aceite_guia_tela` | decimal, obligatorio | **retirado** (rojo) | solo historial |
| `presion_aceite_lubricacion` | decimal, obligatorio | **retirado** (rojo) | solo historial |
| `vacio_tela` | decimal, obligatorio | **retirado** (rojo) | solo historial |
| `vacio_prensa` | decimal, obligatorio | **retirado** (azul) | su concepto ya existe como `velocidad_secador` |
| `vacio_fieltro` | decimal, obligatorio | **retirado** (azul) | su concepto ya existe como `velocidad_fieltro` |
| `rodillos_quimicos` | texto, obligatorio | **retirado** | sustituido por `boquillas_quimicos` |
| `boquillas_quimicos` | — | texto, obligatorio, «Boquillas químicos» | **clave nueva**, misma posición |
| `vacio_pope` | decimal, obligatorio | **retirado** | sustituido por `velocidad_pope` |
| `velocidad_pope` | — | decimal, obligatorio, «Velocidad pope» | **clave nueva**, misma posición; **sin unidad declarada** (no confirmada; los demás «Velocidad» muestran m/min solo como texto visual y aquí no se asume) |
| `velocidad_secador`, `velocidad_fieltro` | decimal, obligatorio | **igual** | un único campo activo por concepto |

Los 62 campos restantes (incluidos los de tanques de la obs. 11) conservan clave, etiqueta, tipo, obligatoriedad, unidad y orden relativo. La prueba `test_p1_01_v4_removes_replaces_and_adds_exactly_what_was_approved` lo verifica contra la definición v3 de producción (copia en `backend/tests/mf12a_p101_v3.json`).

**Por qué claves nuevas (D2).** «Rodillos químicos» → «Boquillas químicos» y «Vacío pope» → «Velocidad pope» cambian de concepto físico; si se renombrara la clave, los valores históricos pasarían a leerse como otra magnitud. Por eso la clave antigua queda **solo de lectura** en el historial (lista `legacy`, «versión anterior») y **ningún valor se traslada** entre claves.

**Secciones.** Las siete secciones conservan su nombre y orden (obs. 5, excluida). «Químicos» ahora empieza con `dosificacion_release`, `frecuencia_release`, `dosificacion_coating`, `frecuencia_coating`, `dosificacion_fosfato`; en «Prensa, aceite, vacío y filtros» salen los campos retirados y las claves nuevas ocupan la posición de las que sustituyen.

## 4. Versiones
| Formulario | Antes (producción) | Después | Campos | Vínculos de máquina |
|---|---|---|---|---|
| VINTO-P1-01 | v1, v2, v3 | **v4** | 70 | MP1, MP3 |
| VINTO-P1-05 | v1 | **v2** | 10 (idénticos a v1) | **solo MP3** |
| VINTO-P1-31 | v1 | **v2** | 9 (idénticos a v1) | **solo MP3** |

Se verificó que v4 de P1-01 y v2 de P1-05 / P1-31 **no existen** ni en el repositorio ni en producción (consulta de solo lectura, §8). El bundle (`backend/seed_data`, `manifest.json` con `form_fields` 472 → **469**) las incluye como últimas versiones; las anteriores solo existen ya en la base. **Sin migraciones.**

## 5. Disponibilidad MP1 / MP3 (obs. 20)
| Máquina | P1-05 | P1-31 | P1-01 | P1-02 | P1-04 | P1-06 / P1-03 |
|---|---|---|---|---|---|---|
| MP1 | **no disponible** (nuevas capturas) | **no disponible** | sin cambios | sin cambios | sin cambios | sin cambios |
| MP3 | disponible | disponible | sin cambios | sin cambios | sin cambios | sin cambios |

Se usa el mecanismo existente de **publicación y vínculos de máquina**, sin lógica visual aislada. Hay tres niveles distintos (verificados en el código y con pruebas):

| Nivel | Cómo se decide | Efecto |
|---|---|---|
| **Tarjetas** | `GET /api/production/machines` devuelve, por máquina, la **versión publicada más alta** de cada formulario **si está vinculada a esa máquina**; la interfaz solo dibuja lo que el backend informa (no hay lista estática de máquinas). | MP1 deja de ver las tarjetas de P1-05 y P1-31. |
| **Acceso directo a la API** | `POST /api/captures` usa la misma regla (`published_form_version`). | En MP1 responde **409 `FORM_NOT_AVAILABLE`** y no deja filas. El bloqueo es real, no solo visual. |
| **Permisos** | Concesión por **sector** (`BOBINAS`) y permiso de captura; **no hay permiso por formulario**. | **No se modifican**: revocarlos afectaría a todo Bobinas. |

**No se puede borrar el vínculo MP1 de la versión 1:** una definición publicada es inmutable (disparador `guard_form_child`). Por eso se publica la versión 2.

**Lectura de lo histórico.** El listado y la lectura por id de capturas filtran por la versión **de cada captura**, no por el vínculo actual: las capturas anteriores de MP1 (v1) siguen accesibles, y el reintento idempotente de una captura ya guardada sigue respondiendo 200. El historial de P1-05 y P1-31 sigue disponible en la interfaz porque MP3 las publica.

## 6. Compatibilidad histórica
- Las versiones anteriores (P1-01 v1 a v3, P1-05 v1, P1-31 v1) quedan **publicadas e inmutables**; cada captura conserva su `form_version_id`.
- Los campos retirados de P1-01 pasan a la lista `legacy` (8 nuevos; 19 en total con los 11 de MF-09): se leen, nunca se digitan ni se envían, y el historial los muestra como **«(versión anterior)»**.
- Los campos obligatorios nuevos (`boquillas_quimicos`, `velocidad_pope`) llevan `sinceVersion: 4`: las capturas v1 a v3 se leen sin exigirlos. Las opcionales no se exigen en ninguna versión.
- **No se trasladan valores entre claves** y no se inventan datos para capturas anteriores (una prueba lo comprueba en el historial: el valor de «Vacío pope (versión anterior)» no aparece en «Velocidad pope»).
- Una captura nueva (v4) que envíe una clave retirada recibe **422** (campo desconocido), y una v3 que envíe una clave nueva también.

## 7. Pruebas y resultados
| Suite | Resultado |
|---|---|
| Backend nuevo `backend/tests/test_mf12a_p101_availability.py` (PostgreSQL efímero, formularios reales del bundle; 19 pruebas) | **OK** |
| Frontend nuevo `scripts/mf12a-p101-availability.test.mjs` (8 pruebas) | **OK** |
| Backend: cada módulo `test_*.py` por separado (§7.1) | ver §7.1 |
| Frontend suite completa (`node --test scripts/*.test.mjs`) | ver §7.2 |
| `tsc --noEmit` / ESLint (archivos modificados y nuevos) | sin errores |

Cubierto por las pruebas nuevas:
- **P1-01:** los tres campos nuevos presentes en MP1 y MP3; captura con valores de Release y Coating (texto tal como se digitó, sin conversión); captura válida sin los tres opcionales (vacíos y nulos no se guardan); los cuatro rojos y `vacio_prensa` / `vacio_fieltro` rechazados en v4; las dos claves azules nuevas obligatorias, con el tipo del campo que sustituyen; sin duplicados de `velocidad_secador` / `velocidad_fieltro`; capturas v1 a v3 legibles, con sus valores en las claves antiguas y sin las nuevas.
- **P1-05 / P1-31:** la oferta de MP1 pierde solo esas dos fichas (y la de MP3 conserva las seis); toda otra máquina conserva exactamente la oferta del bundle; nuevas capturas rechazadas en MP1 (409) y aceptadas en MP3; capturas v1 de MP1 legibles, listadas y con reintento idempotente; P1-01, P1-02 y P1-04 siguen operando en MP1.
- **Importación:** escenario de producción (versiones anteriores ya instaladas) con dry-run y apply, versiones anteriores y demás formularios idénticos, y segunda importación idempotente.

Pruebas existentes adaptadas (cambia la versión o el número de campos de P1-01, el bundle pasa de 472 a 469 campos y MP1 deja de ofrecer P1-05 y P1-31):
- Frontend: `p1-02-p1-01-capture`, `mf09-bobinas-forms`, `mf09a-p1-01-titulo` y `mf11-calidad-conversion`.
- Backend (conteos y versiones): `test_seed_bundle`, `test_bundle_validation` (huella del bundle), `test_import_reference`, `test_mf07`, `test_mf08` y `test_mf11`.
- Backend (oferta de MP1): `test_production_access`, `test_devb1_p105_p131`, `test_devb2_p104`, `test_devb3_p102_p101`, `test_devq1_p122_p126`, `test_devq2_p118_p121`; `test_candidate_forms_qa` captura P1-05 en MP3.
- Backend (estado histórico de P1-01): `test_mf05` y `test_mf09` reproducen el estado de producción entre MF-05/MF-09 y MF-12A con una copia fiel de la definición v3 (`backend/tests/mf12a_p101_v3.json`) en lugar del bundle vigente.

### 7.1 Backend
Se ejecutó cada módulo `backend/tests/test_*.py` por separado en el contenedor `vinto-test-py` (`cd backend/tests && python -B -m unittest <módulo>`, PostgreSQL local de pruebas): **59 módulos**.

- Primera pasada (antes de adaptar las pruebas heredadas): 12 módulos fallaban **por el cambio intencional** de esta entrega (la oferta de MP1, las versiones del bundle y los 73 → 70 campos), no por regresiones.
- Tras adaptarlos, **todos los módulos pasan** salvo dos que fallan **exactamente igual en `main`** (verificado ejecutándolos con los cambios en espera): `test_db_guard` (3 fallos) y `test_capture_count_authorization` (1 fallo); son del entorno local de pruebas y no tienen relación con MF-12A.
- `test_mf12a_p101_availability` (nuevo): 19 pruebas OK. `test_import_reference`, `test_seed_bundle`, `test_bundle_validation`: OK con 469 campos y 1931 registros.

### 7.2 Frontend
`node --test scripts/*.test.mjs`: **781 pruebas, 759 OK y 22 fallos**, con **los mismos nombres** que en `main` (verificado ejecutando la suite sobre `origin/main`: 773 pruebas, 751 OK, 22 fallos; son preexistentes, por ejemplo los «alcance: …» que buscan políticas vacías). Las 8 pruebas nuevas pasan y ninguna prueba existente falla por MF-12A.

## 8. Preflight y capturas históricas (consulta de solo lectura en producción)
Consulta realizada con una transacción `READ ONLY` (con `ROLLBACK`) sobre `vinto_piloto`; no se modificó nada.

| Formulario | Versión | Máquina | Capturas |
|---|---|---|---|
| P1-01 | v1 | MP3 | 1 |
| P1-01 | v3 | MP1 | 1 |
| P1-01 | v3 | MP3 | 1 |
| P1-05 | v1 | **MP1** | **1** |
| P1-31 | v1 | **MP1** | **1** |

- Las **tres** capturas de P1-01 tienen valor en los **ocho** campos de la observación 14 (y en `dosificacion_release`): con v4 se conservan en el historial como «versión anterior».
- Las dos capturas de P1-05 y P1-31 en MP1 siguen siendo legibles después del cambio; no hay capturas de estos formularios en MP3.
- Versiones publicadas en producción: P1-01 v1, v2, v3 (2 vínculos cada una); P1-05 v1 y P1-31 v1 (2 vínculos). No existen P1-01 v4 ni P1-05 / P1-31 v2.
- Sin discrepancias con lo esperado.

## 9. Dry-run esperado (importación simulada)
Sobre una base efímera con el estado de producción previo a MF-12A (todo el bundle vigente con P1-01 v3, P1-05 v1 y P1-31 v1) el importador informa exactamente:

| Concepto | Crear |
|---|---|
| `form_version` | **3** |
| `field` | **89** (70 + 10 + 9) |
| `form_version_machine` | **4** (P1-01: MP1 y MP3; P1-05: MP3; P1-31: MP3) |
| `field_group` / `option` | **0 / 0** |
| Conflictos | **0** |

Coincide con la estimación previa (3 versiones, ≈ 89 campos, 4 vínculos). Total de registros del bundle en una base vacía: 1931 (antes 1936: −3 campos y −2 vínculos). Sin migraciones. Las cifras reales de producción deben contrastarse con un dry-run nuevo antes de aplicar.

## 10. Riesgos
| Riesgo | Medida |
|---|---|
| Entre la importación y la activación, el frontend antiguo envía el payload v3 de P1-01 (ya rechazado por v4: faltan las dos claves azules nuevas y viajan las retiradas). | Mismo patrón que MF-05 / MF-09: importar y activar de inmediato; avisar a QA. No hay capturas pendientes de P1-01 en producción al momento del preflight. |
| En MP1, el frontend antiguo seguiría mostrando las tarjetas de P1-05 / P1-31 hasta la activación (el POST ya respondería 409). | Misma ventana; efecto limitado (una captura histórica en MP1). |
| «Velocidad pope» sin unidad declarada. | No se asume una unidad; queda para confirmación funcional. |
| Reinterpretar valores históricos. | Claves nuevas, sin traslado de valores (D2). |
| Duplicar conceptos de velocidad. | `vacio_prensa` y `vacio_fieltro` se retiran en lugar de renombrarse; prueba de unicidad. |
| Dejar MP1 sin una ficha que aún se necesite. | Cambio acotado por D10; reversible retirando la v2 (requiere autorización expresa). |

## 11. Exclusiones
No se modifican: obs. 5 (nombres y orden de secciones; falta el registro oficial en papel), obs. 11 (campos de tanques T-30/T-31/T-32), obs. 17 (P1-04) ni obs. 44 (P1-16); disponibilidad de P1-01 y P1-02; permisos generales del sector Bobinas; otras máquinas y formularios; el código del backend (sin cambios); migraciones; TVC/ETL (`vinto-web`, `postgres-vinto`); Monday; los Excel.

## 12. Procedimiento de despliegue propuesto (NO ejecutado)
Solo con autorización expresa, como en MF-05 a MF-11: preflight (versión activa, servicios, borradores, capturas, sin despliegues concurrentes); respaldo `backup.sh create-and-verify` con restauración aislada; artefacto de frontend desde el SHA del merge, con checksum y arranque aislado; instalación sin activar; **dry-run** esperando exactamente las cifras del §9 (si difiere, detenerse); importación aditiva como usuario `vinto-mvp`; activación con `deploy/mvp` inmediatamente después; healthcheck; verificación de las tres versiones publicadas y de sus vínculos (P1-05 y P1-31 solo MP3), de las capturas históricas intactas, de la oferta por máquina y de que `vinto-web`/TVC/ETL no se tocaron. Rollback de código con el procedimiento oficial; retirar las versiones nuevas o restaurar datos requiere autorización expresa.

## 13. Guía de QA manual (después del despliegue)
1. **Obs. 9** (QA.OPERACION, MP1 y MP3): abrir P1-01. En «Químicos», tras «Dosificación Release *» aparecen «Frecuencia Release», «Dosificación Coating» y «Frecuencia Coating», **sin asterisco**. Registrar con los tres, con solo uno y con ninguno: los tres casos se guardan. Escribir texto como «50 Hz» o «cada 2 h»: se guarda tal cual.
2. **Obs. 14:** en «Prensa, aceite, vacío y filtros» ya no aparecen «Apertura purga prensa», «Presión aceite guía tela», «Presión aceite lubricación», «Vacío tela», «Vacío prensa» ni «Vacío fieltro»; aparecen «Boquillas químicos *» (texto) y «Velocidad pope *» (decimal). «Velocidad secador» y «Velocidad fieltro» existen **una sola vez** (sección «Secador…»). Enviar sin «Boquillas químicos» o sin «Velocidad pope»: se rechaza.
3. **Historial de P1-01:** las capturas anteriores muestran los valores de los campos retirados con la marca «(versión anterior)» y **sin valor** en «Boquillas químicos», «Velocidad pope» ni en las tres columnas nuevas; las capturas v4 muestran lo contrario.
4. **Obs. 20 en MP1:** en Bobinas con MP1 **no** aparecen las tarjetas «Registro de tubetes» (P1-05) ni «Consumo de químicos» (P1-31); sí P1-01, P1-02, P1-04, P1-06 y la producción de bobinas (P1-03).
5. **Obs. 20 en MP3:** aparecen las mismas fichas que antes, incluidas P1-05 y P1-31; registrar una de cada una.
6. **Historial de P1-05 y P1-31:** siguen visibles los registros anteriores hechos en MP1.
7. Confirmar que P1-01 y P1-02 siguen disponibles en MP1 y MP3 y que no cambiaron otros formularios ni máquinas.

# Piloto funcional aislado de Bobinas MP1/MP3: brechas y checklist GO / NO GO

**Estado: documento de diagnóstico. No implementa nada, no aprueba nada y no fija fechas.** No cambia código, migraciones, `backend/seed_data`, sectores, políticas, permisos, concesiones ni maestros; no accede a DEV ni PROD; no modifica los documentos M5-B0 ni M7-A.
**Base auditada:** `main` en `416f877846c000935aa995e519960b98e6f45916` (merge del PR #34, M7-A cerrado; 36 decisiones `CV:` y 47 `RB:` siguen **Pendiente**).
**Método:** lectura de código, migraciones, bundle de referencia, documentación y pruebas. **No se ejecutó ninguna prueba** en esta auditoría: los conteos de pruebas son conteos de definiciones (`def test_` / `test(`) y no son resultados de ejecución ni criterio de completitud.

## 1. Resumen ejecutivo

1. **El flujo productivo de Bobinas está técnicamente completo de punta a punta hasta la captura:** OT → publicación → asignación → captura F3 (bobina numerada) y P1-06 → PostgreSQL → capturas de Calidad P1-19 / P1-20, con idempotencia, turno y fecha operativa resueltos por el backend y auditoría por triggers.
2. **Hay un bloqueo funcional sin discusión: no existe forma de liberar ni rechazar una bobina.** `vinto_txn.quality_release` nace en `pending` (`backend/app/bobbins/service.py:144-185`) y ningún código la modifica: el router de Calidad solo expone `GET /bobbins`, `POST/GET` de capturas y `GET /captures/{id}` (`backend/app/quality/router.py:27-62`), y su cabecera lo declara («Nada de esto libera ni rechaza»). El permiso `quality.release` ya está asignado a CALIDAD (`backend/app/auth/permissions.py:19,39`) pero **ningún endpoint lo exige**.
3. **Aun con el servicio hecho, el criterio de liberación es una decisión industrial de VINTO** que hoy no está en el repositorio (qué mediciones se exigen, qué límites, quién decide, si se puede revertir, qué efecto tiene). No debe implementarse suponiéndola.
4. **No existe una matriz de decisiones de homologación para Bobinas** (M5-B0 es de Rebobinado, M7-A de Conversión). El contrato de F3, P1-06, P1-19 y P1-20, los maestros MP1/MP3 y los turnos de Bobinas no tienen registro de aprobación identificable en el repositorio, y P1-20 declara unidades provisionales. Esto, y no el código, es el segundo bloqueo.
5. **Faltan además piezas de entrega:** ninguna prueba E2E de navegador para Bobinas ni Calidad, ningún procedimiento de despliegue/restauración del entorno aislado, ningún plan de UAT, reportes sin servicio central y sin definición de offline para captura central.
6. **Distinción obligatoria:** completar el piloto (Entrega A) **no** completa el MVP integral de 25 formularios (Entrega B).

## 2. Convenciones de la matriz

- **Estado:** `implementado` (existe y tiene cobertura de pruebas definida), `parcial`, `pendiente` (no existe), `no verificado` (no se pudo comprobar con lo inspeccionado; no equivale a «faltante»).
- **Severidad:** `B` = bloqueante del piloto; `A` = alta (el piloto es posible pero con riesgo operativo o de datos que debe aceptarse expresamente); `M` = media; `Mejora` = opcional, no bloquea.
- **Tipo de dependencia de VINTO:** `D` = decisión/aprobación de VINTO; `E` = evidencia o documento a aportar; `—` = ninguna.
- «Evidencia» cita ruta y, cuando es posible, línea. Una prueba que existe **no** acredita aprobación industrial (criterio de M5-B0 acta §2).

## 3. Matriz de brechas

### A. Flujo productivo de Bobinas

| ID | Funcionalidad | Estado | Evidencia | Impacto en el piloto | Sev. | Dependencia técnica | Dependencia VINTO | Criterio de aceptación verificable | Incremento |
|---|---|---|---|---|---|---|---|---|---|
| PB-A1 | Creación y publicación de OT base (Bobinas) | implementado | `backend/app/work_orders/router.py:30-62` (crear, listar, añadir línea, publicar); `service.py`; pruebas `test_work_orders_*.py`, `scripts/orders.test.mjs` | El flujo parte de aquí | — | — | **D**: numeración de OT provisional (`service.py:14` indica que podrá reemplazarse si Expertus es autoridad); ver PB-C9 | JEFATURA crea y publica una OT con líneas de MP1/MP3 en el entorno aislado; la línea base publicada es inmutable | — |
| PB-A2 | Asignación por Supervisión (activar/terminar, una activa por máquina) | implementado | `backend/app/assignments/router.py:33-61`; lock de máquina `assignments/service.py:102`; `test_assignments_*.py` | Contexto de toda captura | — | — | — | SUPERVISION activa una asignación; una segunda activa en la misma máquina es rechazada; terminar es idempotente | — |
| PB-A3 | Captura F3: bobina numerada | implementado, contrato sin aprobación documentada | `backend/app/bobbins/router.py:25-36`; `service.py:148-186` (una transacción: captura + detalles + bobina + `quality_release` pending); correlativo por máquina y gestión (migración 0004); `test_f3_bobbin_service.py`, `test_f3_bobbins_api.py`, `scripts/bobbins.test.mjs` | Núcleo del piloto | A | Ver PB-C3 | **D/E**: aprobar los 6 campos manuales, numeración por máquina y gestión (01/04 a 31/03), `numero_de_cortes` como texto, hora inicio/fin manuales y gramaje heredado del nombre `G-<n>` | Capturas F3 de MP1 y MP3 generan correlativos independientes, un reintento idéntico devuelve la misma bobina y un contenido distinto da 409; el contrato firmado coincide con el publicado | Homologación de Bobinas (PB-H) |
| PB-A4 | Captura P1-06 (F6) | implementado, contrato sin aprobación documentada | `backend/app/capture_service.py:39` (`CENTRAL_FORM_CODES = {P1-06}`); `captures.py:76-96`; `test_f6_*.py` | Producción complementaria | A | — | **D/E**: igual que PB-A3 | Una captura P1-06 queda en `capture` revisión 1 con valores tipados; la versión publicada exige área `production` y vínculo con la máquina | PB-H |
| PB-A5 | Seguimiento e historial | parcial | Contador central de capturas (`captures.py:56`, README «Integración local de Seguimiento»); lista central F6 en `app/page.tsx:252`; **Seguimiento de Bobinas sigue pasando el estado demo `releases`** con una liberación ficticia (`app/page.tsx:211`, bobina `BM-2609-001`, y componente `Tracking`, `app/page.tsx:448`) | El supervisor puede ver datos demo mezclados con los reales; el estado de Calidad no se resume en Seguimiento (`app/page.tsx:448`: «todavía no resume liberaciones de Calidad») | A | Depende de PB-B4 para mostrar liberaciones reales | **D**: qué debe ver cada rol en Seguimiento | En Seguimiento de Bobinas no aparece ningún dato fijo ni local mezclado con el central; se muestran bobinas de F3 con su estado de Calidad real; un recuento coincide con la base | Tras PB-B4; la retirada del dato demo es un cambio previo y de bajo riesgo |
| PB-A6 | Persistencia, validación e idempotencia | implementado | Transacción única, `lock(capture_id)`, `CAPTURE_IDEMPOTENCY_CONFLICT`, validación de tipos/obligatorios (`capture_service.py:237-330`); triggers de inmutabilidad (0001/0003) | Integridad de datos | — | — | — | Suite backend completa verde en base efímera `*_test` | — |
| PB-A7 | Turno y fecha operativa | implementado, **datos de turno provisionales** | `backend/app/shifts.py` (resolución por zona horaria, cruce de medianoche, vigencia sobre fecha operativa); `seed_data/shifts.json` (`valid_from` 2026-01-01 provisional, `America/La_Paz`, nota «la vigencia funcional real debe recibirse antes de producción»); `test_shifts.py` | Toda captura depende del turno; un horario erróneo asigna mal el turno | A | — | **E/D**: horarios y vigencias oficiales de Bobinas (comparte tema con `RB:H1-05` a `H1-09`) | Para instantes frontera (inicio, fin, cruce de medianoche) el turno y la fecha operativa coinciden con el reglamento firmado por VINTO | PB-H |
| PB-A8 | Corrección de capturas enviadas | parcial (solo base de datos) | La base exige motivo auditado para cambiar una captura cerrada (`0001` línea ~1007, `0003`); **no existe endpoint ni pantalla de corrección** (los routers de capturas solo tienen POST de creación y GET) | Un error de captura en el piloto no se puede corregir por la aplicación | A | Depende de PB-A9 | **D**: ¿quién puede corregir, hasta cuándo, con qué aprobación? | Existe un camino de corrección con motivo, autor y revisión + 1, probado, o VINTO acepta por escrito que durante el piloto no se corrige | Posterior; no inventar la política |
| PB-A9 | Auditoría y trazabilidad | implementado (backend), **sin consulta ni reporte** | Triggers `touch_row` y `record_change`, tabla `vinto_audit.audit_event` con actor, `request_id`, razón, datos previos y nuevos (0001 líneas 882-925); contexto de auditoría en cada servicio | Hay trazabilidad en base; nadie puede consultarla desde la aplicación | M | — | **D**: si VINTO exige poder consultarla durante el piloto | Para una captura, una bobina y una concesión se puede reconstruir quién, cuándo y por qué mediante consulta documentada | Mejora: vista de auditoría de solo lectura |

### B. Calidad

| ID | Funcionalidad | Estado | Evidencia | Impacto | Sev. | Dep. técnica | Dep. VINTO | Criterio de aceptación | Incremento |
|---|---|---|---|---|---|---|---|---|---|
| PB-B1 | P1-19 Humedad (captura) | implementado | `backend/app/quality/capture_service.py:152-181`; `seed_data/forms/VINTO-P1-19.json` (área `quality`, 7 campos manuales, humedad derivada recalculada); `test_quality_capture_api.py`, `scripts/quality-humidity-capture.test.mjs` | Medición disponible | — | — | **D/E**: contrato sin aprobación documentada | Una medición se liga a la bobina, sin tocar `quality_release`, con retry idempotente | PB-H |
| PB-B2 | P1-20 Propiedades físicas (captura) | implementado, **contrato provisional** | Mismo servicio; `seed_data/forms/VINTO-P1-20.json` (12 campos); advertencia `P1_20_PROVISIONAL_CONTRACT` en `manifest.json` (unidades provisionales, gramaje medido sin unidad de catálogo); `scripts/quality-physical-capture.test.mjs` | Las unidades pueden cambiar | A | — | **D/E**: unidades, etiquetas y obligatoriedad aprobadas | Contrato aprobado igual al publicado | PB-H |
| PB-B3 | Bandeja e historial de bobinas | implementado (solo lectura) | `backend/app/quality/router.py:27`; `quality/service.py:55-89`; `scripts/quality-bobbin-inbox.test.mjs`, `quality-bobbin-history.test.mjs` | Calidad ve bobinas por estado | — | — | — | La bandeja `pending` coincide con las filas `quality_release.status='pending'`; independiente de la asignación | — |
| **PB-B4** | **Servicio de liberación y rechazo de bobinas** | **pendiente** | Infraestructura existente: tabla con `status IN (pending, released, rejected)`, `decided_by`, `decided_at`, `decision_reason` y CHECK que impide estados inconsistentes (`0001_initial_schema.sql:291-294`); permiso `quality.release` en CALIDAD (`permissions.py:19,39`); filtro de bandeja por `released`/`rejected` (`quality/router.py:28`). **Faltan:** endpoint, transición, bloqueo concurrente, idempotencia, auditoría con motivo, pantalla, pruebas | Sin esto ninguna bobina sale de `pending`: el piloto no puede demostrar el objetivo de Calidad | **B** | PB-B5 resuelto; reutiliza triggers de auditoría | **D**: política de PB-B5 | Una bobina pasa de `pending` a `released` o `rejected` solo por CALIDAD con `quality.release` y sector concedido; guarda quién, cuándo y motivo; un segundo intento idéntico es idempotente y uno contrario es 409; las demás capturas no se alteran; la bandeja refleja el nuevo estado; todo queda en `audit_event` | **Incremento Q-LIB** (después de PB-B5) |
| **PB-B5** | **Política de liberación** (criterio industrial) | pendiente, **no se encontró en el repositorio** | Búsqueda en documentación, bundle y código: no existe criterio de decisión ni tolerancias | Sin política, el servicio sería una invención | **B** | — | **D**: ver §7 (preguntas Q-1 a Q-8) | Acta o confirmación formal aprobada, con evidencia identificable (M5-B0 acta §2), que fije cada punto de §7 | **Homologación de Calidad** (antes de Q-LIB) |
| PB-B6 | Reversión o reevaluación de una decisión | no verificado | La tabla permite el estado final; **no se verificó** qué transiciones admite la base tras decidir ni existen triggers específicos de `quality_release` | Una decisión errónea podría no poder corregirse | A | PB-B4 | **D**: ¿se puede revertir? ¿quién? ¿con qué motivo? | Según la política: la reversión está prohibida y probada, o permitida con motivo y auditoría | Con Q-LIB |
| PB-B7 | Efecto de la liberación | pendiente de definición | Hoy nada consume bobinas: no hay inventario, consumo ni despacho (M7-A índice §7) | Si la liberación no habilita ni bloquea nada, es solo un estado | M | — | **D**: qué habilita o impide una bobina liberada/rechazada en el piloto | Efecto documentado y comprobado, o declarado «solo informativo» por VINTO | PB-B5 |
| PB-B8 | Seguimiento de Calidad | parcial | El Seguimiento del front Calidad no resume liberaciones (`app/page.tsx:448`) | Falta vista de resultados | M | PB-B4 | **D**: indicadores | Vista con conteos reales de pendientes, liberadas y rechazadas por máquina y fecha | Con Q-LIB (frontend) |

### C. Requisitos transversales

| ID | Funcionalidad | Estado | Evidencia | Impacto | Sev. | Dep. técnica | Dep. VINTO | Criterio de aceptación | Incremento |
|---|---|---|---|---|---|---|---|---|---|
| PB-C1 | Seguridad y sesiones | implementado en local; **no verificado en entorno real** | Cookie `HttpOnly`, `SameSite=Lax`, `Secure` salvo `APP_ENV=local` (`auth/router.py:24-25`); sesiones de servidor con token opaco (`auth/sessions.py`); CORS con orígenes explícitos (`main.py:24-26`, `config.py:19`); `test_auth_*.py` | `Secure` solo se comprueba con HTTPS | A | Entorno aislado con HTTPS | **D**: política de contraseñas y bloqueo, si VINTO la exige | En el entorno aislado: cookie `Secure` activa, orígenes correctos, logout y expiración probados; sin credenciales en repositorio ni logs | PB-ENV |
| PB-C2 | Perfiles, permisos y concesiones por sector | implementado | `auth/permissions.py` (JEFATURA gestiona OT, SUPERVISION asigna, OPERACION captura producción, CALIDAD captura y libera, DATA_BALTREK administra sin permisos de planta); `auth/grants.py`; API y UI de administración (PR #19, #20); `test_sector_*.py`, `test_admin_sector_api.py` | Los perfiles existen; **faltan los usuarios reales del piloto** | A | — | **D/E**: lista nominal de usuarios, perfil y sector; confirmar que la separación de funciones coincide con la organización | Cada usuario de la lista accede solo a lo permitido y recibe 403 en lo contrario (matriz perfil × acción probada en el entorno aislado) | PB-ENV / UAT |
| PB-C3 | Catálogos y maestros de Bobinas | implementado como **candidato** | `seed_data/manifest.json`: 2 máquinas (MP1, MP3), 93 artículos, 91 también materiales, 2 sin clase de material, 1 sin gramaje, **0 con peso nominal**, 30 campos de formulario; advertencias `MACHINE_NAME_FROM_CODE` (el nombre de máquina repite el código), turnos con vigencia provisional | Datos sin aprobación; no se promueve a DEV | A | — | **E/D**: lista oficial de máquinas y artículos con nombres, unidades y vigencias, y confirmar si el peso nominal es obligatorio | Bundle regenerado con las fuentes aprobadas, SHA-256 registrado, ensayo de importación en base `*_test` sin diferencias respecto a la lista oficial | M7-B parcial para Bobinas |
| PB-C4 | Reportes | **pendiente** | `REPORT_DEFINITIONS` (`lib/vinto/form-definitions.ts:8888-8908`) define **4** reportes por nombre y descripción (productos rebobinados, bobinas por camión, consolidado PH y consolidado de servilletas; el README dice 3); en la UI solo figuran como tarjetas y los únicos archivos son descargas CSV de registros locales (`app/page.tsx:448`); no hay endpoint central de reportes | **No se verificó** cuáles son obligatorios para Bobinas; «Bobinas por camión» es el candidato evidente pero requiere un dato (camión) que ningún formulario central de Bobinas captura | A | Definir fuente de datos | **D/E**: reportes exigidos en el piloto y su formato; si «camión» entra | Para cada reporte exigido: salida generada desde datos centrales, cuadrada contra la base en una muestra y aprobada por VINTO | Posterior; depende de la decisión |
| PB-C5 | Operación sin conexión | pendiente para captura central | F3, P1-19 y P1-20 exigen conexión (`lib/vinto/bobbins.ts:233`, `quality-captures.ts:210`); la propuesta original contemplaba cola offline | Si la planta no tiene conectividad estable, la captura se detiene | A | Diseño de cola local si se requiere | **D**: si el piloto exige offline y con qué garantías | VINTO declara por escrito que el piloto opera con conexión, o existe cola probada sin pérdida ni duplicados | Decisión previa; cola solo si se exige |
| PB-C6 | Pruebas backend, Node y E2E | parcial | Backend: definiciones de prueba (aprox.) F3 52, F6 66, Calidad 61, revisión 26, asignaciones 65, OT 57, turnos 38; Node: `bobbins` 45, `quality-*` 133, `orders` 21; **ninguna E2E de navegador para F3, P1-06, P1-19, P1-20 ni para el flujo OT → asignación → captura → Calidad** (`scripts/e2e/` solo cubre Rebobinado y Conversión) | El circuito completo nunca se ha probado como un usuario | A | Servidor de pruebas y fixtures como los de M6 | — | Un E2E con base `*_test` recorre OT → publicación → asignación → F3 → P1-19 → P1-20 → liberación y verifica el estado en base | Incremento E2E-B (tras PB-B4) |
| PB-C7 | Entorno aislado, despliegue y restauración | **pendiente** | Solo existe `docker-compose.yml` local (`127.0.0.1`); sin CI (no hay `.github/workflows`); `backups/` contiene volcados manuales previos a F3; **no hay procedimiento documentado de despliegue, respaldo programado ni restauración validada** para un entorno de piloto | Sin entorno ni recuperación no hay piloto «aislado» | B | Definir infraestructura | **D**: dónde se aloja y quién lo opera | Entorno separado de DEV y PROD, migraciones aplicadas con `migrate.py --check`, respaldo restaurado y validado con recuento de filas | Incremento PB-ENV |
| PB-C8 | QA manual y UAT | **pendiente** | No existe plan de pruebas ni acta de UAT en el repositorio | Sin UAT no hay aceptación | B | PB-B4, PB-ENV | **D**: participantes y criterios de aceptación | Guion de UAT con casos por rol, ejecutado con datos aprobados y firmado | Incremento UAT |
| PB-C9 | Integración con Expertus | **no verificado** | El README indica «Expertus queda como integración futura» y «sin escritura a Expertus»; la numeración de OT es provisional (`work_orders/service.py:14`) | Si VINTO exige importar OT o publicar resultados al piloto, hoy no es posible | M | Depende del alcance | **D**: si el piloto requiere integración | VINTO confirma por escrito que el piloto no integra Expertus, o se define la integración | Decisión previa |
| PB-C10 | Datos de ejemplo en la UI | **parcial**: dato demo visible | Estado inicial con una bobina ficticia `BM-2609-001` en `app/page.tsx:211`, usado por `Tracking` y `ReleaseCards`; la métrica «Bobinas liberadas» cuenta ese estado local | Riesgo de que un usuario lea un dato ficticio como real | M | — | — | Ninguna pantalla del piloto muestra datos que no vengan del backend | Cambio menor previo al piloto |

## 4. Bloqueos reales frente a mejoras opcionales

**Bloqueos reales (NO GO mientras estén abiertos):**
1. **PB-B5** política de liberación de Calidad (VINTO).
2. **PB-B4** servicio de liberación y rechazo (técnico, depende de PB-B5).
3. **PB-H** homologación de los contratos y maestros de Bobinas: F3, P1-06, P1-19, P1-20 (incluye unidades de P1-20), maestros MP1/MP3, turnos (PB-A3, PB-A4, PB-A7, PB-B1, PB-B2, PB-C3).
4. **PB-C7** entorno aislado con respaldo restaurado y validado.
5. **PB-C8** UAT y aprobación expresa de VINTO.

**Riesgos que el piloto solo puede asumir con aceptación escrita de VINTO:** PB-A8 (corrección), PB-C1 (seguridad en entorno real), PB-C2 (usuarios reales), PB-C4 (reportes), PB-C5 (offline), PB-C6 (E2E), PB-A5/PB-C10 (datos demo en pantalla).

**Mejoras opcionales (no bloquean):** PB-A9 (consulta de auditoría), PB-B8 (indicadores de Calidad), PB-C9 si VINTO confirma que no hay integración.

## 5. Dos niveles de entrega

### Entrega A: piloto funcional aislado de Bobinas MP1/MP3
Mínimo verificable: en un entorno separado de DEV y PROD, usuarios autorizados nominalmente ejecutan con datos aprobados el flujo OT → publicación → asignación → F3 (y P1-06) → P1-19 / P1-20 → liberación o rechazo → Seguimiento, con evidencia de trazabilidad, recuperación de datos probada y UAT firmado. Requiere cerrar PB-B4, PB-B5, PB-H, PB-C7 y PB-C8, y que cada riesgo de §4 esté cerrado o aceptado por escrito.

### Entrega B: MVP integral VINTO (referencia)
Conserva el alcance original: 25 formularios y 602 campos activos, 3 reportes (el repositorio define 4, ver PB-C4), Rebobinado y Conversión homologados (47 + 36 decisiones pendientes), formularios restantes, integraciones, offline, QA integral, despliegue y aceptación. Hoy el bundle de referencia exporta **4 formularios** (`manifest.json`: 30 campos) y 21 definiciones quedan fuera de alcance.

**Piezas compartidas** (se avanzan una vez y sirven a ambas entregas): modelo de turnos, maestros y vigencias, mecanismo de liberación y trazabilidad de bobinas, entorno y procedimientos de respaldo, plantilla de UAT, estrategia de E2E, política de correcciones, decisión de offline. **Completar A no completa B ni sustituye el acuerdo formal sobre el alcance.**

## 6. Secuencia propuesta de incrementos

Criterios de orden: dependencias, riesgo operativo, esfuerzo técnico, necesidad de homologación y valor para una entrega intermedia verificable. **El esfuerzo se expresa en orden de magnitud relativa (S/M/L) y no en días; no se emiten porcentajes de avance** porque no existe un denominador acordado con VINTO. Cualquier porcentaje futuro será una valoración técnica de planificación y no una aceptación contractual.

| Orden | Incremento | Tipo | Esfuerzo | Requiere de VINTO | Autorización necesaria |
|---|---|---|---|---|---|
| 1 | **PB-H0**: paquete de homologación de Bobinas (matriz de decisiones, agenda y registro, mismo formato que M5-B0/M7-A) y preguntas de Calidad §7 | Documental | S | Convocar las sesiones | Sí (nuevo incremento documental) |
| 2 | **PB-CLEAN**: retirar el dato demo de Seguimiento (PB-A5/PB-C10) | Técnico menor | S | — | Sí |
| 3 | **Homologación de Bobinas y Calidad** (respuestas con evidencia) | Externo | — | Responder y aprobar | No aplica a código |
| 4 | **Q-LIB**: servicio y UI de liberación/rechazo con pruebas backend, Node y E2E | Técnico | M | Política aprobada | Sí |
| 5 | **E2E-B**: E2E de navegador del flujo completo | Técnico | M | — | Sí |
| 6 | **PB-ENV**: entorno aislado, migraciones, respaldo y restauración documentados y probados | Infra | M | Dónde alojar y quién opera | Sí |
| 7 | **PB-MAESTROS**: bundle Bobinas con fuentes aprobadas e importación en `*_test` (equivale a un M7-B acotado a Bobinas) | Técnico | S–M | Listas oficiales aprobadas | Sí |
| 8 | **UAT**: guion, ejecución, acta | Mixto | M | Participantes y firma | Sí |
| 9 | Decisiones sobre PB-A8, PB-C4, PB-C5 y PB-C9 (corrección, reportes, offline, Expertus) y su implementación si se exigen | Mixto | S a L cada una | Decidir | Sí, caso por caso |

**Camino crítico del piloto:** PB-H0 → homologación de Calidad → Q-LIB → E2E-B → PB-ENV/PB-MAESTROS → UAT → aprobación expresa. Los pasos 2, 5 (parcialmente) y 6 pueden avanzar en paralelo sin decisiones industriales nuevas; el 4 y el 7 no.

## 7. Preguntas y decisiones que VINTO debe resolver

**Calidad (decisión de liberación; ninguna tiene respuesta en el repositorio):**
- **Q-1** ¿Qué mediciones son obligatorias para liberar una bobina: P1-19, P1-20 o ambas? ¿Cuántas y con qué frecuencia?
- **Q-2** ¿Cuáles son los límites o tolerancias de aceptación por magnitud y por artículo?
- **Q-3** ¿Quién decide (perfil y persona) y puede decidir quien midió?
- **Q-4** ¿Es obligatorio el motivo en la liberación, en el rechazo o en ambos?
- **Q-5** ¿Una decisión puede revertirse o reevaluarse, quién puede y con qué motivo?
- **Q-6** ¿Qué efecto tiene la decisión en el piloto (habilita/impide algún paso) o es solo informativa?
- **Q-7** ¿Qué ocurre con una bobina rechazada (destino, registro, nuevo ciclo)?
- **Q-8** ¿Una bobina puede liberarse sin ninguna medición (excepción) y bajo qué condición?

**Bobinas (contratos y maestros):**
- **B-1** Aprobación del contrato de F3, P1-06, P1-19 y P1-20 (campos, tipos, unidades, obligatoriedad) y, en particular, de las unidades provisionales de P1-20.
- **B-2** Lista oficial de máquinas MP1 y MP3 (nombre y código), artículos vinculados, unidades y clases de material, y si el peso nominal es obligatorio.
- **B-3** Horarios y vigencias de los turnos de Bobinas.
- **B-4** Numeración de bobinas: confirmar correlativo por máquina y gestión 01/04 a 31/03 y la inexistencia de prefijos.
- **B-5** Registros históricos o heredados de navegador: qué hacer con ellos (relacionado con CV:C-10).

**Operación y entrega:**
- **O-1** Alcance exacto del piloto (máquinas, turnos, duración, volumen) y quién puede aprobarlo.
- **O-2** Reportes exigidos y su formato (incluido si «bobinas por camión» entra y de dónde sale el dato de camión).
- **O-3** ¿Se exige operación sin conexión? ¿Con qué garantías?
- **O-4** Política de corrección de capturas cerradas.
- **O-5** ¿El piloto requiere Expertus (lectura de OT, escritura de resultados) o no?
- **O-6** Usuarios nominales, perfiles y sectores; responsable de aprobar altas y bajas.
- **O-7** Dónde se aloja el entorno aislado, quién lo opera y quién autoriza el respaldo/restauración.
- **O-8** Participantes, casos y criterio de aprobación del UAT.

## 8. Riesgos identificados

| # | Riesgo | Evidencia | Mitigación propuesta |
|---|---|---|---|
| R1 | Interpretar «Calidad completa» por tener capturas, bandeja e historial | `quality_release` nunca cambia (PB-B4) | Declarar expresamente que capturar ≠ liberar en toda comunicación |
| R2 | Implementar Q-LIB sin política y fijar un criterio por suposición | PB-B5 sin evidencia | Q-LIB solo tras aprobación documentada de Q-1 a Q-8 |
| R3 | Datos candidatos o provisionales tratados como oficiales | Manifest: pesos 0/93, turnos y nombres de máquina provisionales, P1-20 con unidades provisionales | No promover maestros sin evidencia aprobada |
| R4 | Ninguna prueba recorre el circuito completo en navegador | PB-C6 | E2E-B antes del UAT |
| R5 | Sin entorno aislado ni restauración validada no hay marcha atrás | PB-C7 | PB-ENV como condición de GO |
| R6 | Dato demo ficticio visible en Seguimiento | PB-A5/PB-C10 | PB-CLEAN |
| R7 | Confundir piloto con MVP integral y el cumplimiento del alcance contractual | §5 | Acuerdo formal escrito sobre qué sustituye la entrega intermedia |
| R8 | Decidir por defecto «fuera de alcance» offline, reportes o Expertus | PB-C4, PB-C5, PB-C9 | Registrar cada decisión de VINTO por escrito |

## 9. Observaciones verificables sobre la documentación existente
- El README de la raíz habla de **3 reportes**, mientras `REPORT_DEFINITIONS` contiene **4** (`form-definitions.ts:8890-8908`). No se corrige aquí; debe aclararse en la homologación.
- La matriz **M1-B2-c1** (evidencia fuera del repositorio) sigue pendiente: su contenido no cuenta como aprobación hasta aportarse (M5-B0 §1, M7-A índice §11).
- `CENTRAL_FORM_CODES` contiene solo P1-06; F3 tiene su propio endpoint (`/api/bobbins`) y Calidad el suyo. Es coherente con las restricciones, pero significa que la política «qué formularios se aceptan» está repartida en tres lugares y deberá revisarse al ampliar el alcance.

## 10. Checklist GO / NO GO del piloto

Leyenda: **Completo** (hay evidencia verificable), **Pendiente** (no existe o no está aprobado), **No verificado** (no se pudo comprobar). **Estado actual: NO GO.**

| # | Condición | Estado | Detalle |
|---|---|---|---|
| 1 | Alcance del piloto aprobado por VINTO (máquinas, turnos, duración, reportes, offline, Expertus) | Pendiente | O-1 a O-5 |
| 2 | Maestros aplicables confirmados (máquinas, artículos, unidades, turnos, vigencias) | Pendiente | PB-C3, PB-A7: bundle candidato, sin evidencia de aprobación |
| 3 | Contratos de F3, P1-06, P1-19 y P1-20 homologados | Pendiente | PB-H; P1-20 con unidades provisionales |
| 4 | Flujo de producción completo: OT, publicación, asignación, F3, P1-06 | **Completo técnicamente** (sin aprobación industrial) | PB-A1 a PB-A4, PB-A6; no recorrido de punta a punta por E2E de navegador |
| 5 | Política de Calidad aprobada (Q-1 a Q-8) | Pendiente | PB-B5 |
| 6 | Servicio de liberación y rechazo implementado y probado | Pendiente | PB-B4 |
| 7 | Capturas P1-19 y P1-20, bandeja e historial | **Completo técnicamente** (contrato sin aprobar) | PB-B1 a PB-B3 |
| 8 | Roles, permisos y concesiones validados con los usuarios reales del piloto | Pendiente | Mecanismo completo (PB-C2); usuarios reales no definidos |
| 9 | Auditoría y trazabilidad verificadas | Parcial | Registro en base completo (PB-A9); sin consulta ni verificación en el entorno aislado |
| 10 | Seguridad y sesiones verificadas en el entorno real (HTTPS, `Secure`, CORS) | No verificado | PB-C1 |
| 11 | QA técnico: suites backend, Node y E2E satisfactorias en una ejecución nueva | No verificado | Esta auditoría no ejecutó pruebas; sin E2E de navegador para el circuito (PB-C6) |
| 12 | Seguimiento sin datos ficticios y con estado real de Calidad | Pendiente | PB-A5, PB-B8, PB-C10 |
| 13 | Reportes exigidos entregados y cuadrados | Pendiente | PB-C4 (depende de la decisión) |
| 14 | Corrección de capturas definida (implementada o aceptada su ausencia) | Pendiente | PB-A8 |
| 15 | UAT completado y firmado | Pendiente | PB-C8 |
| 16 | Entorno aislado, migraciones verificadas y recuperación (respaldo restaurado y validado) | Pendiente | PB-C7 |
| 17 | Rebobinado y Conversión permanecen deshabilitados; `DEFAULT_OPERATIONAL_SECTORS = (BOBINAS,)` y `CENTRAL_FORM_CODES = {P1-06}` sin cambios | **Completo** (verificado en `sectors.py:28` y `capture_service.py:39` sobre `416f877`) | Debe repetirse antes de cualquier GO |
| 18 | Aprobación expresa de VINTO con persona de autoridad y evidencia identificable | Pendiente | M5-B0 acta §2 |

**Regla de decisión:** el piloto es GO solo cuando los puntos 1 a 3, 5, 6, 8 y 15 a 18 estén **Completo** y cada punto restante esté Completo o con aceptación escrita de VINTO del riesgo correspondiente.

## 11. Límites de esta auditoría
- No se ejecutaron pruebas, migraciones ni conexiones a bases de datos; todos los estados son resultado de lectura.
- Los conteos de pruebas son aproximados (definiciones, no ejecuciones) y no se usan como criterio de completitud.
- «No se encontró» significa que no aparece en lo inspeccionado (código, documentación, bundle y migraciones del repositorio), no que no exista fuera de él.
- No se modificaron los documentos M5-B0 ni M7-A.

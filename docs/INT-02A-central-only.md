# INT-02A · Operación exclusivamente central y contención del circuito legacy

Estado: **técnico, previo a UAT**. No habilita Rebobinado ni Conversión, no activa candidatos, no cambia reglas industriales ni datos de negocio.

Objetivo: eliminar de la interfaz operativa normal la posibilidad de **crear** operaciones o capturas con el circuito legacy del navegador (`localStorage`). Toda captura operativa pasa por las APIs centrales y PostgreSQL. Los datos legacy existentes **no se tocan**.

## 1. Inventario ANTES de INT-02A (`app/page.tsx` en `main` 6fd7131)

### 1.1 Rutas centrales (backend) usadas por la interfaz
| Circuito | Rutas |
|---|---|
| Sesión | `/api/auth/*` (cookie HttpOnly) |
| OT y asignaciones | `/api/work-orders`, `/api/assignments` (activar, activa por máquina) |
| Disponibilidad | `GET /api/production/machines`, `GET /api/quality/machine-forms`, `GET /api/quality/bobbin-forms` |
| Producción por asignación | `POST/GET /api/captures` (P1-06 y fichas candidatas de Bobinas, Rebobinado y Conversión), `GET /api/captures/count` |
| Bobinas (F3) | `POST/GET /api/bobbins` |
| Calidad por bobina | `GET /api/quality/bobbins` (inbox), `POST/GET /api/quality/bobbins/{id}/captures`, `GET /api/quality/captures/{id}` |
| Calidad por máquina | `POST/GET /api/quality/machines/{m}/captures`, `GET /api/quality/machine-captures/{id}` |

### 1.2 Formularios
- **Centrales operativos:** VINTO-P1-06 (política `CENTRAL_FORM_CODES`), F3 / VINTO-P1-03 (ruta propia), VINTO-P1-19 y VINTO-P1-20 (Calidad por bobina). No cambian.
- **Candidatos técnicos (21):** P1-01, 02, 04, 05, 07, 10, 11, 12, 13, 16, 18, 21, 22, 24, 25, 26, 27, 28, 29, 30, 31. Solo se ofrecen si el backend los publica; ninguno está habilitado en la configuración real.

### 1.3 Pantallas y código legacy en `app/page.tsx`
`effectiveForms()` (lista local de ~30 formularios), `demoSeedData()`, `ensureDemoCoverage()`, `loadCoverage()`, `localContext()`, `ctx()` (turno por reloj del navegador), `Programming()` (crear/publicar/activar OT locales), `Cards()` (tarjetas de todos los formularios locales), `Capture()` (+ `Fiber`, `MaterialConsumption`, `PalletProduction`, `NapkinSheet`, `WasteCapture`, `BobbinBales`, `RewinderBale`, `GenealogyCapture`, `Chemical`, `Recipe`, `FormField`), `Tracking()` con conteo y descargas de registros locales, `downloadRows()/downloadRecords()`.

### 1.4 Claves de `localStorage`
| Clave | Quién la escribía | Quién la leía |
|---|---|---|
| `vinto-ot` | `useEffect` automático de `page.tsx` | estado inicial (`loadCoverage`) |
| `vinto-asg` | `useEffect` automático de `page.tsx` | estado inicial (`loadCoverage`) |
| `vinto-p1-records` | `useEffect` automático de `page.tsx` (cada captura legacy) | estado inicial; Seguimiento (conteo y descargas) |
| `vinto-device-key` | `lib/vinto/device.ts` (clave técnica del dispositivo para el `device_key` de las capturas centrales) | `lib/vinto/device.ts` |

### 1.5 Acciones de escritura legacy
Crear OT local (`Programming.add`), publicar base, añadir línea, **activar asignación local** (`Programming.activate`), **guardar captura local** (`Capture.submit` → `setRecords`) y la escritura automática de las tres claves.

### 1.6 Lecturas de registros históricos
`read("vinto-p1-records")`, `loadCoverage()` (OT/asignaciones legacy + demo), `Tracking` (conteo local, descargas CSV) y el resumen OT–producto local.

### 1.7 Dependencias del código legacy (por qué no se borró todo)
`scripts/export-seed-data.mjs` y `backend/seed_data/manifest.json` (**no se modifica**) extraen **por texto** de `app/page.tsx`: las máquinas de `GROUPS` (Bobinas, Rebobinado, Conversión), los overrides de etiquetas/unidades de F6, P1-19 y P1-20 dentro de `effectiveForms()`, los selectores de `BobbinBales` y la regla de turno nocturno de `ctx()`. Su huella semántica forma parte del manifiesto aprobado.

## 2. Estado DESPUÉS de INT-02A

### 2.1 Retirado de la operación
- `Programming()` local, `Capture()` y todos sus componentes auxiliares, `Cards()` con la lista local, `demoSeedData/ensureDemoCoverage/loadCoverage/localContext`, las descargas de registros locales, el buscador legacy y el conteo local en Seguimiento.
- **Las tres escrituras automáticas** (`vinto-ot`, `vinto-asg`, `vinto-p1-records`) y las lecturas iniciales: `app/page.tsx` ya **no llama a `localStorage` para nada** (ni get, set, remove, clear ni key).
- El estado `ots`, `asg`, `records`.

### 2.2 Conservado (circuito central)
| Frente | Qué ofrece la interfaz |
|---|---|
| **Bobinas** | Programación central (`BobbinasProgramming`), asignaciones centrales, **F3 y P1-06** como únicas tarjetas de formulario, fichas candidatas **solo si el backend las publica** para la máquina, Seguimiento central (OT, asignaciones, conteo central, historial F6 y de candidatos). |
| **Rebobinado** | Solo `RebobinadoCentral` → `SectorCentral`: disponibilidad que devuelve el backend (hoy «no está habilitado»), P1-10/P1-29 y candidatos P1-30/P1-07 si se publican. |
| **Conversión** | Solo `ConversionCentral` → `SectorCentral`: igual, P1-11/12/13/16. |
| **Calidad** | Inbox central por bobina, P1-19 y P1-20, candidatos por bobina y por máquina si el backend los publica (P1-28 como ficha **documental**), historial central. Sin tarjetas legacy. |

Sin asignación activa, sin permiso, con la API caída (401/403/error/cargando) o con el formulario sin publicar **no** se sustituye por un formulario local ni por datos demo: se muestra el estado real o «no habilitado» / «pendiente».

### 2.3 Sin conexión
Se muestra «Sin conexión: no es posible registrar capturas. Nada se guarda en este navegador». No hay captura offline hasta que VINTO apruebe explícitamente una estrategia de captura offline **central**.

### 2.4 Seguimiento
Solo indicadores con fuente central. Los conteos locales se retiraron (no hay «cero ficticio»). Reportes y «Bobinas liberadas» siguen **Pendiente**.

### 2.5 Código conservado a propósito pero INERTE
En `app/page.tsx` queda un bloque marcado «INT-02A · FUENTE LEGACY DE LA SIEMBRA DE DATOS — INERTE» (`GROUPS` completo, `ctx`, `fld`, `calc`, `effectiveForms`, `BobbinBales`, `Section`, `Choice`, `SelectBox`). **Ninguna pantalla lo llama**; existe solo porque el exportador de siembra y el manifiesto aprobado leen esos textos. Motivo: modificar `backend/seed_data` está fuera de alcance. Pendiente (INT-02B / siembra): moverlo a un módulo propio con un cambio de manifiesto aprobado y retirar el bloque.

## 3. Protección de los datos legacy

Reglas cumplidas (verificadas por `scripts/int-02a-central-only.test.mjs` con un `localStorage` espía y por el E2E-B0 con bytes sembrados):
1. No se llama `localStorage.clear()`.
2. No se llama `removeItem` sobre `vinto-ot`, `vinto-asg` ni `vinto-p1-records`.
3. No se sobrescriben con arrays vacíos ni con datos demo (ya no se escribe nada).
4. No se migran automáticamente al backend.
5. No se generan OT ni asignaciones sintéticas.
6. No se producen capturas con el mecanismo local.
7. No se suman a indicadores centrales ni se muestran: **no existe visor** (una cuenta B no puede ver lo de A).

Los bytes históricos permanecen en el navegador donde se crearon, intactos.

### 3.1 Procedimiento seguro para una futura exportación / conservación / migración (sujeto a decisión de VINTO)
1. **No hay forma segura de identificar al dueño** de un registro local: `vinto-p1-records` guarda `userId: "usuario-demo"` y `deviceId: "equipo-<máquina>"`, no una identidad autenticada. Por tanto **no se infieren propietarios** y el caso queda **pendiente de autorización**.
2. Antes de cualquier tratamiento: inventariar por navegador/equipo con consentimiento del responsable del equipo, **copiar** (nunca mover) el contenido de las tres claves a un archivo cifrado fuera del navegador, y verificar su suma de verificación.
3. Cualquier migración debe ser una **herramienta explícita, de una sola vez y por equipo**, ejecutada por un usuario autenticado con permiso, que cree capturas **centrales** mediante las APIs (idempotentes por `capture_id`), con revisión humana de cada registro y trazabilidad de origen; nunca automática al abrir la aplicación.
4. Solo después de verificar la copia y la migración, y con autorización escrita de VINTO, podría retirarse el contenido local. Hasta entonces: conservar.

## 4. Restricciones respetadas
Sin cambios en `DEFAULT_OPERATIONAL_SECTORS`, `CENTRAL_FORM_CODES`, `MACHINE_QUALITY_FORM_CODES`, `ENABLED_BOBBIN_CANDIDATE_FORM_CODES`, `backend/seed_data`, catálogos, máquinas, turnos, roles, permisos, concesiones, `quality_release`, fórmulas, genealogía ni correlativos. Sin cambios de backend ni migraciones.

## 5. Pendientes para INT-02B
Visor unificado de controles candidatos; mover la fuente de siembra fuera de `page.tsx` con cambio de manifiesto aprobado; decisión de VINTO sobre los datos legacy; estrategia offline central (si se aprueba); indicadores de Seguimiento con fuente central.

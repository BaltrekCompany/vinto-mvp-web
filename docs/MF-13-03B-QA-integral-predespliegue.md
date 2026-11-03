# MF13-03.B — QA integral previo al despliegue

Base: `origin/main` e193777 (merge de PR #112). Alcance: validar la funcionalidad multimáquina (PR1–PR8 + migración 0012) **en laboratorio aislado** antes de pedir autorización para desplegarla y activarla. **No se tocó la VPS, `vinto_piloto`, TVC, ETL ni Nginx; no se aplicó ninguna migración fuera de bases efímeras; no se activó ningún flag ni modo AUTHZ; no se fusionó ni desplegó nada.** Plan de despliegue y matriz GO/NO-GO: `docs/MF-13-03B-plan-de-despliegue.md`.

## 1. Preflight (Fase 1)

| Verificación | Resultado |
|---|---|
| `origin/main` incluye PR #112 | Sí (`git merge-base --is-ancestor e193777 origin/main`) |
| Migraciones | 0001…0012 contiguas (0010 expand, 0011 trigger por máquina, 0012 guarda de modo) |
| Flags en el código | `WORK_ORDERS_MULTI_MACHINE_ENABLED=False` y todos los `AUTHZ_*_MODE="off"` por defecto (`backend/app/config.py`) |
| Flags en artefactos de despliegue | `deploy/mvp/env/backend.env.example` y `docker-compose.yml` **no** los definen; producción queda apagada. (No se leyeron los `.env` locales: el entorno denegó el acceso, y no era necesario.) |
| Contratos | `GET /api/work-orders/capabilities`, `POST /api/work-orders/{id}/activate-all`, `GET /api/assignments/active`, `/active-lines`, `/operational-lines`, `POST /api/bobbins`: verificados por pruebas HTTP reales (ver §2) |
| Producción | Intacta: todo corrió en PostgreSQL efímero local y en un contenedor propio que se eliminó |

## 2. QA funcional integrado por HTTP real (Fase 2)

`backend/tests/test_qa_integral_multimachine.py` (11 pruebas, **todas OK**): ASGI real, login con cookies, triggers reales de PostgreSQL, usuarios sintéticos por perfil. La compuerta y los modos AUTHZ se fijan **solo dentro del proceso de prueba**.

| Pedido | Cubierto por | Resultado |
|---|---|---|
| 1. Jefatura crea y publica una OT con varias líneas | `test_the_full_journey…` (L1, L2 en MP1; L3 en MP3) | OK |
| 2. Supervisión consulta capacidades y obtiene vista previa | capacidades 200 para Supervisión, 403 para Operación/Calidad/DATA, 401 sin sesión; vista previa de solo lectura | OK |
| 3. Supervisión activa varias líneas de una misma OT | `activate-all` 201 `applied`, 3 activas | OK |
| 4. Operación identifica las líneas activas | `/active` → 409 `MULTIPLE_ACTIVE_ASSIGNMENTS`; `/active-lines` lista L1 y L2 | OK |
| 5–7. Selección explícita, captura por línea y cambio de línea | `POST /api/bobbins` con el `assignment_id` de L1 y luego de L2: 1 captura en cada una | OK |
| 8. Supervisión finaliza una línea y Operación pierde el contexto | `finish` → captura sobre L1 = 409 `ASSIGNMENT_NOT_ACTIVE`; L1 desaparece de `/active-lines`; `/active` vuelve al contrato de una sola; el histórico se conserva | OK |
| 9. Conflictos entre OT | activación individual 409 `MACHINE_ACTIVE_WITH_OTHER_WORK_ORDER`; masiva `can_confirm=false`, 2 conflictos, confirmar 409 `ACTIVATION_BLOCKED`; OT original intacta | OK |
| 10. Permisos, revocaciones, turno, concurrencia, idempotencia | 403 por perfil y 401; concesión revocada ⇒ 403 sin tocar la línea; turno +2 días ⇒ `stale` y 409 `ASSIGNMENT_STALE`; 4 capturas concurrentes en 2 líneas; doble envío con el mismo `capture_id` ⇒ 1 fila (201 + 200); `activate-all` repetido ⇒ 200 `already_in_effect`; captura contra `finish` (guardada o rechazada, nunca a medias) | OK |
| Flag apagado (comportamiento histórico) | capacidades `false`; OT con línea en **otra** máquina ⇒ 422 `MULTI_MACHINE_DISABLED`; `activate-all` ⇒ 422; activar otra línea **reemplaza** a la anterior; `/active` 200; la BD (0012) rechaza una segunda activa aunque el escritor salte el servicio | OK |
| Preflight SQL consolidado | informa operadores sin concesión y máquinas con varias activas; **no escribe nada** (`SET TRANSACTION READ ONLY`) | OK |

**Hallazgo de diseño (requisito previo, no defecto):** con la compuerta **encendida**, un operador sin ninguna concesión máquina-formulario activa recibe 422 `MACHINE_OUTSIDE_SCOPE` en `/active` y `/active-lines`, y la aplicación le muestra «Sin accesos asignados» (PR5: la visibilidad pasa a depender de las concesiones). Está fijado por la prueba `IntegralGatePrerequisiteTests`. **Antes de encender el flag hay que conceder a todos los operadores activos lo que deban ver** (preflight sección 2).

### Suites completas y línea base
- **Backend completo** (rama de esta QA): 2158 pruebas; **19 fallos, idénticos a `origin/main`** (18 `FileNotFoundError` por archivos fuera del montaje Docker + `test_capture_count_authorization`). **0 regresiones.** (Las 10 pruebas integrales corrieron dentro de la suite; la clase del preflight, añadida después, corrió aparte: módulo completo 11/11.)
- **Frontend:** esta fase no modifica código fuente del frontend (solo `scripts/e2e/`, pruebas de backend y documentos). La línea base posterior a PR8 es 962 pruebas con 32 fallos heredados; **no se reejecutó** en esta fase.
- No se declara ninguna suite limpia: los 19 + 32 heredados siguen sin corregirse (fuera de alcance).

## 3. E2E de navegador real (Fase 3)

Herramienta: `scripts/e2e/mm13-run.mjs` + `mm13-e2e.mjs` (derivadas de QA-3F-01, mismas salvaguardas) + `backend/tests/e2e_mm_server.py`. Levanta solo para la prueba, en `127.0.0.1`: PostgreSQL 17.11 en un contenedor propio con tmpfs (`vinto-mm13-pg`, puerto 55441), el **frontend real** construido con `NEXT_PUBLIC_API_URL` de QA (puerto 8798) y el **backend real** (puerto 8193) sobre una base efímera `*_test`; **Chrome 156 real** controlado por CDP. Dos fases: compuerta **encendida** y **apagada** (solo en ese proceso). Evidencias en `docs/MF-13-03B-QA-evidencia/` (resultados JSON con SHA y base, entorno y capturas **tomadas por el navegador**, no composiciones estáticas).

**Resultado (corrida final): 66 comprobaciones; 64 OK y 2 FALLAN** (defectos reales, §5). Fase encendida 48 (46 OK, 2 fallos); fase apagada 18/18. Contenedor, puertos y procesos eliminados; la verificación de limpieza halló perfiles temporales de Chrome de la propia corrida que se eliminaron a mano (§6).

Cubierto con clics y teclado reales: login/logout y cambio de sesión; Supervisión abre el diálogo, la vista previa es **una** solicitud `{"dry_run":true}` sin escribir en BD; Escape lo cierra; el foco inicial no cae sobre «Confirmar»; **doble clic en «Confirmar» = una sola confirmación** con el `plan_hash` del servidor y 3 activas en BD; conflicto entre OT con «Confirmar» deshabilitado; Operación: `/active` 409 y solo entonces `/active-lines`, selector sin ninguna línea marcada, F3 no se abre sin elegir, elección con barra espaciadora, captura sobre L1 y luego L2 con el `assignment_id` correcto (verificado en BD y en los POST), Supervisión finaliza L1 y «Actualizar líneas» le quita el contexto, estado de error sin red con «Reintentar» que recupera, sin almacenamiento local de la selección; operador sin concesión ⇒ «Sin accesos asignados»; móvil de 390 px sin desplazamiento horizontal y objetivos táctiles ≥ 44 px; fase apagada: sin botón masivo, activar reemplaza, Operación sin selector con **una sola** lectura `/active`, captura correcta.

**Límites declarados:** solo Chrome headless en Windows (sin Firefox/Safari/dispositivo táctil real; «móvil» es un viewport emulado de 390 px); la creación de la OT por Jefatura se hizo por API en este recorrido (su pantalla se cubrió en PR6 con pruebas de render, no con este E2E); sin pruebas de carga; sin coexistencia con TVC ni VPS.

## 4. Cobertura por sector (Fase 4, solo auditoría; sin cambios de código)

| | Bobinas | Rebobinado | Conversión |
|---|---|---|---|
| Programación (Jefatura) | **Completo** (PR6: máquina por línea, capacidades) | `BobbinasProgramming` sin `capabilities`/`scope`: solo OT de una máquina | Igual que Rebobinado |
| Activación masiva (Supervisión) | **Completo** (PR7) | **No hay botón** (queda apagado, no roto): el shell no pasa capacidades ni `scope` | Igual |
| Activación individual | Sí | Sí | Sí |
| Ejecución con varias líneas activas | **Selector (PR8)** | `/active` → **409**: se muestra «El estado cambió. Actualiza y vuelve a intentar.» y «Reintentar» repite el mismo 409: **callejón sin salida** | Igual |
| Captura / backend | `lock_active_assignment` (activa, vigente, alcance, concesión) | Comparte `lock_active_assignment` (`capture_service.py:623`) ⇒ el backend ya es seguro con varias líneas | Igual |
| Estado | Listo (con defectos §5) | Funciona con **una** línea por máquina; con la compuerta encendida y 2+ activas en una máquina de este sector, Operación queda bloqueada | Igual |

**Por qué importa:** la compuerta es **global**: al encenderla, la regla «varias líneas de la misma OT» rige para **todas** las máquinas. Supervisión puede activar 2 líneas en una máquina de Rebobinado/Conversión con «Activar» y Operación de ese frente queda sin salida (falla segura: no captura nada, pero sin explicación útil).

**Integración necesaria (no implementada):** (a) reutilizar `useOperationSelection` + `LineSelector` en el `Execution` de `sector-central.tsx` (cambio pequeño, mismo contrato); (b) pasar capacidades, `scope` y `onCapabilitiesStale` al `Programming` del shell para la activación masiva; (c) mensaje específico para `MULTIPLE_ACTIVE_ASSIGNMENTS` en lugar del genérico.
**Alternativas:** A) hacer (a)+(c) ahora y (b) después (**recomendada**: elimina el callejón con poco riesgo); B) extraer un contenedor de Ejecución compartido entre Bobinas y los shells (más limpio, más grande); C) no tocar y exigir por procedimiento que Supervisión no active 2+ líneas de una OT en máquinas de Rebobinado/Conversión mientras el flag esté encendido (frágil: nada lo impide técnicamente).

## 5. Defectos y observaciones (no se corrigen aquí; PR correctivos propuestos)

| ID | Hallazgo | Evidencia | Severidad | PR propuesto |
|---|---|---|---|---|
| **DEF-1** | Al cerrar con Escape el diálogo de activación masiva **el foco no vuelve** al botón que lo abrió (queda en el logotipo «VINTO»; no se probó «Cerrar»). La documentación de PR7 afirmaba lo contrario. Causa probable (no medida): el diálogo se abre por estado, sin `DialogTrigger`, así que Radix no conoce el elemento al que devolver el foco | E2E A6b (FAIL), foco en «VINTO» | Baja–media (teclado/lector de pantalla) | PR-A: guardar el elemento activo al abrir y restaurarlo en `onCloseAutoFocus` |
| **DEF-2** | Con la preferencia de **tema oscuro** del sistema, el diálogo de PR7 se pinta oscuro (Radix usa `bg-background`) pero su contenido usa colores claros fijos: el resumen y los encabezados de tabla quedan **ilegibles** (contraste 1,12:1; en tema claro 17,06:1) | E2E D7 (FAIL), capturas `sup-05…claro.png` y `sup-06…oscuro.png`; las capturas estáticas de PR7 lo ocultaron al forzar tema claro | Media (ilegible para usuarios con tema oscuro) | PR-A: colores del contenido con tokens del tema, o forzar fondo claro en el diálogo |
| **OBS-1** | Requisito previo: con el flag encendido, los operadores necesitan concesiones máquina-formulario (§2) | `IntegralGatePrerequisiteTests` | Condición de GO | Procedimiento (etapa 1 del plan); sin PR |
| **OBS-2** | `deploy.sh migrate` solo hace `--check` y corre desde `current` (tras `activate`): dejaría el backend nuevo sobre el esquema viejo | lectura de `deploy/mvp/scripts/deploy.sh` | Alta si no se corrige el procedimiento | PR-C: fase `migrate-release <sha>` (o procedimiento documentado: migrar desde el release nuevo antes de `activate`) |
| **OBS-3** | Rebobinado/Conversión: callejón sin salida con 2+ activas (§4) | lectura de `sector-central.tsx` + `failureMessage` | Media si esos frentes se usan | PR-B |
| **OBS-4** | Herramienta E2E: al terminar quedan perfiles temporales de Chrome (la limpieza corre antes de que Chrome suelte los archivos); el orquestador lo reporta como «LIMPIEZA PENDIENTE» | corrida final | Baja (solo herramienta) | PR-D (reintentar el borrado) |

## 6. Riesgos pendientes

1. **No hay E2E en VPS, ni con TVC coexistiendo, ni carga real:** solo laboratorio.
2. DEF-2 afecta a quien use tema oscuro; DEF-1 a quien navegue con teclado.
3. Rebobinado/Conversión (OBS-3) mientras no exista PR-B.
4. Backend **viejo** + compuerta encendida + 0012 ⇒ activaciones múltiples rechazadas (por eso el backend nuevo va antes que el flag).
5. La ventana de migración espera a las escrituras en curso sobre `assignment` (probado con `lock_timeout`).
6. La compuerta es global (no por OT ni por máquina): no se puede habilitar «solo Bobinas».

## 7. Recomendación

- **Despliegue con la compuerta APAGADA: GO condicionado** a (i) backup verificado y restaurado, (ii) preflight SQL revisado, (iii) **migrar desde el release nuevo ANTES de `activate`** (OBS-2) y (iv) las autorizaciones del plan. Con el flag apagado el comportamiento es el histórico (probado en navegador y por HTTP) y las migraciones son compatibles hacia atrás con el backend actual.
- **Encender la compuerta: NO-GO todavía.** Antes: concesiones de operadores (OBS-1), decisión sobre **DEF-2** (recomiendo corregirlo: PR-A pequeño) y decisión explícita sobre Rebobinado/Conversión (PR-B o confirmar que en el piloto no se usan varias líneas por máquina en esos frentes). Después, habilitar por etapas (plan §5).
- PR correctivos propuestos, separados: **PR-A** (DEF-1+DEF-2, diálogo de PR7), **PR-B** (Rebobinado/Conversión), **PR-C** (migración antes de `activate` en `deploy.sh`), **PR-D** (limpieza del E2E).

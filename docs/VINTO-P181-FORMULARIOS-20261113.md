# VINTO P181 — Ajustes de formularios | trazabilidad técnica (13/11/2026)

**Repositorio:** `BaltrekCompany/vinto-mvp-web`  
**PR:** [#181](https://github.com/BaltrekCompany/vinto-mvp-web/pull/181)  
**Rama:** `feat/vinto-formas-p125-p116-20261113`  
**Base de comparación:** `19d2058652734d4a51268449d482522b2b2315e8` (`main` al iniciar el PR).  
**Estado de entrega:** CANDIDATO; PR en borrador, **sin merge y sin despliegue en VPS**. La condición de salida es CI integral PASS y autorización del cambio.

## 1. Decisiones y alcance funcional

| Formulario | Versión nueva | Cambio de captura | Conservación histórica |
| --- | --- | --- | --- |
| P1-25 Resistencia en húmedo-curado | V4 | Seis etiquetas corregidas; retirada la nota de prototipo | Identificadores de campos y datos anteriores inalterados |
| P1-16 Control de merma | V4 | Retirados Hora inicio, Hora fin, sección y textos explicativos; se mantiene una pesada por registro | V1–V3 consultables por sus versiones; campos legacy de horas no se solicitan en V4 |
| P1-07 Producción de bobinas rebobinadas | V5 | `formato_3` se muestra como **Cortes** | Clave `formato_3`, valor decimal, carácter opcional, 21 posiciones de crías y genealogía intactos; V4 sigue mostrando «Formato 3» |
| P1-10 Registro de fardos | V4 | No se piden horas; nuevo **Tipo** obligatorio: una de Papel Higiénico, Toalla o Servilleta | Peso y observaciones intactos; V1 conserva código/número, V2–V3 conservan ambas horas |
| P1-05 Registro de tubetes | Sin nueva versión: baja funcional | No se ofrece ni admite nuevas capturas o concesiones máquina–formulario | Se retienen versiones, definiciones, capturas y concesiones históricas; lectura filtrada por permisos |

**Fuera de alcance:** borrar capturas/usuarios, alterar roles, modificar bobinas existentes, renumerar crías, implementar correlativos automáticos, crear migraciones destructivas o cambiar reglas industriales no aprobadas.

## 2. Detalles técnicos implementados

- **Frontend:** `lib/vinto/p1-07.ts` preserva la clave técnica `formato_3` y permite mostrar su etiqueta histórica con `renamedAt`; `lib/vinto/p1-10.ts` separa parser de lectura por versión y contrato de borrador V4; `components/vinto/p1-10-capture.tsx` usa selección única para Tipo y retira las horas.
- **Catálogo:** `backend/seed_data/forms/VINTO-P1-07.json` V5 y `VINTO-P1-10.json` V4. Se recalculan `definition_checksum`, hashes de archivos y `backend/seed_data/manifest.json`. Conteo de la última versión de bundle: **26 formularios, 567 campos, 38 opciones**.
- **Servidor:** `backend/app/mp3_inspection_policy.py` niega P1-05 en `allowed_for_machine` (disponibilidad y concesiones) y `assert_form_machine` (POST de capturas). La clave permanece en `CENTRAL_FORM_CODES` **solo para que no se rompa la consulta del historial**; el código publicado por sí solo no autoriza nuevas capturas.
- **Persistencia:** importar versiones nuevas de forma aditiva, sin sobrescribir definiciones publicadas. El backend valida contra campos, obligatoriedad y opciones de la versión vigente almacenada en PostgreSQL; en P1-10 V4 rechaza valores de Tipo ajenos al catálogo.
- **Compatibilidad de QA:** `backend/tests/mf13_p110_v3.json` es una copia de la definición histórica V3 usada en bases efímeras de prueba; **no** se introduce como definición de producción V4. Pruebas de concesiones anteriores se aíslan con un parche temporal del ensayo, sin debilitar la política productiva.

## 3. Evidencia de pruebas y regresiones

| Control | Evidencia | Resultado conocido al registrar los avances |
| --- | --- | --- |
| P1-25/P1-16 nuevos contratos | `backend/tests/test_cv_formas_p125_p116.py` y los gates de catálogo | Cambios implementados; ver CI del HEAD |
| P1-07 crías + Calidad PG17 | `scripts/rb-crias-quality.test.mjs` y `backend/tests/test_rb_crias_quality_api.py` | PASS en commit `57956768` |
| P1-10 V4, historial V1–V3 | `scripts/p1-10-capture.test.mjs`, `scripts/p181-forms-finalization.test.mjs`, `backend/tests/mf13_p110_v3.json` | Contratos implementados; sujetos al CI del HEAD |
| Retiro P1-05 | `backend/tests/test_p181_retired_tubetes.py`, `backend/tests/test_machine_form_grants_hardening.py` | Bloqueo funcional incorporado; pruebas de disponibilidad ajustadas |
| RG-MP3-01 | GitHub Actions, suite aislada | PASS en `57956768` |
| CV-P111-v3, CV-P112-01, CV-P113-01 | GitHub Actions, suites aisladas | PASS en `57956768` |
| E1-08 focus, 55 pruebas | GitHub Actions `43484229262` | En `57956768`: **53 PASS y 2 fallos** de expectativas de versión/oferta, corregidos en el siguiente commit; **pendiente revalidación** |
| E1-08 integración frontend/backend | GitHub Actions `43484229275` | Frontend PASS; backend todavía ejecutándose cuando se inició esta corrección; revisar resultado definitivo |

### 3.1. Correcciones del gate E1-08

1. `test_mf12a_p101_availability.py`: la matriz general de versiones debe reflejar P1-07 **V5** y P1-10 **V4**, sin cambiar las comprobaciones originales de P1-01/P1-05/P1-31.
2. `test_mf13_p110_rebobinado_machines.py`: la lista de formularios ofrecidos excluye P1-05, retirado para nuevas operaciones, incluso cuando su definición y vínculo histórico permanezcan en el bundle. Conserva P1-10 V3 en la prueba **histórica** aislada.
3. Estas correcciones actualizan *oráculos de prueba* legítimos; no omiten tests, no amplían la línea base de fallos y no cambian datos industriales para forzar PASS.

## 4. Condiciones de salida y despliegue controlado

1. Todos los flujos CI del commit final deben finalizar **PASS**, incluyendo E1-08 frontend/backend y su grupo de 55 regresiones, PG17 y suites de formularios.
2. Revisión formal del diff y del alcance, sin cambios inesperados en rutas, permisos, cálculos o migraciones.
3. Antes de cualquier modificación de la VPS: **preflight de solo lectura**, respaldo PostgreSQL nuevo con verificación de restauración, comprobación de release activo y artefacto frontend del SHA autorizado.
4. Ejecutar `import_reference.py` en modo simulación para el bundle final, revisar `conflicts=[]` y el detalle de creaciones; aplicar solo con autorización y backup verificado. La nueva definición no debe publicarse mientras haya operadores capturando en formularios involucrados.
5. Activar release exacto, verificar `/health`, `/api/health`, disponibilidad, captura P1-10 V4, lectura histórica, bloqueo P1-05 y procedimiento de reversión.
6. Documentar SHA, backup, hora, resultado QA, responsable y decisión de cierre.

**Nota de estado:** la finalización de una ejecución de GitHub Actions no equivale a un despliegue ni a una aprobación de merge. La aprobación productiva es un control distinto.

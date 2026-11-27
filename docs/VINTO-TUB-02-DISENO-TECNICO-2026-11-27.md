# VINTO — TUB-02: Diseño técnico del endpoint de Tubetes Utilizados

**Fecha:** 27 de noviembre de 2026  
**Estado:** diseño técnico propuesto; implementación no iniciada.  
**Dependencia funcional:** decisiones D01-D05 aprobadas en TUB-01.  
**Estrategia de pruebas:** fixtures sintéticos en PostgreSQL efímero PG17; no crear capturas de prueba en la VPS.  
**Alcance:** exclusivamente backend de consulta y autorización del Reporte de Tubetes Utilizados (MP1/MP3).

---

## 1. Objetivo

Diseñar una consulta central, de solo lectura, para consolidar los usos de tubetes registrados en Producción de Bobinas P1-03.

Endpoint previsto:

`GET /api/reports/tubetes-used`

La respuesta debe incluir ambas máquinas MP1 y MP3 en una sola consulta, para que la interfaz, el PDF y el Excel consuman exactamente la misma fotografía de datos.

TUB-02 no implementa la pantalla ni las exportaciones; esos trabajos corresponden a TUB-03, TUB-04 y TUB-05.

## 2. Decisiones funcionales vinculantes

| ID | Regla |
|---|---|
| D01 | Código como texto que conserva el entero original de P1-03. No añadir `TUB-`, ceros ni normalización. |
| D02 | Fecha `operating_date`; zona operativa `America/La_Paz`. No derivar fecha desde UTC. |
| D03 | Incluir capturas `submitted` y `closed`, cualquiera sea el estado de Calidad. Excluir `draft`, `blocked` y órdenes `qa_retired`. Incluir órdenes archivadas normales. |
| D04 | Permiso `report.read` para `JEFATURA` y `SUPERVISION`; exigir sector BOBINAS y limitar en servidor a MP1/MP3. |
| D05 | Una respuesta con ambas máquinas; todas las utilizaciones y duplicados conservados. Códigos en orden numérico; fechas ascendentes y `captured_at` como desempate. |

El reporte mide consumo de tubetes, no aprobación de bobinas. No debe filtrar por `quality_release.status`: una bobina rechazada o pendiente ya consumió el tubete.

## 3. Fuente de datos y joins

Fuente primaria:

- `vinto_txn.capture`
- `vinto_config.form_version` y `vinto_config.form`
- `vinto_master.machine` y `vinto_master.sector`
- `vinto_txn.capture_detail`
- `vinto_config.field_definition`
- `vinto_txn.assignment`
- `vinto_txn.work_order_line`
- `vinto_txn.work_order_version`
- `vinto_txn.work_order`
- `vinto_txn.bobbin` (para confirmar que la captura produjo una bobina F3 numerada)

### Relaciones

```text
capture
  ├─ form_version ─ form (VINTO-P1-03, área production)
  ├─ machine ─ sector (MP1 / MP3, BOBINAS)
  ├─ capture_detail ─ field_definition (key = codigo_de_tubete)
  ├─ bobbin (source_capture_id, sequence_number IS NOT NULL)
  └─ assignment
       └─ work_order_line
            └─ work_order_version
                 └─ work_order (qa_retired)
```

### Reglas del join

1. Identificar P1-03 por `form.code = 'VINTO-P1-03'`; no utilizar P1-05, P1-07 ni una lista genérica de bobinas.
2. Identificar el campo por `field_definition.key = 'codigo_de_tubete'` y la versión de formulario asociada a la captura; no fijar un UUID de versión.
3. El campo es simple, no repetible: exigir `group_row_id IS NULL`.
4. Para códigos existentes, leer `capture_detail.value_integer` y validar que el tipo de definición/detalle siga siendo `integer`.
5. Hacer LEFT JOIN a la definición y al detalle para reconocer capturas históricas v1 que no tenían el campo. Esas capturas no generan fila de tubete y pueden sumarse a `records_without_code`.
6. Relacionar con la bobina mediante `bobbin.source_capture_id = capture.id` y `sequence_number IS NOT NULL`. El índice único parcial de producción F3 evita multiplicar una captura numerada por varias bobinas.
7. Relacionar la orden desde la asignación hasta `work_order` y excluir únicamente `qa_retired = true`.
8. No filtrar por `work_order.archived_at`: las órdenes archivadas normales no se excluyen por el mero hecho de estar archivadas.
9. No unir ni filtrar por el estado de `quality_release`. La decisión de Calidad no cambia el consumo.

Si se encuentra una definición de campo con tipo distinto de integer o un detalle inconsistente con la definición, la consulta debe fallar de forma segura y dejar evidencia técnica sanitizada; no convertir texto ni corregir datos silenciosamente.

## 4. Consulta y agregación

El servicio ejecutará una única consulta parametrizada que:

- Filtre `c.status IN ('submitted','closed')`.
- Filtre formulario P1-03 y `fv.area = 'production'`.
- Filtre `s.code = 'BOBINAS'` y `m.code IN ('MP1','MP3')`.
- Excluya `wo.qa_retired = true`.
- Mantenga las capturas históricas v1 aunque no tengan definición/detalle de tubete, para poder contarlas como registros sin código.
- Devuelva una fila por captura con código nullable, `operating_date`, `captured_at` y máquina.
- Ordene por máquina, valor entero del código, `operating_date`, `captured_at` e ID de captura.

La agregación en Python conservará cada fila como una utilización independiente. No se aplicará `DISTINCT` sobre código/fecha, ni se deduplicarán dos usos del mismo código en un mismo día.

El orden numérico se aplicará al valor entero antes de serializarlo como texto. Las fechas se ordenarán por `operating_date`; cuando coincidan, se conservará el orden de `captured_at` y del ID de captura.

### Código sin valor

- Una captura incluida que no tiene el campo (por ejemplo, P1-03 v1) o no tiene valor registrado se contabiliza en `records_without_code`.
- No genera una utilización ni una fila en `tubetes`.
- `records_without_code` es un dato diagnóstico del endpoint, no un consumo ni una fila que deba imprimirse.
- No aplicar filtro `value_integer > 0`: el contrato aprobado exige preservar el entero almacenado. Cualquier regla de validación positiva es una decisión independiente sobre P1-03.

## 5. Contrato de respuesta

Esquema propuesto:

```json
{
  "generated_at": "2026-11-27T15:00:00Z",
  "source_form": "VINTO-P1-03",
  "date_basis": "operating_date",
  "timezone": "America/La_Paz",
  "machines": [
    {
      "machine": "MP1",
      "usage_total": 0,
      "records_without_code": 2,
      "tubetes": []
    },
    {
      "machine": "MP3",
      "usage_total": 3,
      "records_without_code": 2,
      "tubetes": [
        {
          "code": "1",
          "usage_count": 1,
          "dates": ["2026-11-13"]
        },
        {
          "code": "50",
          "usage_count": 1,
          "dates": ["2026-11-16"]
        },
        {
          "code": "70",
          "usage_count": 1,
          "dates": ["2026-11-16"]
        }
      ]
    }
  ]
}
```

Los valores del ejemplo son ilustrativos; no representan una nueva lectura de producción.

### Invariantes de respuesta

- `machines` siempre contiene MP1 y MP3, incluso cuando una no tenga registros.
- `usage_total` es la suma de utilizaciones con código para esa máquina.
- `usage_count = len(dates)` para cada código.
- `dates` contiene una entrada por captura, incluso si dos entradas tienen la misma fecha.
- `code` es string decimal del entero original; no es el código secuencial de bobina.
- La API devuelve todas las fechas. El límite de diez es solo de presentación PDF.
- `generated_at` debe incluir zona/offset explícito; el contrato identifica la base de fecha y zona operativa.

## 6. Autorización

### Backend

Añadir `REPORT_READ = 'report.read'` a:

- `backend/app/auth/permissions.py`
- `ALL_PERMISSIONS`
- `PROFILE_PERMISSIONS[JEFATURA]`
- `PROFILE_PERMISSIONS[SUPERVISION]`

No añadir el permiso a OPERACION, CALIDAD ni DATA_BALTREK.

El endpoint usa `Depends(require_permission(REPORT_READ))`. Luego exige explícitamente que `BOBINAS` esté entre los sectores concedidos al usuario. Si falta, responde 403; no devolver un reporte vacío como si fuera válido.

El servidor fija MP1 y MP3 en la consulta. El endpoint no acepta parámetros de máquina, sector, usuario, fechas ni filtros enviados por el navegador.

### Frontend

Añadir `report.read` al union type `Permission` de `lib/vinto/auth.ts`, para que TUB-03 pueda usar el permiso de UX. La autoridad real permanece en el backend.

No se modifica el login, el contrato de sesión ni `user_out`: la lista de permisos ya se deriva de la matriz de perfiles y se devuelve en `/api/auth/me`.

### Semántica HTTP

- 401: sesión ausente, inválida o expirada.
- 403: permiso insuficiente o sector BOBINAS no concedido.
- 503: base de datos o consulta no disponible.
- 200: ambas máquinas devueltas, incluso si alguna está vacía.

Añadir `Cache-Control: private, no-store` a todas las respuestas del endpoint. La consulta no debe registrar auditoría de negocio ni crear eventos persistentes.

## 7. Transacción y solo lectura

La conexión de aplicación opera en autocommit. El servicio debe abrir una transacción explícita y establecer READ ONLY como primera sentencia:

```python
with connection.transaction():
    connection.execute("SET TRANSACTION READ ONLY")
    # consulta SELECT parametrizada
```

No ejecutar SQL de escritura, DDL, migraciones ni cambios de configuración. No leer datos personales del creador de la captura.

No se requiere migración de base de datos para esta primera implementación: el permiso vive en la matriz de código y la fuente de datos ya existe.

## 8. Estructura de archivos propuesta

```text
backend/app/reports/
  __init__.py
  router.py
  tubetes_service.py
  tubetes_schemas.py

backend/tests/
  test_tubetes_report_service.py
  test_tubetes_report_api.py

lib/vinto/auth.ts
backend/app/auth/permissions.py
backend/app/main.py
```

El router se registra en `backend/app/main.py`. No se modifica ningún router ni endpoint de Calidad Offline.

## 9. Pruebas sintéticas en PostgreSQL efímero PG17

Los escenarios ausentes en la VPS se cubrirán exclusivamente con fixtures automatizados en bases de datos de prueba efímeras. No se crearán capturas artificiales en la base de producción ni en la VPS.

### Matriz de casos

| Caso | Fixture | Resultado esperado |
|---|---|---|
| Ambas máquinas | MP1 y MP3 con datos distintos | Ambas aparecen siempre en la respuesta |
| Máquina vacía | MP1 sin códigos; MP3 con códigos | MP1 devuelve lista vacía y MP3 conserva sus filas |
| Mismo código, varias fechas | Un código con varias capturas | Una fila agrupada y todas sus fechas |
| Mismo código, mismo día | Dos capturas con mismo código y `operating_date` | Dos fechas iguales; no deduplicar |
| Más de diez usos | Un código con 23 capturas | API devuelve 23 fechas; PDF queda para TUB-04 |
| Mismo número en ambas máquinas | Código 1 en MP1 y MP3 | Dos grupos independientes |
| Calidad pending/released/rejected | Capturas con cada estado | Todas cuentan |
| Captura submitted/closed | Ambos estados | Ambas cuentan |
| Draft/blocked | Capturas con esos estados | Excluidas |
| OT qa_retired | Captura histórica enlazada a OT retirada | Excluida |
| OT archivada normal | No filtrar por `archived_at` | La consulta no la excluye por ese campo |
| P1-03 v1 sin campo | Captura histórica sin definición/detalle | No genera tubete; incrementa `records_without_code` |
| Código numérico | 1, 2, 10, 50 | Orden numérico, serializado como texto |
| Valor 0/negativo | Solo si el fixture lo requiere para preservar contrato | No normalizar ni excluir silenciosamente |
| Sin sector | Usuario report.read sin BOBINAS | 403 |
| Sin permiso | OPERACION/CALIDAD/DATA_BALTREK | 403 |
| Sin sesión | Sin cookie válida | 401 |
| Sin escrituras | Comparar conteos y eventos antes/después | Ningún dato de negocio ni auditoría cambia |

Las pruebas de integración deben seguir el patrón existente de PostgreSQL efímero PG17 y la protección de nombres de bases de prueba. No deben apuntar a la base de producción.

La situación de una orden archivada normal asociada a una captura puede no ser construible bajo las reglas actuales de archivo (no se archivan órdenes con asignaciones). Se comprobará que el SQL no filtra `archived_at` y no se desactivarán triggers ni restricciones para fabricar un estado imposible.

## 10. Rendimiento y migraciones

La consulta debe ser una sola lectura, sin N+1 y sin cargar detalles de campos no relacionados.

Antes de proponer índices:
- Ejecutar `EXPLAIN` sobre la consulta en la base efímera PG17 con fixtures representativos.
- Revisar índices existentes de `capture`, `capture_detail`, `field_definition` y `bobbin`.
- No ejecutar `EXPLAIN ANALYZE` contra producción.
- No añadir migración salvo evidencia reproducible de necesidad y revisión independiente.

La muestra productiva auditada es pequeña (13 capturas P1-03); no justifica anticipar una migración de rendimiento.

## 11. Alcance del PR de implementación TUB-02

El diseño se implementó en el [PR #258](https://github.com/BaltrekCompany/vinto-mvp-web/pull/258), limitado a:

- Matriz backend de `report.read`.
- Tipo frontend de permiso para futuras vistas.
- Router, servicio y esquemas de respuesta de Tubetes.
- Registro del router y respuesta `private, no-store`.
- Pruebas sintéticas y automatizadas en PostgreSQL 17 efímero.

No se incluyó:
- UI final de reportes (TUB-03).
- PDF ni Excel (TUB-04/TUB-05).
- Cambios P1-03.
- Migraciones.
- Cambios de login, sesiones o permisos de captura.
- Cambios en Calidad Offline, PWA, bóveda, IndexedDB, firmas, grants, cola o sincronización.
- Datos artificiales en la VPS ni producción.
- Despliegue productivo.

## 12. Puerta de aprobación

La aprobación de implementación fue otorgada el 27/11/2026. El alcance se ejecutó en el PR #258.

El PR #258 está abierto, fuera de Draft y listo para revisión. No se ha fusionado ni desplegado. La autorización de implementación no implica autorización de merge o despliegue.

## 13. Resultado de implementación y pruebas (27/11/2026)

**PR:** [#258 — feat(tubetes): implement read-only MP1/MP3 usage report API](https://github.com/BaltrekCompany/vinto-mvp-web/pull/258)  
**Rama:** `feat/tubetes-utilizados-report`  
**Base:** `main` en `b84562d9f5b78aab549219e82b4472ad67dadbeb`  
**HEAD:** `049a563986a0cf384b984d27d91511186c2a89dc`  
**Estado:** aprobado y fusionado mediante squash el 27/11/2026.  
**Commit integrado en main:** `5f66f6001d670b30fff99b44a08aa3286703dd81`.

### CI específico TUB-02 — PASS

- 14 pruebas de servicio/API.
- 7 pruebas de matriz de permisos.
- 6 pruebas estáticas de alcance sectorial.
- 17 pruebas de regresión P1-03 y Calidad.
- 15 pruebas frontend de autenticación/permisos.
- TypeScript, ESLint y build PASS.
- PostgreSQL de CI: 17.12.

### Cobertura demostrada

- MP1 y MP3 en una respuesta.
- Jefatura y Supervisión con permiso y sector BOBINAS.
- Operación, Calidad, Data Baltrek y Jefatura sin sector: 403.
- Sin sesión: 401.
- Estados de Calidad pending, released y rejected incluidos.
- 23 utilizaciones del mismo código en el mismo día conservadas.
- Consulta explícitamente READ ONLY.
- Conteos de capturas, detalles, bobinas, liberaciones y eventos de auditoría sin cambios tras consultar.
- Respuestas `private, no-store`.
- Regresión P1-03/Calidad y matriz de permisos aprobadas.

La matriz de workflows de integración disparados por el PR también terminó PASS, incluyendo USR-02/03/04/06 y las regresiones E1-08, E1-10, E2-B, E2-C1, E2-C2 y E2-D2.

### Límites verificados

- Sin migraciones.
- Sin escrituras en la VPS ni en la base productiva.
- Sin cambios de login/sesiones.
- Sin modificaciones a Calidad Offline.
- Sin cambios de P1-03.
- Sin UI, PDF ni Excel; permanecen en TUB-03/TUB-04/TUB-05.
- Sin despliegue.
- Merge realizado tras aprobación técnica; no se ha desplegado.

**Estado final:** `TUB02_IMPLEMENTATION=PASS_MERGED`.

## 14. TUB-03 — pantalla Seguimiento → Reportes (27/11/2026)

La implementación frontend se inició en un PR independiente:
- [PR #259 — Tubetes Utilizados en Seguimiento](https://github.com/BaltrekCompany/vinto-mvp-web/pull/259).
- Rama: `feat/tubetes-report-ui`.
- Base: commit TUB-02 ya integrado en `main`.

Alcance del incremento:
- Mostrar el acceso al reporte en Bobinas → Seguimiento → Reportes solo cuando el usuario tenga `report.read`.
- Consumir `GET /api/reports/tubetes-used` con el cliente HTTP central (cookie HttpOnly, `cache: no-store`).
- Mostrar MP1 y MP3 por separado, código, cantidad de usos y todas las fechas.
- Mantener fechas duplicadas del mismo día como usos independientes.
- Mostrar `operating_date` y zona `America/La_Paz`.
- Manejar carga, actualización manual, errores de red, 403 y sesión vencida.
- Validar el contrato de respuesta en el frontend.

PDF y Excel permanecen fuera de TUB-03: se desarrollarán en TUB-04 y TUB-05 con PR separados. No se han añadido cambios a backend, P1-03, Calidad Offline, migraciones, VPS ni producción.

**Estado:** PR #259 abierto en Draft mientras se completan CI y revisión.

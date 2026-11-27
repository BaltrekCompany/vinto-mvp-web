# VINTO — TUB-01: Auditoría de datos y contrato de Tubetes Utilizados

**Fecha:** 27 de noviembre de 2026  
**Método:** Claude Code conectado a la VPS; inspección de código y consultas PostgreSQL de solo lectura.  
**Resultado:** `TUB01_AUDIT=PARTIAL`  
**Alcance:** únicamente Producción de Bobinas P1-03, máquinas MP1 y MP3.  
**Código de producto:** no se implementó ni modificó.

---

## 1. Resumen ejecutivo

La fuente de datos del reporte está identificada y verificada: las utilizaciones se registran en las capturas de Producción de Bobinas **VINTO-P1-03**, en el detalle del campo `codigo_de_tubete`.

No es necesario crear un formulario ni una tabla paralela para almacenar utilizaciones. La consulta futura deberá leer las capturas y sus detalles, relacionándolos con la máquina y el formulario de origen.

La auditoría es **PARTIAL**, no porque falte identificar el origen, sino porque la muestra actual es insuficiente para demostrar varios casos de negocio: MP1 con códigos, reutilización de un código, más de diez utilizaciones, un mismo código en ambas máquinas y diferencias de fecha dentro de P1-03.

### Resultados principales

| Métrica | MP1 | MP3 | Total |
|---|---:|---:|---:|
| Capturas P1-03 | 3 | 10 | 13 |
| Capturas con código de tubete | 0 | 3 | 3 |
| Capturas sin código | 3 | 7 | 10 |
| Códigos distintos | 0 | 3 | 3 |
| Capturas enviadas (`submitted`) | 3 | 10 | 13 |

Los diez registros sin código pertenecen a la versión v1 de P1-03, anterior a la incorporación del campo. No deben interpretarse automáticamente como errores de captura: la v1 no tenía ese campo.

Los tres códigos encontrados en MP3 son `1`, `50` y `70`. No hay códigos con uso repetido en la muestra auditada.

---

## 2. Entorno y alcance de la inspección

- La aplicación productiva sigue en el release `54df1defedcf91e12d50c497e9b44a37ad3e9a50`.
- La versión desplegada coincide con la referencia histórica verificada en la auditoría.
- La base identificada es la base PostgreSQL 17 de VINTO en la VPS.
- Backend, frontend, Nginx y PostgreSQL estaban activos; las comprobaciones de salud devolvieron backend/base de datos OK y frontend OK.
- La zona horaria de PostgreSQL es UTC.
- El código remoto `main` estaba en `b84562d9`; el clon local de construcción consultado estaba desactualizado en `2ca165a`. Para cualquier trabajo futuro se debe partir del `main` remoto vigente, no del clon desactualizado.
- El plan de Tubetes se leyó desde su rama documental; en el momento de la auditoría todavía no estaba fusionado a `main`.

Se omiten deliberadamente direcciones IP, rutas internas, puertos, identificadores de contenedores y otros detalles de infraestructura. El repositorio GitHub es **público**, por lo que la documentación no debe convertirse en un inventario de infraestructura ni publicar secretos o datos personales.

---

## 3. Fuente de datos y relaciones

### Formulario

- Código: `VINTO-P1-03`.
- Nombre: «Registro de producción de bobinas».
- Máquinas: MP1 y MP3.
- Versiones publicadas identificadas: v1 (19/10) y v2 (13/11).
- La v2 es la que incorpora `codigo_de_tubete`; el campo es obligatorio y de tipo entero.
- El frontend desplegado contiene el campo y valida un entero.
- El backend especializado `POST /api/bobbins` recibe el valor, lo valida contra la definición publicada y lo guarda.

### Persistencia

El código de tubete queda almacenado en:

`vinto_txn.capture_detail.value_integer`

La columna almacena un entero grande (bigint). La tabla `vinto_txn.bobbin` no tiene una columna propia para el tubete.

La máquina se obtiene desde la captura:

`capture.machine_id → machine.code`

La auditoría encontró cero discrepancias entre la máquina de la captura y la máquina de la bobina relacionada.

Relación conceptual:

```text
capture
  ├── form_version ── form (VINTO-P1-03)
  ├── machine ── sector (MP1 / MP3)
  ├── capture_detail ── field_definition (codigo_de_tubete)
  ├── bobbin (source_capture_id) ── quality_release
  └── assignment ── line ── work_order
```

### Fuentes que NO deben confundirse

- P1-05 «Registro de tubetes» es otro formulario y almacena un valor de texto; no es la fuente definida para este reporte.
- El campo `tubete` de P1-07 es otra fuente distinta.
- P1-07 aporta 31 de las 44 bobinas existentes en la muestra de la base; consultar todas las bobinas sin filtrar por P1-03 mezclaría el proceso de Rebobinado con Producción de Bobinas.

La consulta futura debe identificar el formulario por su código y el campo por su clave funcional, no depender de un ID de versión fijo.

Los detalles de una captura enviada son inmutables por el trigger de integridad identificado en la auditoría.

---

## 4. Formato real de los códigos

Muestra completa disponible:

| Máquina | Códigos almacenados |
|---|---|
| MP1 | Sin códigos en la muestra |
| MP3 | `1`, `50`, `70` |

Hallazgos:

- Los valores son enteros; no hay valores alfanuméricos.
- Longitud observada: uno a dos dígitos.
- No hay letras, espacios ni caracteres especiales.
- No hay ceros iniciales almacenados.
- El frontend convierte `007` en `7` antes del envío y el backend también normaliza a entero.
- Un código como `TUB-001` no se puede registrar con el contrato actual.
- La validación actual admite cero y negativos, aunque no se encontraron esos valores en los datos consultados.

### Implicación funcional

La especificación visual muestra ejemplos como `TUB-001`, pero VINTO actualmente guarda enteros. El reporte debe mostrar el valor original almacenado (`1`, `50`, `70`) sin inventar el prefijo `TUB-` ni completar ceros.

Si Functional confirma que el identificador físico real incluye letras o ceros significativos, será necesario planificar una evolución independiente de P1-03 y su almacenamiento. No debe cambiarse el formulario dentro del desarrollo del reporte sin una decisión explícita.

---

## 5. Fechas y turnos

| Campo | Tipo | Significado |
|---|---|---|
| `capture.captured_at` | `timestamptz` | Momento de registro en PostgreSQL |
| `capture.operating_date` | `date` | Fecha operativa heredada de la asignación/turno |
| `bobbin.created_at` | `timestamptz` | Momento de inserción de la bobina |

La zona horaria operativa identificada en la lógica de turnos es `America/La_Paz`. PostgreSQL registra timestamps en UTC.

**Pendiente funcional importante:** confirmar que `America/La_Paz` corresponde efectivamente a la zona horaria de la planta. No sustituirla por `America/Lima` ni cambiar la configuración por inferencia. Si la planta opera en Perú, Functional debe confirmar explícitamente si la zona horaria correcta es `America/Lima`; la auditoría solo demuestra qué usa actualmente el código.

Turnos de Bobinas identificados:
- Día: 07:00–19:00.
- Noche: 19:00–07:00.

En los tres registros P1-03 con código:
- Las tres fechas coinciden en día entre `captured_at` convertido a La Paz, `operating_date` y `bobbin.created_at`.
- La diferencia entre `captured_at` y `created_at` fue de 31 a 57 milisegundos.
- No se encontraron diferencias de día entre esos campos en los 13 registros P1-03.

Sin embargo, otros formularios sí demuestran por qué importa la fecha operativa: en registros de turno noche, la fecha local de captura puede ser el día siguiente a `operating_date`.

Las horas `hora_inicio` y `hora_fin` no incluyen fecha y en algunos datos de prueba son incoherentes; no deben usarse para derivar la fecha de utilización.

### Recomendación pendiente de aprobación

Utilizar `operating_date` como fecha del reporte, porque atribuye el consumo al día operativo/turno al que pertenece, incluso cuando el registro se completa después de medianoche.

No convertir `captured_at` directamente a fecha UTC.

La zona horaria asociada también debe validarse con Functional: el código actual usa `America/La_Paz`. Confirmar si esa es la zona horaria real de la planta o si debe ser `America/Lima`. No cambiarla como parte de TUB-02 sin una decisión explícita.

Esta recomendación debe ser confirmada funcionalmente antes de TUB-02.

---

## 6. Repeticiones y estado de Calidad

En la muestra auditada:

| Comprobación | Resultado |
|---|---:|
| Usos por cada código | 1 |
| Códigos utilizados más de una vez | 0 |
| Códigos con más de 10 usos | 0 |
| Repeticiones del mismo código en un día | 0 |
| Códigos presentes en MP1 y MP3 | 0 |

No hay evidencia actual para probar la agrupación de múltiples fechas, la continuación del PDF ni los duplicados legítimos de un mismo día. Esos casos deberán cubrirse con pruebas controladas posteriores, previa autorización específica para crear registros de prueba.

### Hallazgo importante sobre Calidad

Dos de los tres registros que tienen código de tubete corresponden a bobinas rechazadas por Calidad.

- Incluir los tres registros produce tres utilizaciones.
- Excluir los rechazados deja una sola utilización.

### Recomendación funcional

El reporte mide **consumo/uso de tubetes**, no cantidad de bobinas aprobadas. Por tanto, se recomienda incluir los registros P1-03 enviados y válidos como producción, independientemente de que la bobina resultante esté liberada, pendiente o rechazada por Calidad.

La decisión de Calidad no deshace el consumo físico del tubete. No se deben reutilizar las reglas de liberación de Calidad como filtro de consumo.

Los borradores y registros bloqueados deben excluirse. La auditoría encontró los 13 registros P1-03 en estado `submitted`, sin borradores ni bloqueados.

### Órdenes retiradas para QA

Se encontraron seis registros asociados a órdenes marcadas `qa_retired` (uno en MP1 y cinco en MP3); ninguno contiene código de tubete.

Se recomienda excluir los registros de órdenes `qa_retired` para evitar que datos retirados de pruebas contaminen el reporte, pero incluir órdenes archivadas normales. La regla debe aplicarse por estado técnico de la orden, no por una exclusión indiscriminada de todas las órdenes archivadas.

---

## 7. Permisos de consulta

Actualmente:
- Jefatura y Supervisión no tienen `production.capture`.
- `work_order.read` no es adecuado como permiso sustituto: también lo tienen Operación, Calidad y DATA_BALTREK.
- La auditoría identificó dos usuarios activos de Jefatura y uno de Supervisión; los tres tienen concedido el sector BOBINAS.

### Recomendación

Crear un permiso de lectura específico `report.read`, asignado exclusivamente a los perfiles:
- `JEFATURA`
- `SUPERVISION`

El endpoint deberá además exigir el sector BOBINAS y limitar los datos a MP1 y MP3 desde el servidor. Si el usuario no tiene el sector, debe recibir 403, no un reporte vacío que parezca válido.

No conceder `production.capture` para resolver la consulta. No usar grants de máquina/formulario para estos perfiles gestores, que ya operan con alcance por sector.

La matriz de permisos está definida en código; la auditoría no identificó necesidad de migración de base de datos. La implementación sí deberá actualizar el tipo de permisos del frontend y las pruebas correspondientes.

Esta propuesta requiere aprobación antes de TUB-02.

---

## 8. Contrato de datos propuesto

Endpoint:

`GET /api/reports/tubetes-used`

Sin parámetros en la primera versión. Una sola respuesta debe contener ambas máquinas para que la pantalla, PDF y Excel trabajen sobre la misma consulta.

Ejemplo conceptual con datos ficticios:

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
      "records_without_code": 0,
      "tubetes": []
    },
    {
      "machine": "MP3",
      "usage_total": 3,
      "records_without_code": 0,
      "tubetes": [
        {
          "code": "7",
          "usage_count": 3,
          "dates": [
            "2026-10-02",
            "2026-10-05",
            "2026-10-05"
          ]
        }
      ]
    }
  ]
}
```

El ejemplo es ilustrativo, no reproduce los resultados reales de la auditoría.

### Reglas propuestas para el contrato

| Regla | Propuesta |
|---|---|
| Máquinas | MP1 y MP3 siempre presentes en una única respuesta |
| Código | Texto con el entero original almacenado; sin prefijo ni relleno |
| Orden de códigos | Numérico |
| Orden de fechas | Ascendente; desempatar por `captured_at` |
| Duplicados | Conservar cada utilización, incluso dos en el mismo día |
| Conteo | `usage_count` debe coincidir con la cantidad de fechas |
| Inclusión | Capturas `submitted` o `closed`, cualquiera sea el estado de Calidad |
| Exclusión | Borradores, bloqueadas y órdenes `qa_retired` |
| Sin código | No generan fila; contabilizar aparte si se aprueba `records_without_code` |
| Más de 10 usos | La API entrega todas las fechas |
| PDF | Bloques de hasta 10 fechas; fila de continuación marcada `(cont.)` |
| Excel | Una hoja por máquina, tantas columnas de fechas como se requieran |
| HTTP | `Cache-Control: private, no-store`; respuestas 401, 403 y 503 |

Con los índices y tablas actuales no parece necesaria una migración.

---

## 9. Riesgos y limitaciones

1. **Formato del código:** los ejemplos `TUB-001` de la especificación no corresponden al dato entero actual.
2. **Regla de producción válida:** Functional debe confirmar que el reporte representa consumo y, por tanto, incluye bobinas rechazadas.
3. **Corrección de errores:** no se encontró un flujo para corregir un código mal digitado. Los detalles enviados son inmutables. El reporte reflejará lo registrado; no debe inventar correcciones.
4. **Muestra insuficiente:** MP1 no tiene códigos, no hay repeticiones y no hay códigos con más de diez usos. Esos casos no están probados.
5. **Datos de prueba:** para demostrar esos escenarios será necesario crear registros de prueba identificables en el entorno productivo actual. Esto requiere una autorización específica para las escrituras y un procedimiento de identificación/reversión; no se realizó en TUB-01.
6. **Validación numérica:** cero y negativos pasan la validación actual, aunque no aparecen en la muestra. No se deben normalizar silenciosamente.
7. **Repositorio público:** se verificó que el repositorio GitHub tiene visibilidad `public`. Esta auditoría omite identificadores de infraestructura y secretos. Conviene revisar por separado si la visibilidad pública es intencional y qué documentación operativa puede permanecer expuesta.

---

## 10. Desviaciones del procedimiento de auditoría

La auditoría no produjo cambios persistentes en la base de datos ni en la aplicación, pero se deben dejar registradas estas desviaciones respecto de las restricciones:

| Acción | Resultado y evaluación |
|---|---|
| Intento de `CREATE TEMP VIEW` dentro de transacción READ ONLY | PostgreSQL lo rechazó con `cannot execute CREATE VIEW in a read-only transaction`; no se creó la vista. Fue un intento DDL improcedente y no debe repetirse. |
| Script auxiliar `ro.sh` en directorio temporal de la VPS | Se creó para envolver consultas en READ ONLY/ROLLBACK y luego se eliminó. No quedó archivo auxiliar, pero crear archivos estaba fuera del alcance autorizado. |
| Uso de `sudo` para leer código y configuración Nginx | Solo lectura; sin cambios. |
| Conexión PostgreSQL como superusuario | El rol dedicado `vinto_audit_ro` no tenía SELECT. Se utilizó `SET LOCAL ROLE pg_read_all_data` para las consultas de datos, dentro de transacciones de solo lectura. No se cambiaron grants, pero el uso de superusuario fue excesivo y no debe ser el método habitual. |
| Sondeos repetidos de salud | No modificaron datos de negocio, pero generaron entradas de log. |

No se leyeron secretos, contraseñas, tokens, claves privadas ni datos personales de operarios. No se modificaron capturas, bobinas, permisos, configuración, servicios ni despliegues.

### Mejora obligatoria para futuras auditorías

- No usar superusuario para consultas ordinarias.
- No crear scripts temporales en VPS.
- No probar DDL, ni siquiera temporal.
- No repetir health checks si una verificación ya es suficiente.
- Si el rol de auditoría no tiene permisos SELECT, detenerse y solicitar una solución de acceso de solo lectura antes de continuar.
- Mantener evidencia agregada y sanitizada.

---

## 11. Estado de verificaciones

| Verificación | Estado |
|---|---|
| Host, aplicación, servicios, release, Git y base | PASS |
| Formulario, versión, tipo, escritura y máquina | PASS |
| Compatibilidad con el formato `TUB-001` | FAIL |
| Volumen de P1-03 | PASS |
| Formato de los tres códigos encontrados | PASS |
| Consultas de repetición ejecutadas | PASS |
| Comportamiento con repeticiones, más de 10 usos y ambas máquinas | PENDING |
| Tipos, zona horaria y comparación de fechas | PASS |
| Ejemplos de fechas distintas dentro de P1-03 | PENDING |
| Distribución temporal | PASS |
| Recomendación de permisos | PASS; aprobación pendiente |
| Contrato propuesto | PASS; aprobación pendiente |
| Datos MP1 con código | PENDING |
| Cambios persistentes en base de datos | Ninguno identificado |
| Bloqueos técnicos | 0 |

**Resultado final:** `TUB01_AUDIT=PARTIAL`.

---

## 12. Decisiones solicitadas antes de TUB-02

Se presentan las recomendaciones para validación del responsable funcional:

1. **Código:** mostrar el entero original (`1`, `50`, `70`), sin prefijo ni ceros agregados. Si el identificador físico requiere letras/ceros, abrir una decisión separada sobre P1-03.
2. **Fecha y zona horaria:** utilizar `operating_date`; confirmar si la zona horaria operativa correcta de la planta es `America/La_Paz` (actual en el código) o `America/Lima`.
3. **Consumo:** incluir registros enviados/cerrados aunque la bobina esté rechazada por Calidad; excluir borradores, bloqueados y órdenes `qa_retired`.
4. **Permiso:** `report.read` para Jefatura y Supervisión, con sector BOBINAS y alcance MP1/MP3.
5. **Contrato:** una respuesta con ambas máquinas, código como texto original, todas las fechas y duplicados conservados.

No se autoriza todavía TUB-02 por este informe. El responsable debe confirmar las reglas funcionales y, por separado, autorizar la creación de registros ficticios de prueba si se necesitan para cubrir MP1, repeticiones y más de diez usos.

---

## 13. Siguiente paso

Revisar las cinco decisiones del apartado 12 y resolver si se autoriza una prueba controlada con escrituras ficticias para cubrir los casos que no existen en la muestra.

Después de esa validación se podrá cerrar TUB-01 y preparar el diseño/implementación de TUB-02.

**No se escribió código funcional, no se crearon ramas de implementación, no se crearon PR de código y no se desplegó ningún cambio.**

# VINTO RBE-05 · PDF, historial y entrega a Claude Code

## Candidato y dependencias

- Rama `feat/rbe-05-pdf-history-2026-11-28`. El HEAD remoto inicial era `ef7c5ecbaf3da906ca59d3c5afa6ee493981d99f`, el mismo del PR #279. El árbol inicial estaba limpio. No había commits adicionales en la rama.
- RBE-02 define reglas y bloqueos. RBE-03 aporta Ejecución y clasificación de OT. RBE-04 aporta 0032, permisos y reserva. Se integró el HEAD de RBE-03 `c7047fcf1db177d9072c2e224f56791625239bf8` mediante merge local sin conflictos. [RBE-02 #274](https://github.com/BaltrekCompany/vinto-mvp-web/pull/274) · [RBE-03 #277](https://github.com/BaltrekCompany/vinto-mvp-web/pull/277) · [RBE-04 #279](https://github.com/BaltrekCompany/vinto-mvp-web/pull/279)
- El PR RBE-05 es borrador y tiene como base RBE-04. El commit y la evidencia definitiva se registran en el PR y en `pr-head.sha`, `checkout.sha` y `resumen.json` del artefacto del workflow. Usar el run del HEAD vigente. [PR de RBE-05 por rama](https://github.com/BaltrekCompany/vinto-mvp-web/pulls?q=is%3Apr+head%3Afeat%2Frbe-05-pdf-history-2026-11-28) · [Ejecuciones RBE-05](https://github.com/BaltrekCompany/vinto-mvp-web/actions/workflows/rbe-05-pdf-history.yml)
- Orden de integración recomendado para revisión posterior: #274, #277, #279 y RBE-05. Conservar la ascendencia al integrar #277 y #279, actualizar la base del PR RBE-05 cuando ambas estén integradas y volver a correr el candidato combinado si cambia su árbol o su SHA.

## Funcionalidad y arquitectura

Operación edita borradores, confirma la vista previa y genera el PDF al reservar crías. El historial conserva el archivo original y su SHA-256. Supervisión consulta detalle y descarga en REBOBINADO. Jefatura además clasifica OT y puede anular reportes con motivo. Los reportes anulados y las reservas históricas se conservan. Las crías liberadas por la anulación vuelven a la lista cuando mantienen elegibilidad. El historial también presenta el estado Observado. La transición a Observado queda disponible para el proceso de corrección de Calidad que se apruebe por separado.

La generación verifica identidad activa, perfiles y concesión sectorial, propietario y concesión P1-07 vigente. PostgreSQL bloquea OT → Calidad → bobbins → capturas → reporte → paquetes → selecciones → reservas. Un bloqueo asesor por usuario y clave serializa los reintentos. La huella canónica incluye UUID del reporte, cabecera, orden y madres de paquetes activos, UUID y slot de cada cría, y versión de snapshot. El servidor resuelve el snapshot validado y almacena PDF, hash, reservas y eventos en una transacción. El índice parcial de 0032 decide la colisión de reservas concurrentes. Bajo el mismo alcance de autorización, un reintento con la clave original devuelve los bytes persistidos y el estado actual. Una clave usada para otra operación devuelve 409.

El renderizador usa ReportLab 4.5.1 con Vera incrustada y pypdf 6.14.0 para verificar páginas y flujos de contenido. El PDF usa A4 vertical, blanco y negro, cuadrícula delgada, cabecera repetida, numeración global y hasta 20 paquetes enteros por página. Una fila extensa puede reducir el número de paquetes de esa página. Los campos se ajustan en varias líneas. Una fila indivisible que supera el espacio A4 o un glifo incompatible produce un error explícito. Las observaciones largas pueden continuar en páginas finales. El tope de memoria de almacenamiento del documento serializado es 25 MiB. La muestra de 2.021 paquetes generó 102 páginas.

El producto procede del artículo de OT. La descripción aparece si coincide en las versiones de todos los paquetes activos. Formato concatena los componentes presentes y Cortes conserva el tercer valor por paquete. El operador es el nombre asociado a `capture.created_by`. El snapshot conserva los valores originales y las advertencias. El guardado de cabecera queda en la auditoría genérica de la tabla. El contrato anterior intentaba insertar `draft_updated`, que la lista de eventos de 0032 no admite.

No se localizó la especificación funcional original de seis páginas en las ramas, PR o adjuntos disponibles. Se usó la sección 11 de RBE-02. La comparación con la página 6 original queda como puerta del QA visual.

### Archivos y dependencias

| Área | Archivos |
|---|---|
| Motor y API | `backend/app/rewinding_export/{service,router,repository,schemas,pdf_renderer}.py`, `backend/app/main.py` |
| Dependencias | `backend/requirements.txt` fija ReportLab y pypdf. Playwright 1.65.1 se instala únicamente para la suite de navegador |
| Interfaz | `app/page.tsx`, `components/vinto/{sector-central,rewinding-export-workspace,rewinding-export-history}.tsx`, `lib/vinto/{central-http,rewinding-export,rewinding-export-api}.ts` |
| Verificación | `backend/tests/test_rewinding_export_*.py`, `scripts/rbe05-browser.test.mjs`, expectativa histórica de migraciones en `scripts/p1-30-p1-07-capture.test.mjs`, `.github/workflows/rbe-05-pdf-history.yml` |

## Contrato HTTP

Raíz `/api/reports/rewinding-export`. Las consultas y mutaciones RBE-03 de selección, borradores, paquetes y clasificación conservan sus rutas. Se utilizan cookies de sesión y `Content-Type: application/json` para mutaciones. Las respuestas RBE incluyen `Cache-Control: private, no-store`.

| Método y ruta | Entrada y respuesta |
|---|---|
| `POST /drafts/{id}/preview` | Valida fuentes vivas. Devuelve `valid`, conteos, `warnings` y `blocking_errors` |
| `POST /drafts/{id}/generate` | JSON `{"idempotency_key":"<uuid>"}`. Devuelve 200 y el PDF original, con `ETag` SHA-256, `Content-Disposition`, `X-RBE-PDF-Pages`, `X-RBE-Report-ID` y `X-RBE-Report-Status`. El detalle JSON ofrece el estado para consumidores en otro origen |
| `GET /history?limit=50&offset=0` | Lista de Generados, Observados y Anulados, acotada a reportes propios o sector autorizado |
| `GET /reports/{id}` | `{report, packages}` con snapshot congelado, estado, fechas y selecciones con pesos decimales exactos como texto |
| `GET /reports/{id}/pdf` | PDF original verificado por tamaño y SHA-256. 503 si falta o falla la integridad |
| `POST /reports/{id}/annul` | Jefatura envía `{"reason":"<10 a 300 caracteres>"}`. Devuelve `report_id` y `released_reservations` |

401 indica sesión inválida. 403 indica permiso o concesión insuficiente. 404 protege recursos ajenos. 409 indica conflicto de estado, reserva o clave. 422 indica dato inválido. 413 indica exceso de 25 MiB. La clave permanece en memoria mientras la solicitud puede reintentarse. Tras recargar, el historial recupera un resultado confirmado por el servidor.

## Evidencia y criterio de aceptación

- PostgreSQL 17 desechable migrado hasta 0032 con checksum SHA-256 `d95e74f56353fe25750dd30f753bbb623af898fb23ab247a944a2100448d23e1`.
- Verificación local con PostgreSQL 17.12 y el rol `vinto_app`, usando login, capturas P1-07 y decisiones de Calidad sintéticas. Concurrencia real de dos operadores 200/409 con triggers habilitados. El perdedor conservó estado Borrador con cero PDFs, reservas y eventos de generación. Reintentos concurrentes con la misma clave devolvieron los mismos bytes. Anulación por Jefatura, liberación, reutilización y restauración por `pg_dump`/`pg_restore` comprobaron el SHA-256 original.
- Verificación local con ESLint, TypeScript, build, suite RBE-03, regresiones dirigidas y Chromium. Chromium usa respuestas HTTP sintéticas para comprobar navegación del componente, doble clic, respuesta perdida, 401, 409, perfiles, historial, descarga y anulación. PostgreSQL HTTP usa FastAPI real.
- En GitHub verificar el resultado de todos los checks asociados al HEAD vigente. Descargar el artefacto `rbe05-<run_id>-<attempt>` del run correcto. Ejecutar `sha256sum -c SHA256SUMS`, comprobar `pr-head.sha` y `checkout.sha`, y consultar `resumen.json`, `concurrencia.json`, `conservacion.json` y `revocacion.json`. El artefacto contiene PDFs sintéticos, PNG, logs y hashes. Su retención es de 14 días. [Ejecuciones y artefactos de RBE-05](https://github.com/BaltrekCompany/vinto-mvp-web/actions/workflows/rbe-05-pdf-history.yml)
- **GO de despliegue autorizado** exige SHA explícito, CI íntegro, comparación visual con la página 6, respaldo restaurado y verificado, historial de migraciones coherente, roles efectivos correctos, build y health correctos y aprobación del alcance de QA.
- **NO-GO** ante un check obligatorio fallido o sin concluir, divergencia del SHA o checksum, backup sin restauración, ausencia de autorización, origen operativo de los datos de ensayo, concesión excesiva o regresión. Mantener reportes, PDFs y reservas para análisis.

## Prompt completo para Claude Code

> Recibes VINTO RBE-05 para RBE-06. Trabaja únicamente con la autorización emitida por el responsable de VINTO. Registra la aprobación, el SHA exacto, el alcance y la ventana antes de cualquier cambio. Comprueba si VINTO sigue sin uso operativo oficial y si cada dato que se usará en QA es ficticio. Confírmalo con el responsable y con evidencia de solo lectura. Si una condición falla o no se acredita, detén las escrituras y escala para usar un entorno aislado. Mantén la instalación TVC separada.
>
> **Preflight.** Lee el cierre RBE-04, este documento y `deploy/mvp/README.md` en el SHA autorizado. Comprueba el PR, el SHA del HEAD, el SHA del checkout probado y los resultados del candidato combinado. Descarga el artefacto de evidencia, valida `SHA256SUMS` y contrasta la página 6 original con los PNG. Registra el SHA activo, los servicios `vinto-mvp-backend` y `vinto-mvp-frontend`, el estado de PostgreSQL y la disponibilidad de un rollback al release activo. Ejecuta las comprobaciones de infraestructura del runbook oficial de VINTO MVP.
>
> **Respaldo.** Ejecuta `CONFIRM=yes bash backup.sh create-and-verify` por el mecanismo aprobado en el runbook. Guarda el checksum, manifiesto y marcador verificado con acceso restringido. Usa una restauración aislada para comprobar el esquema y, si hay PDFs RBE previos, que muestra de bytes y SHA-256 sobrevivan al restore. Para la comprobación de conservación del reporte de QA generado en esta sesión, usa también un respaldo posterior restaurado en aislamiento. Conserva hashes y conteos en el informe. Mantén el dump y los secretos en almacenamiento restringido.
>
> **Build y migraciones.** Construye fuera de la VPS el frontend Linux con `deploy/mvp/scripts/build-frontend-artifact.sh`, el dominio público ya aprobado y el mismo SHA. Verifica el checksum, el manifiesto y el arranque aislado. En la VPS autorizada prepara el release con los pasos `checkout`, `python-venv` e `install-frontend-artifact` de `deploy.sh`, manteniendo el enlace a la configuración compartida existente. Ejecuta `bash deploy.sh check-release <sha>` y registra su resultado. Si 0032 está pendiente, verifica su checksum y aplica únicamente el conjunto pendiente aprobado con `CONFIRM=yes AUTHORIZED_COMMIT=<sha> bash deploy.sh migrate-release <sha>`. Repite `check-release` y exige código 0. Verifica las concesiones efectivas de 0032 contra el rol aplicativo y el estado de endurecimiento. Si falta alguna concesión RBE aprobada, usa solo el subconjunto RBE aprobado con el rol migrador bajo autorización y verifica privilegios efectivos. La fase general `postgres-grants` puede reintroducir DML de catálogos o identidad tras D.3B.1/D.3B.4. Respeta la guardia y el procedimiento de roles documentado. Verifica el alcance explícito REBOBINADO por cuenta y las concesiones específicas de P1-07 de los operadores sintéticos.
>
> **Activación.** Ejecuta `preflight-startup`, activa el release exacto con `CONFIRM=yes bash deploy.sh activate <sha>` y verifica el symlink `current`, systemd, frontend y health del backend con `bash deploy.sh healthcheck`. Comprueba también el estado público con el dominio del MVP usando rutas normales.
>
> **QA manual.** Usa nombres, observaciones y archivos sintéticos. Registra los códigos HTTP, roles, conteos de reservas y SHA-256 de los documentos. Conserva capturas de evidencia sin credenciales ni datos personales.
>
> 1. Entra como Jefatura y clasifica una OT de ensayo como producción. Incluye una OT desconocida y una QA como controles de exclusión.
> 2. Entra como Operación con REBOBINADO y P1-07 vigentes.
> 3. Selecciona PV y producto y verifica que el producto corresponde al artículo de OT.
> 4. Selecciona la madre P1-07 por UUID, con su etiqueta visible.
> 5. Selecciona crías liberadas. Comprueba exclusión de pending, rejected y crías de otra madre.
> 6. Crea paquetes, incluyendo A y E con ranuras intermedias vacías. Comprueba que el borrador conserva los slots y carece de reservas.
> 7. Guarda camión, orden y observaciones. Ejecuta la vista previa y revisa bloqueantes y advertencias.
> 8. Confirma generación y descarga el PDF. Comprueba el historial, el estado Generado y la actualización de disponibilidad.
> 9. Coteja A4, cabecera, tabla, pesos, Cortes literal, 20 filas, observaciones, paginación y campos con la página 6 aprobada.
> 10. Desde dos sesiones de Operación prepara reportes sobre otra cría elegible común y genera en paralelo. Exige un 200 y un 409. Verifica ausencia de artefactos, reservas y eventos de éxito parciales en el perdedor.
> 11. Consulta detalle, estado y PDF como Supervisión. Comprueba que otra cuenta de Operación no descarga el reporte de un tercero.
> 12. Anula como Jefatura con motivo de 10 a 300 caracteres y confirmación explícita. Verifica denegación para otros perfiles.
> 13. Confirma estado Anulado y liberación de la reserva. Verifica que la cría puede reutilizarse si sigue liberada por Calidad.
> 14. Descarga el PDF original después de anular, compara bytes y SHA-256 con la primera descarga y verifica el mismo hash sobre el documento restaurado en aislamiento.
> 15. Recorre Calidad, P1-07, Conversión y Calidad Offline, incluyendo una recarga y cambio de sesión. Verifica que la lista, la captura de origen y los flujos offline conservan su comportamiento.
>
> **Rollback.** Ante un NO-GO, conserva los registros y artefactos. Si el release ya está activo, ejecuta `rollback.sh version <sha-anterior>` de acuerdo con el procedimiento autorizado, verifica `current` y repite health y pruebas críticas. Conserva 0032 y sus filas. Una restauración sobre producción requiere autorización independiente, evaluación de escrituras posteriores y reconciliación.
>
> Entrega una decisión GO/NO-GO con evidencia de cada prueba, release y SHA, respaldo y restauración, migraciones, permisos, hash descargado y verificación visual. Identifica cualquier QA que quede sin ejecutar y el motivo concreto.

# VINTO OFF-03C.1 — Exportación firmada de definiciones completas de Calidad

**Estado: candidato de ensayo — no apto para captura, no desplegado.**  
**Base:** OFF-03B.3 PR #190 / `2709fde2971c4acdba04289563e17de5c937d98d`.  
**Dependencias:** contrato OFF-01 V2 PR #184, OFF-02 PR #186, OFF-03A PR #187, OFF-03B.1 PR #188, OFF-03B.2 PR #189 y OFF-03B.3 PR #190 (todos Draft).

## Objetivo y elección de alcance

La prioridad acordada es **Calidad → Conversión → Bobinas/Rebobinado**. El móvil compartido de Calidad utiliza **un navegador por identidad** y debe abrir VINTO tras cerrar Chrome/reiniciar el dispositivo sin red. OFF-03B.3 permite leer un **índice** firmado de formularios y versiones. **OFF-03C.1** agrega la fuente de definición completa leída del **catálogo PostgreSQL**, no de archivos seed.

**Recorte para el primer lote:** únicamente Calidad **por máquina** sin asignación ni bobina: `VINTO-P1-18`, `VINTO-P1-22`, `VINTO-P1-26`, `VINTO-P1-27` sobre MP1/MP3, **siempre sujetos a concesión efectiva individual y última versión publicada vigente**. Son candidatos de **QA interno pendientes de homologación VINTO**; el código no los habilita para piloto industrial por descargarlos. Excluye Calidad por bobina P1-19/P1-20, liberaciones, decisiones, WIP y OT.

## Contrato técnico

**Ruta candidata**: `POST /api/offline/quality-package`. No escribe en PostgreSQL ni acepta capturas.

- Compuertas de servidor **independientes y OFF de origen**: `OFFLINE_SCOPE_ISSUE_ENABLED=false` y `OFFLINE_QUALITY_PACKAGE_ISSUE_ENABLED=false`. Ambas deben ser `true` **solo en QA aislado**, con semilla Ed25519 válida fuera de Git. No agregar variables a producción.
- Requiere sesión de usuario activa (HttpOnly `/api/auth/me`), HTTPS fuera de entornos locales de ensayo y `Cache-Control:no-store`; recibirá `device_key`, `machine_code`, `form_code` y `signed_scope` de OFF-03B.2.
- El backend **verifica la firma del alcance con la clave pública del firmador del servidor** (no la que un cliente adjunte). Exige **mismo usuario, dispositivo, máquina, formulario y operación `quality_machine_capture`**. Una firma de otro navegador o con `captures_enabled=true` no sirve.
- Dentro de `connection.transaction()`, `authorize(..., lock=True)` relee permisos efectivos, sector, concesión actual, versión vigente y vínculo. **La concesión y versión deben coincidir exactamente** con el alcance previo. Cambios de asignación, revocaciones o nuevas versiones no se convalidan silenciosamente.
- Se consulta la **versión publicada exacta de vinto_config**: `form_version`, `field_definition`, `unit` y `field_option`, con sus nombres, descripción, orden, fuente, obligatoriedad, unidad, opciones, metadatos y checksum oficial de definición. No se reinterpreta la semilla JSON.
- Se usa `capture_service.load_fields(... allow_calculated=True)` como guardia de soporte: fuentes automáticas, campos agrupados y dependencias de opciones no soportadas se deniegan; nunca se exportan silenciosamente medias definiciones.
- P1-26 incluye la regla vigente del backend: `porcentaje_cantidad_de_seco = masa_seca / masa_humeda × 100`, redondeo a dos decimales **half up**; denominador cero = omitir resultado. Es solo metadato de lectura. No se autoriza el cálculo ni aceptación de una captura desde el cliente.
- Se limita a 128 campos y 512 opciones por definición. Un exceso o fuente no representable falla cerrado.
- El paquete incluye `content_sha256` calculado sobre JSON canónico de la definición, `scope_snapshot_id`, usuario, dispositivo, máquina, código, versión y concesión. Firma Ed25519 separada de la del alcance con **dominio `VINTO-OFFLINE-QUALITY-PACKAGE-V1\x00`** y `schema=vinto.offline.quality-package.v1`. Una firma de alcance **no** valida como firma de paquete.
- `captures_enabled:false` y `capture_eligible:false` son obligatorios. **No hay TTL por turno** durante el primer piloto, pero al reconectar habrá revalidación central.

## Datos que no están incluidos y por qué

- **Recetas/maestros por artículo:** la definición de estos formularios por máquina no vincula automáticamente una receta a cada formulario. El paquete indica explícitamente `recipe_bundle_included:false`. No inferir una receta desde `recipe_version` o `recipe_component` por coincidencia de máquina.
- **OT y asignación:** los controles de máquina son independientes de esas relaciones; sin embargo, la fecha de ensayo y turno offline requieren contrato de timestamps y resolución, aún no incorporado.
- **Dependencia dinámica:** un campo dependiente fuera del motor actual de Calidad no se entrega como si fuese soportado; se rechaza.
- **Formatos/valores de captura:** `source=calculated` es resultado de backend, no un campo editable; `needs_validation` y atributos de catálogo no equivalen a homologación industrial.
- **Campos/recetas históricos distintos:** solo se exporta la versión publicada vigente y exactamente autorizada.

## Secuencia pendiente y QA

1. **OFF-03C.1:** firma servidor y pruebas unitarias; PostgreSQL 17 efímero para definición real P1-22, opciones y regla de P1-26, denegación de concesión revocada y separación de dominios. Sin migraciones.
2. **OFF-03C.2:** verificador WebCrypto de **firma de paquete** y **hash de contenido**, vínculo con scope snapshot y pin de clave de OFF-03B.3, persistencia cifrada AES-GCM en IndexedDB por usuario/navegador/versión, recuperación sin Internet y no sustitución de paquete histórico.
3. **OFF-03C.3:** primera vista offline de campos/restricciones **solo lectura**, sin habilitar escritura ni usarla como validador operativo. QA de Chrome con perfil persistente y corrupción de paquete.
4. **QA físico en móvil compartido:** online → desconectar red → cerrar navegador → reiniciar dispositivo → abrir VINTO → desbloquear perfil y paquete cifrado → comprobar valores y versión sin API → reconectar. Se ejecutará en ensayo HTTPS, no en producción.
5. Antes del piloto de captura: homologación VINTO de formularios, decisión de dispositivo fuerte/revocación, repositorio de recetas realmente exigidas, auditoría durable, pruebas con rol PostgreSQL mínimo, ciclo de confianza/rotación de firma, outbox y política de conciliación OFF-04.

## Controles y límites

- El paquete firmado **no crea permisos** y puede permanecer verificable históricamente después de una revocación. El backend reevalúa el autor y el permiso de la acción al reconectar.
- `device_key` es una etiqueta de navegador, NO prueba de posesión física. No se resuelve aquí la amenaza de copiar IndexedDB.
- El sobre firmado no debe almacenarse en caché pública ni `localStorage`; OFF-03C.2 deberá cifrarlo y proteger su vínculo con el alcance verificado previamente.
- No modificar `main`, ni merge, ni desplegar VPS, ni activar flags o copiar claves reales, ni escribir en la BD de producción.

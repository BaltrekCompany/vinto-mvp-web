# FOFF-03 — Avance de implementación unificada, 2026-11-27

**Rama:** `feat/foff03-conversion-offline-complete-20261127`  
**PR único:** [#273](https://github.com/BaltrekCompany/vinto-mvp-web/pull/273) (Draft).  
**Implementación NO finalizada ni desplegada.** Flags OFF por defecto y sin migración aplicada en VPS.

## Desarrollo incorporado a este PR

- Paquete referencial de Conversión construido a partir de **definiciones publicadas de vinto_config**, campos, opciones, grupos, recetas por artículo y pesos nominales versionados de pallet. No se genera un correlativo de pallet local, ni se inventan recetas.
- Digest SHA-256 del paquete incorporado en el contexto de preparación firmado con Ed25519. Verificador navegador comprueba firma, identidad, asignación, versión y digest del paquete.
- Enrolamiento de Operación devuelve, cuando están configuradas, dos claves públicas anclables por conexión HTTPS autenticada (preparación y CAPTURE), no semillas.
- **Autoridad CAPTURE separada**, con semilla, esquema y dominio propios, y verificador independiente de la preparación `preparation_only`. La firma de preparación por sí sola no permite registrar capturas.
- Receptor `POST /api/offline/production/conversion/captures` con flag independiente OFF, sesión del autor original, hash de valores, firma de preparación y firma CAPTURE, concesiones efectivas revalidadas y llamada al servicio central con `gate_for(...,"enforce")` dentro de su transacción.
- Los reintentos usan `capture_id` estable y pasan por la lógica de idempotencia del servicio; no se confirma un duplicado basándose solo en los encabezados. El receptor verifica el registro persistido.
- Migración aditiva `0032_offline_conversion_review.sql` para recibos técnicos inmutables. Una asignación vencida, cerrada, línea no iniciada o autoridad caducada recibe un 202 de **revisión técnica**, no un éxito industrial.
- El proceso 202 y el registro productivo comparten lock por `capture_id` para reducir carreras de concurrencia; las pruebas de PostgreSQL de esta ruta aún deben completarse.
- Cliente: verificador CAPTURE Ed25519, almacén IndexedDB cifrado y aislado de Calidad para envíos pendientes, función de sincronización únicamente con sesión de autor original y confirmación explícita 200/201/202 vinculada al SHA del envío.
- Pruebas unitarias de backend/frontend para firmas, permisos, fragmentación de identidad, falta de IndexedDB, recibos y almacenamiento (parcial).

## Riesgos/puntos aún abiertos antes del gate de merge

1. **Falta conectar el almacenamiento y la cola con los formularios originales P1-16, P1-11, P1-12 y P1-13.** En especial autoguardado, cierre/reapertura, grupos repetibles y pantallas móviles deben funcionar con pruebas reales.
2. Falta flujo de preparación completo en dispositivo: persistir perfil y pins protegidos, obtener las asignaciones realmente seleccionables, descargar contexto, verificar ambas firmas, guardar bundle cifrado; debe operar tras pérdida de red sin grants inventados.
3. Falta la matriz real de pruebas PG17 para el receptor y la migración 0032, incluyendo carreras de captura/202, reintentos idénticos, revocación, expiración, cambios de receta/peso/OT, idempotencia de pallets y aislamiento de autores.
4. D03 **aún no tiene interfaz de gestión/resolución de revisiones**; solo persistencia y consulta. No declarar resuelto un registro 202.
5. Verificar correctamente la semántica de fecha de planta `America/La_Paz` y captura tardía; el timestamp del navegador **no es prueba** de turno.
6. El CI del SHA actual debe concluir en verde; resultados de commits anteriores no son válidos para certificar este.
7. Hacer revisión de seguridad concurrente antes de habilitar flags, y QA móvil de formularios y PWA. Producción contiene datos ficticios, pero necesita backup restaurable y rollback.
8. No hacer merge ni desplegar la migración o activar un flag mientras la entrega funcional esté incompleta.

## Metodología

No se abren PRs por subincremento. Todo FOFF-03 permanece en el **mismo PR #273** hasta cerrar backend, interfaz, pruebas, documentación y QA de despliegue. FOFF-04 Rebobinado no empieza antes de la prueba productiva exitosa de Conversión.


## Integración de preparación en Ejecución (avance posterior)

- Componente `components/vinto/foff-conversion-preparation.tsx`, montado dentro del `Execution` original del sector Conversión, solo cuando hay una asignación validada por el backend y la línea permite captura.
- Formulario seleccionado por código/versión de la **disponibilidad autorizada**, sin lista fija de máquinas ni OT elegida manualmente.
- `lib/vinto/foff-conversion-profile.ts`: perfil local separado de Calidad, con vault AES-GCM, clave de Operación y dos pins Ed25519 que no pueden sobrescribirse silenciosamente, incluido acceso concurrente en pestañas.
- `lib/vinto/foff-conversion-prepare.ts`: sesión original, enrolamiento autenticado, comparación de pins, firma de preparación, firma CAPTURE, SHA-256 de paquete referencial; guarda envelopes y contexto cifrados en IndexedDB únicamente tras verificar.
- Tests de perfil, aislamiento, selección inválida y no-fallback sin IndexedDB en `tests/foff-conversion-device-preparation.test.ts`.
- **No se ha montado ningún editor offline de Conversión**: siguen pendientes adaptar los formularios originales P1-16, P1-11, P1-12 y P1-13 a autoguardado, recuperación, cierre, cola y sync. El botón de preparar solo crea un paquete cifrado cuando los flags estén habilitados, y por defecto permanece bloqueado por el backend.
- No habilitar ninguna bandera ni declarar FOFF-03 lista hasta superar CI del HEAD más reciente, pruebas integrales PG17 y QA móvil. No hay cambios de VPS ni migración aplicada.


## Implementación del editor de capturas y recuperación sin red (27/11, siguiente iteración dentro de FOFF-03)

- **20/20 workflows PASS** comprobados para el commit inicial `3834640d`, antes de los cambios que se describen aquí. **No atribuir ese PASS al HEAD actual.**
- `lib/vinto/foff-conversion-draft-store.ts`: borradores aislados en IndexedDB con AES-GCM, AAD ligado al usuario/dispositivo/preparación/formulario/versión, `capture_id` UUID v4 estable, incrementos de revisión y compare-and-swap por transacción para impedir sobrescrituras entre pestañas.
- `lib/vinto/foff-conversion-form-schema.ts`: definición estricta derivada de campos y grupos **publicados en backend**, tipos `text`, `textarea`, `integer`, `decimal`, `date`, `time`, `boolean`; opciones, campos obligatorios y filas repetibles; desconocidos/no manuales se rechazan, sin sustituir validación industrial de servidor.
- `components/vinto/foff-conversion-workspace.tsx`: recuperación en el móvil por clave local del dispositivo previamente enrolado; visualización de los formularios preparados, firmas Ed25519 y digest de paquete verificados, borrador cifrado, autoguardado diferido, captura en cola inmutable, reintento únicamente en línea con sesión del autor original y estados `pending/synced/requires_review`.
- `lib/vinto/foff-conversion-profile.ts`: consulta de perfiles preparados del dispositivo; no crea sesión del backend ni concede permisos nuevos.
- `app/page.tsx`: acceso a **Conversión Offline** sin desplazar Calidad Offline, también cuando falla conexión de sesión. El editor no inventa maquinaria ni asignaciones: todas las preparaciones nacen en la Ejecución original con OT vigente y quedan cifradas.
- Se admiten paquetes ya vencidos para **recuperar su contenido**, pero su posterior envío corresponde a **revisión 202** del receptor, sin transformar el reloj del dispositivo en autoridad de turno.
- Se añadieron pruebas de formato, normalización de grupos, cifrado sin fallback y validación local de contexto. El flujo funcional P1-11/P1-12/P1-13/P1-16 con datos de las formas reales del backend requiere ensayo de navegador y dispositivo.

### Bloqueos para autorizar producción

1. El estado de GitHub Actions debe verificarse sobre el **HEAD actual** tras el editor y las modificaciones de `app/page.tsx`; cualquier fallo requiere corrección y nuevo CI.
2. Pruebas de integración con IndexedDB real y Safari/Chrome móvil: clave correcta/incorrecta, refresco offline, cierre/reapertura, autoguardado, colisión de pestañas, expiración, reconexión, pérdida de ACK, autor distinto.
3. Receptor y migración 0032 en PostgreSQL 17 aislado: revisiones 202 realmente persistidas, idempotencia de captura y pallet, control de revocación, permisos y cambio de turno.
4. Auditoría de concurrencia y UX móvil en entornos controlados; si se obtienen pruebas suficientes, actualizar el PR y preparar respaldo, rollback y activación **solo de Conversión**.
5. No habilitar `offline_conversion_capture_enabled`, `offline_conversion_preparation_enabled` ni `offline_production_enrollment_enabled` mientras existan bloqueos; **ningún despliegue realizado**.


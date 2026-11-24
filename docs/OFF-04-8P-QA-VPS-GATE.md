# VINTO OFF-04.8P — Gate de ejecución QA aislado (23-11-2026)

**Autorización del usuario:** preparar y ejecutar QA final de captura offline de Calidad SOLO en QA, con respaldos y rollback. No autoriza merge, despliegue a producción, modificación de datos reales, cambios a otras áreas, ni cambios de permisos fuera del par de prueba.

## Estado probado en CI
- PR #246 Draft; commit `7cce82f85e84ac64fa5a533ca80b6e7f1e74ca52`, 15/15 workflows PASS.
- 10 formularios Calidad (4 máquina, 6 bobina F3) pasan endpoint HTTP aislado y escritura `vinto_txn.capture` con MF-13, autor original, verificador Ed25519 y validación central sobre DB descartable.
- Chrome real (CI) valida IndexedDB cifrado, cierre/reapertura, reinicio del navegador y concurrencia de pestañas. El ensayo cliente con reconexión usa fetch simulado.
- **NO equivale a QA funcional en servidor**. Actualmente `backend/app/main.py` NO monta `create_operational_quality_router`, `issue_capture_scope` carece de endpoint y `createOperationalQualityExperience` no está montado en pantalla de la aplicación.

## Fase A — Preflight, estrictamente de solo lectura
Responsable: agente Codex/Claude autorizado con acceso VPS QA, nunca producción.

1. Capturar referencia Git y SHA del candidato, confirmar árbol limpio; verificar que `qa-vinto-mvp.baltrekservices.com` resuelve a QA y no reenvía tráfico a producción. Confirmar `APP_ENV=qa` y **base real efectiva** de los servicios QA; no imprimir cadenas de conexión, secretos, cookies o tokens.
2. Verificar aislamiento del PostgreSQL QA y servicio/puerto QA, recursos, certificados TLS, Nginx, Basic Auth y estado de health. No inferir conexión a QA solo por DNS. Informar los nombres efectivos del DB/servicio y SHA sin credenciales.
3. Verificar inventario de migraciones efectivas y `to_regclass('vinto_offline.capture_receipt')` y `to_regclass('vinto_offline.capture_scope_authority')`. Los SQL `proposed_0032...` y `proposed_0033...` **no son automigraciones**. No ejecutar nada sin gate de backup y sin confirmar que la base es exclusivamente QA.
4. Revisar rol `vinto_app` y sus privilegios para `vinto_offline` y `vinto_txn`, además de las protecciones MF-13. No elevar permisos para que un ensayo pase.
5. Comprobar **tres dependencias para QA físico**: (a) endpoint autenticado para emisión CAPTURE de `issue_capture_scope` —no confundir con `/api/offline/scope` read-only—; (b) composición opt-in del router `create_operational_quality_router`; (c) pantalla/browser opt-in que arranca `createOperationalQualityExperience` contra el mismo origen y sesión, con pin de firma anclado y claves localmente cifradas. Verificar presencia efectiva de cada una en el despliegue QA candidato.
6. Certificar captura de backup de QA recuperable y verificación de restauración aislada antes de cualquier cambio de DB/servicios. No respaldar ni leer valores industriales de producción. Registrar hashes y destino privado del respaldo, sin exponer contenidos.

**STOP / NO-GO:** si (a), (b) o (c) faltan, producir diagnóstico `OFF048_QA_PREFLIGHT=BLOCKED_MISSING_WIRING` y NO aplicar SQL/servicios. Si DB no está probadamente aislada, `OFF048_QA_PREFLIGHT=BLOCKED_DB_ISOLATION`. Si falta backup verificable, `OFF048_QA_PREFLIGHT=BLOCKED_BACKUP`.

## Fase B — Integración mínima, solo si el gate A prueba los requisitos
- Resolver los cables faltantes **en GitHub PR #246 Draft**, con flags QA OFF por defecto, endpoint de CAPTURE solo para principal autenticado y MF-13 (nunca grant por paquete read-only), y test negativo de flag OFF/401/403.
- Ejecutar CI hasta PASS. No usar claves/credenciales de prueba en el repositorio. Nunca copiar claves de producción a QA.
- Para activación QA: aplicar migraciones aisladas con backups previos, sin alterar la historia `backend/migrations` ni permitir ejecuciones dobles de propuestas. Verificar el rol/objeto correcto y registrar SQL checksum; cualquier error requiere rollback QA.
- Habilitar URL y pantalla QA solo para el piloto ficticio, sin exponer usuarios/operaciones productivas. Prohibido activar servicio principal por accidente.

## Fase C — Pruebas QA funcionales (datos ficticios)
1. Login online y descarga de metadatos firmados + permisos CAPTURE, usuario ficticio CALIDAD autorizado y máquina MP1.
2. Desconectar; iniciar captura de máquina; autoguardar; cerrar pestaña; reiniciar navegador; desbloquear con el mismo dueño: íntegra y cifrada.
3. Guardar captura: un `capture_id` permanente, una fila pending y una fila queue; no envío offline.
4. Reconectar con usuario diferente: no POST, queda pendiente. Reautenticar al autor original: sync automática; verificar HTTP 201 y `operational_registered=true`, `capture_id` en `vinto_offline.capture_receipt` y `vinto_txn.capture`, status submitted; GET reconciliación y reintento idempotente.
5. Repetir por bobina F3 de QA (P1-19), con digest y contexto histórico correctos. Documentar matriz 10/10 usando ensayos SQL automatizados y una muestra completa UI por tipo máquina/bobina; no volver a inventar formularios.
6. Revocar autorización MF-13; un envío no puede crear registro operativo; excepción a revisión sin destruir pendiente. Probar caída/reintento, dos pestañas, sesión caducada.
7. Confirmar cero aprobaciones, rechazos y liberaciones automáticas; la actividad offline se limita a captura de datos.
8. Deshabilitar flags QA y confirmar rutas de captura no accesibles; backups y producción intactos.

## Criterio de cierre
Emitir `OFF048_QUALITY_OFFLINE_QA=PASS` **solo** con evidencia de A+B+C, CI PASS del candidato, trazabilidad de recibo a captura operativa, y pruebas de reinicio/reconexión en navegador contra QA. En cualquier otro caso `PARTIAL` o `BLOCKED` con causa exacta. No afirmar que está en producción. No fusionar PR #246 automáticamente.

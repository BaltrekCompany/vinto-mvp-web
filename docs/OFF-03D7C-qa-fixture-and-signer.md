# VINTO OFF-03D.7C — Contrato de fuente de referencia, usuario Calidad QA y firma offline

**Fecha: 18-nov-2026. Estado: desarrollo GitHub + posible inspección VPS READ ONLY.** Prohibido hacer seed, publicar versiones, crear usuarios/concesiones, generar claves persistentes, activar flags o exponer servicios en este PR. Se conserva en Draft sobre OFF-03D.7B, sin merge a main.

## 1. Entrada verificada D7B

- Codex informó ejecución de `OFF-03D.7B` en la VPS: auditor del rol `vinto_app` PASS, 31 migraciones sin cambios, permisos mínimos y login real PASS, `NO_DATABASE_WRITES=PASS`.
- HTTPS QA válido con certificado Let's Encrypt (17-nov-2026 a 15-feb-2027); `/qa-ready` HTTP 200, pero `/` y `/api/` HTTP 404, sin upstream conectado al piloto.
- **BLOQUEANTE para habilitar acceso web:** el vhost QA no mostró controles `auth_basic`, `allow`, `deny` ni una restricción equivalente demostrada. TLS y 404 no constituyen autorización. No configurar upstreams hasta aprobar VPN/allowlist o mecanismo equivalente con pruebas negativas desde red no autorizada.
- 3200/8200 libres pero no reservados. Node 20 piloto intacto, Node 22/pnpm 11 todavía NO instalados.
- CI D7B `44326059744` PASS (2/2): arranque real Vinext Node standalone y auditor. No demuestra funcionamiento de API/DB/web en VPS.

## 2. La fuente de datos y el alcance QA, sin copiar datos operativos

Existe el bundle de referencia versionado `backend/seed_data` con `manifest.json`. No se trata de un dump del piloto ni de mediciones/OT/capturas. Es un conjunto de **definiciones y catálogos del repositorio**, derivados históricamente de especificaciones del proyecto; NO se deben describir todos esos catálogos como datos ficticios. Es correcto utilizarlo como fuente de definiciones para una prueba interna, sujeto a revisión funcional y licencias/aprobaciones pertinentes.

`app.seed.bundle.load_bundle()` comprueba SHA256, tamaños, manifest, conteos y referencias. `app.qa_offline_fixture_contract` añade aserciones estrictas:
- Perfil existente `CALIDAD` y permiso funcional `quality.capture`; sector `BOBINAS`.
- Máquinas `MP1` y `MP3`, ambas en `BOBINAS`.
- Exactamente las cuatro definiciones candidatas por máquina `VINTO-P1-18`, `VINTO-P1-22`, `VINTO-P1-26`, `VINTO-P1-27`, con área `quality`, vínculo MP1/MP3, versión positiva y checksum por definición.
- Política explícita `MACHINE_QUALITY_FORM_CODES` admite esos códigos en el código, sin que ello conceda autorización individual al usuario.
- Usuario sintético futuro propuesto: `qa.offline.calidad`, nombre visible `Calidad QA Offline (sintetico)`, perfil `CALIDAD`, sector explícito `BOBINAS`. No contraseña en Git ni en el artefacto.
- **Concesión efectiva** de cada par máquina/formulario NO surge automáticamente del perfil ni del sector. Es necesaria una concesión explícita `user_machine_form_grant`, verificable mediante el motor `authorize`. No adjudicar pares extra.

**Hallazgo verificado en CI PostgreSQL 17 efímero (D7C2):** el importador oficial `backend/app/seed/reference.py` primero inserta `form_version` como `draft`, añade sus campos y después ejecuta `UPDATE ... status='published'` **en la misma transacción**. Por tanto, una importación completa del bundle oficial publica automáticamente las cuatro versiones. Esto **no** demuestra que QA real ya esté importada, ni concede autorizaciones al usuario, ni significa homologación industrial. Deben verificarse checksums, área, asociación con MP1/MP3 y autorización antes de ensayos físicos. No ejecutar un UPDATE manual.

## 3. Orden sugerido para las futuras operaciones D7C (NO AUTORIZADAS AQUÍ)

1. Inventariar por **consulta SQL solo lectura** estado actual de QA: migraciones=31, cuentas, perfiles, sectores, versiones publicadas, lotes de importación, grants. No imprimir nombres/UUID/hash/filas: solo estado agregado EMPTY vs EXISTING.
2. Revisar origen y checksum del bundle en el commit D7C aprobado. Probar `import_reference.py --target dev` como dry-run apuntando exclusivamente a `vinto_qa_offline`, mediante rol `vinto_reference` y modo endurecido. Un dry-run sin conflictos no autoriza `--apply`.
3. Por separado, ejecutar **únicamente mediante nuevo procedimiento reversible, con respaldo POST-DDL reciente y autorización expresa**, importación del bundle de referencia desde GitHub. Mantener un control de rollback frente a datos previos en QA. **No se debe restaurar el respaldo PRE-DDL B2 sobre el esquema migrado**.
4. Verificar que la importación aprobada publicó automáticamente las cuatro versiones exactas y revisar homologación, checksums, área y asociaciones máquina. No repetir la publicación por SQL manual.
5. Crear exactamente una identidad sintética y credencial efímera QA con Argon2id, no reutilizar usuarios reales. Conceder solo `CALIDAD`, `BOBINAS`, MP1/MP3 y las combinaciones de esos cuatro formularios que autorice la revisión funcional. Registrar plan de revocación y fin de prueba; no exponer credenciales en respuestas ni logs.
6. Recién después, configurar la semilla Ed25519 de 32 bytes **aleatoria exclusiva QA**, en secreto protegido y con `OFFLINE_SCOPE_ISSUE_ENABLED` y `OFFLINE_QUALITY_PACKAGE_ISSUE_ENABLED` inicialmente false. Verificar clave pública y ancla de confianza por enrolamiento autenticado HTTPS; **no confiar solo en la clave pública recibida dentro del sobre**.
7. Habilitar los dos flags exclusivamente para ensayo de lectura y luego deshabilitar. Mantener bloqueo de escrituras operativas del middleware D7A, sin OFF-04 captura/sync/outbox/aprobaciones.

## 4. Pruebas entregadas por este PR sin conexión a DB

- `backend/app/qa_offline_fixture_contract.py`: carga y valida manifest oficial y los pares/roles admitidos. **No conecta con PostgreSQL, no crea usuarios ni firma paquetes.**
- `backend/tests/test_off03d7c_qa_fixture_contract.py`: pruebas negativas para ausencia de perfil, cambios de máquinas/formularios y bundle marcado como candidato. Prueba Ed25519 con clave **efímera solo en memoria de CI**, sin almacenar ni imprimir seed; valida clave pública anclada, adulteración y separación de dominios para scope vs paquete.
- `scripts/off-03d7c-qa-fixture-preflight.sh inspect`: futuro inventario **solo lectura en VPS** del contenedor `vinto-qa-postgres`, con puerto, red, imagen y estado exactos. Cuenta solo metadatos agregados; si hay usuarios/referencias previas, BLOQUEA y exige inspección humana en vez de borrar/resetear. No imprime nombres, contraseñas, tokens, UUIDs ni registros de negocio. No revalida estado PRE-DDL B2/C1.
- CI: `OFF-03D7C QA Fixture and Signing Preflight` sobre runner efímero Python 3.12, sin DB, usa dependencias backend y tests negativos Node.

## 5. Restricciones de acceso y siguiente paso de infraestructura

El vhost HTTPS QA actualmente accesible no tiene control de entrada verificado. **No levantar frontend/API con rutas públicas aún.** Aprobar primero una opción concreta y reversible: idealmente acceso a QA mediante VPN ya existente con política propia, o allowlist de IP autorizadas con denegación predeterminada. Documentar IP/capacidad móvil y pruebas desde cliente permitido y denegado sin publicar datos sensibles. Nginx debe conservar `/qa-ready` y no enrutar jamás al piloto/TVC; preparar backup y rollback de su configuración, probando `nginx -t` antes de reload, solo en un release posterior aprobado.

**Cierre de D7C GitHub:** contratos fuente/firmas/fixturas PASS en CI, audit read-only en VPS pendiente. **D7D:** instalación runtime Node22 QA, app, backend, controles de acceso, datos sintéticos y firma solo por etapas con autorización explícita; no mezclar todas esas escrituras en una sola operación. El móvil físico M01–M11/N01–N06 sigue pendiente.

**Marcadores actuales:** `OFF03D7B_VPS_AUDIT=PASS_READ_ONLY` (informado por Codex), `OFF03D7C_GITHUB=PENDING_CI`, `QA_ACCESS_CONTROL=BLOCKED`, `QA_FIXTURE_IMPORT=NOT_STARTED`, `QA_TEST_USER=NOT_CREATED`, `QA_SIGNING_SEED=NOT_CONFIGURED`, `OFF04=DISABLED`.

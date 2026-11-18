# VINTO OFF-03D.7C6A — Auditoria READ ONLY de identidad y barrera de escritura Calidad QA

**18-nov-2026 | PR Draft, basado en #212.** Ninguna fase de este PR crea roles, cuentas, perfiles, concesiones, contrasenas, claves, firmas, servicios ni modifica PostgreSQL/Nginx/piloto/TVC. La auditoria es un diagnostico, NO una autorizacion.

## Entrada validada: D7C5 cerrado

Codex informo una sola importacion del catalogo oficial vinto-reference-bobinas-pilot en vinto_qa_offline. La auditoria D7C5A-R1 termino PASS para 31 migraciones, checksums y ACL; estado piloto/TVC; copia POST-DDL; aislamiento QA; fuente canonica; conteos completos; lote y checksum; cuatro versiones Calidad publicadas; exactamente ocho pares MP1/MP3; usuarios=0, grants=0; dry-run idempotente. Sin nuevas escrituras. Cierre en PR #211 y #213. No repetir apply, inspect anterior ni verificadores PRE-DDL.

## Riesgos confirmados en el repositorio

1. **CALIDAD no es de solo lectura**: backend/app/auth/permissions.py concede quality.capture y quality.release. Los ocho pares maquina/formulario no impiden por si solos otras escrituras.
2. **Bloqueo de escritura QA existe en codigo pero NO en API QA desplegada.** backend/app/qa_offline_guard.py permite solo POST de login, logout, scope firmado y quality-package firmado; deniega otros metodos inseguros bajo APP_ENV=qa. Login/logout SI pueden escribir sesion/eventos de identidad; se bloquea el dato OPERATIVO, no toda escritura en DB. La API QA y su acceso externo aun NO estan habilitados.
3. **vinto_identity ausente en QA**: el auditor D6C3 anterior exigia su ausencia y D7C5A-R1 lo ejecuto. El rol vinto_app todavia dispone de DML de identidad, incluyendo usuario, perfil-de-usuario, sectores, concesiones, credenciales y sesiones. Es la exposicion heredada documentada, no la meta de minimo privilegio.
4. **CLI de usuario puede caer a DATABASE_URL**: backend/create_user.py elige IDENTITY_DATABASE_URL si existe, pero puede recurrir a DATABASE_URL sin ella. No ejecutar el CLI sobre QA sin conexion blindada, rol dedicado y secretos protegidos.
5. **Procedimientos existentes**: backend/roles/00c_create_identity_role.sql crea el rol, 03c_d3b2_identity_role_grants.sql concede privilegios de identidad de forma aditiva y 03d_d3b4_cut_identity_dml.sql aplica un corte posterior con aprobacion independiente. Ninguno esta autorizado por este PR. No ejecutar esos SQL por atajo.

## Ejecutor D7C6A — modo unico audit

Archivo: scripts/off-03d7c6a-qa-identity-readiness.sh.

Primero verifica el blob inmutable del auditor anterior D7C5A-R1, ejecuta solo audit y exige todos sus PASS: 31 migraciones, ACL, backup POST-DDL, catalogo completo con lote/checksum, 4 Calidad, 8 pares, usuarios/grants=0, idempotencia y piloto/TVC. Luego hace una sola consulta SELECT fija a la DB exacta vinto_qa_offline del contenedor vinto-qa-postgres con rol de auditoria vinto_qa_bootstrap y PGOPTIONS default_transaction_read_only=on. Inspecciona metadatos de roles, permisos de tabla y columna, conteos agregados y ACL. No consulta filas ni secretos.

**Estados previstos:**

- OFF03D7C6A_POSTIMPORT_CATALOG=PASS_READ_ONLY; OFF03D7C6A_PILOT_TVC=PASS_AT_AUDIT; OFF03D7C6A_POST_DDL_BACKUP=PASS_FILE_INTEGRITY.
- OFF03D7C6A_QA_USERS_AND_GRANTS=ZERO.
- OFF03D7C6A_IDENTITY_ROLE=ABSENT_NOT_PROVISIONED.
- OFF03D7C6A_APP_IDENTITY_DML=EXPOSED_LEGACY_BASELINE.
- OFF03D7C6A_CATALOG_WRITE_RESTRICTION_D3B1=PASS.
- OFF03D7C6A_IDENTITY_ROLE_CUT_D3B4=NOT_APPLIED.
- OFF03D7C6A_TEST_ACCOUNT_CREATE=BLOCKED_PENDING_ROLE_AND_APPROVAL.
- OFF03D7C6A_GRANTS_AND_SIGNING=NOT_AUTHORIZED.
- OFF03D7C6A_QA_WEB_WRITE_GUARD=NOT_VERIFIED_ON_DEPLOYED_API.
- OFF03D7C6A_AUDIT=PASS_READ_ONLY_WITH_IDENTITY_GATES_OPEN; NO_DATABASE_WRITES=PASS.

La auditoria puede terminar PASS incluso cuando la preparacion para crear la cuenta sigue BLOCKED. Si vinto_identity aparece inesperadamente o cambian privilegios, el gate falla cerrado y requiere revision sin ningun ajuste automatico.

## CI GitHub, sin VPS

- Node prueba negativas: solo audit, sin apply, create-role, create-user, grant, backup, restore, migrate, etc.; requiere auditor D7C5A pinneado y SELECT read-only.
- Python prueba CALIDAD write rights, denegacion QA de todos los POST operativos por la funcion de guard, excepciones de autenticacion/paquetes firmados, referencia al middleware real, y fallback de create_user.py.
- PostgreSQL17 desechable: migra 31, configura ACL, importa catalogo oficial solo en runner y ejecuta el mismo SQL que D7C6A. Debe comprobar vinto_identity ausente y DML identidad aun presente en vinto_app. Ninguna conexion a la VPS real.
- Ninguna prueba de CI puede demostrar que el backend QA real ya usa el middleware: aun no esta desplegado.

## Secuencia futura (no autorizada en este PR)

1. D7C6A: CI 2/2 PASS + audit READ ONLY Codex con SHA/blob exactos.
2. D7C6B: plan reversible y autorizacion explicita aparte para crear vinto_identity exclusivamente en PostgreSQL QA (00c) y conceder permisos con 03c. La creacion de un rol requiere escritura/credencial protegida, backup y rollback propios. No toca piloto/TVC.
3. D7C6C: probar ambas conexiones y, solo con aprobacion independiente, aplicar corte de DML 03d a vinto_app. Un futuro auditor POST-CUT debe reemplazar los supuestos de D6C3 que exigen ausencia de vinto_identity; no invocar viejos gates en fase incorrecta.
4. D7C6D: cuenta qa.offline.calidad con Argon2id, perfil CALIDAD, sector BOBINAS y ocho grants MP1/MP3 x P1-18/22/26/27; solo con identidad dedicada y denegacion efectiva de escrituras operativas probada en API QA y autorizaciones independientes. Revocacion/rollback por etapas.
5. Firma exclusiva Ed25519 QA, ancla publica autenticada y flags de emision inicialmente apagados; VPN/allowlist de acceso al hostname QA con deny-by-default y pruebas desde red permitida/no permitida antes de publicar / o /api. M01-M11/N01-N06 en celular fisico despues. OFF-04 captura/sync deshabilitada.

**Draft sin merge a main y sin modificaciones piloto/TVC, API QA ni base de datos.**

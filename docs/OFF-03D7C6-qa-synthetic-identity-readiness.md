# VINTO OFF-03D.7C6 — Preparación de identidad sintética Calidad QA (SIN escrituras)

**18-nov-2026 — contrato para un incremento posterior, apilado sobre PR #211.** NO crea usuarios, perfiles, sectores, grants, semillas, firmas, servicios, secretos ni nuevos roles. No concede autorización para ejecutar `D7C5 apply`. QA, piloto y TVC permanecen sin alteraciones.

## Línea de base: D7C5 aún es solo lectura

El operador informó `OFF03D7C5_PREFLIGHT=PASS_READ_ONLY`, `OFF03D7C5_REFERENCE_DRY_RUN=PASS_READ_ONLY`, fuente oficial `PASS_PINNED`, rol `vinto_reference` y destino QA `PASS`, respaldo POST-DDL D7C4 íntegro, 31 migraciones y ACL PASS. Resultado `OFF03D7C5_IMPORT=NOT_AUTHORIZED`: **no hay catálogos en QA**. GitHub CI de PR #211 `44334003645` terminó 2/2 PASS en runner con PostgreSQL17 efímero. El primer paso real pendiente sigue siendo **autorizar por separado** D7C5 apply una sola vez, tras aprobación expresa del operador.

## Objetivo de identidad para ensayos offline de solo lectura

| Dimensión | Contrato de QA previsto |
|---|---|
| Usuario sintético | `qa.offline.calidad` |
| Nombre de presentación | `Calidad QA Offline (sintetico)` |
| Perfil existente | `CALIDAD` |
| Sector concedido explícitamente | `BOBINAS` |
| Máquinas autorizables | `MP1`, `MP3` |
| Formularios | `VINTO-P1-18` v2, `VINTO-P1-22` v2, `VINTO-P1-26` v3, `VINTO-P1-27` v2 |
| Concesiones de máquina+formulario | Exactamente ocho pares, solo después de revisión funcional y autorizaciones específicas |
| Credenciales | Generadas de forma aleatoria exclusiva QA, Argon2id, almacenadas bajo protección administrativa; nunca Git, chat ni CI |
| Ed25519 QA | Clave privada de 32 bytes exclusivamente QA, provisionada por fase distinta, no en este PR |

**Las definiciones oficiales del bundle no son datos de captura ficticios**. Se importarán desde fuente versionada con checksum, no desde bases del piloto ni TVC. El usuario y las credenciales sí son sintéticos.

## Riesgo comprobado — CALIDAD NO es un perfil de solo lectura

La matriz ejecutable `backend/app/auth/permissions.py` concede al perfil `CALIDAD` los permisos `quality.capture` **y** `quality.release`. Por tanto, crear el usuario y otorgar esos ocho pares **podría darle capacidades de escritura online** si la API no aplica otras barreras. Un paquete offline de definición firmado es de solo lectura, pero **el perfil y las concesiones no lo son**.

El valor por defecto `AUTHZ_QUALITY_MACHINE_CAPTURES_MODE=off` significa que el endurecimiento opcional de autorización no se evalúa en esa ruta; **NO equivale a deshabilitar POST**. No confiar en valores por defecto ni en que no haya usuarios externos. Antes de crear y habilitar la cuenta, garantizar que el middleware QA de solo lectura D7A efectivamente bloquea capturas, liberaciones, aprobaciones, sincronización y otros cambios operativos con pruebas de denegación HTTP, aun para sesión CALIDAD válida. `OFFLINE_SCOPE_ISSUE_ENABLED` y `OFFLINE_QUALITY_PACKAGE_ISSUE_ENABLED` comienzan desactivados; podrán activarse posteriormente solo para exportar definiciones firmadas de solo lectura con acceso restringido.

## Riesgo comprobado — la identidad DB sigue pendiente

El servicio oficial `app.auth.service.create_user()` crea usuario, perfil, credencial y sectores en una transacción; la contraseña se hashea con Argon2id. El CLI `backend/create_user.py` admite `--target dev` y `--password-env`, pero **si IDENTITY_DATABASE_URL falta puede caer a DATABASE_URL**. D6C3 no probó que exista una identidad `vinto_identity` con ACL mínimas; el rol `vinto_app` conserva derechos de identidad que aún forman parte de un endurecimiento pendiente. **No ejecutar el CLI directamente contra QA con conexiones heredadas, bootstrap o privilegios elevados**.

Se requiere un gate separado y read-only: verificar en catálogos de PostgreSQL qué rol realizará exclusivamente creación de usuarios QA y concesiones, su login/ACL y el destino exacto `127.0.0.1:6554/vinto_qa_offline`. Si falta, diseñar aprovisionamiento mínimo y pedir autorización aparte; no conceder privilegios ampliados a `vinto_app` ni reutilizar rol migrador/referencia. Verificar dónde reside el procedimiento oficial de `user_machine_form_grant` y la revocación de concesiones; **no escribir SQL ad hoc** sin comprobación de contrato/ACL.

## Secuencia de gates futuros (ninguno ejecutado aquí)

1. **D7C5:** operador autoriza expresamente `apply`; Codex repite gates y aplica solo el bundle oficial en QA; comprobar batch único, cuatro versiones `published`, ocho vínculos, 31 migraciones, 0 usuarios y 0 concesiones, y repetición dry-run idempotente. Preservar D7C4 y B2.
2. **D7C6-A — identidad READ ONLY:** localizar flujo oficial y rol de identidad, verificar ACL para la DB QA, diseñar alta/revocación y manejo secreto de contraseña. Ninguna escritura en esta etapa.
3. **D7C6-B — protección de API:** validar `APP_ENV=qa`, middleware QA deny-by-default y pruebas negativas de POST/PUT/PATCH/DELETE operativas incluyendo Calidad y liberaciones, aun con cuenta autorizada. No usar solo modo `AUTHZ_*_MODE=off` como bloqueo.
4. **D7C6-C — alta sintética:** con autorizaciones explícitas de identidad, crear solo una cuenta `qa.offline.calidad`, perfil `CALIDAD` y sector `BOBINAS` usando el mecanismo oficial; credencial secreta con expiración/rotación, rollback de cuenta y auditoría.
5. **D7C6-D — concesiones:** autorizar por separado solo ocho pares vigentes MP1/MP3 × P1-18/22/26/27; probar denegación de máquinas/formularios fuera de lista, revocación y lectura del motor de autorización.
6. **Firma y web móvil:** aprovisionar semilla Ed25519 QA en secreto protegido, anclar clave pública autenticadamente; VPN/allowlist o mecanismo equivalente con denegación predeterminada verificado desde cliente permitido y denegado antes de publicar `/` y `/api` en Nginx. Solo entonces ensayar M01–M11/N01–N06 en celular físico.

## Estado

- `OFF03D7C5_GITHUB_CI=PASS`, `OFF03D7C5_VPS_PREFLIGHT=PASS_READ_ONLY`, `QA_REFERENCE_IMPORT=NOT_AUTHORIZED`.
- `D7C6_SYNTHETIC_IDENTITY=NOT_CREATED`, `D7C6_MACHINE_FORM_GRANTS=NOT_CREATED`, `D7C6_SIGNING_SEED=NOT_CONFIGURED`.
- `QA_AUTHZ_WRITE_BLOCK=NOT_VALIDATED_ON_DEPLOYED_QA_API`, `QA_ACCESS_CONTROL=BLOCKED`, `QA_WEB=NOT_DEPLOYED`.
- Ninguna fase incluye modificaciones piloto/TVC, Nginx ni merges a main sin autorización separada.

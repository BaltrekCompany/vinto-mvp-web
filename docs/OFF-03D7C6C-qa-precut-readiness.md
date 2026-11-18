# VINTO OFF-03D.7C6C — Auditoría PRE-CUT de identidad QA (READ ONLY)

18-nov-2026. Draft basado en PR #217. Ningún SQL de escritura, no hay autorización D3B4, no se cambió la VPS.

## Evidencia de entrada

Codex informó una única ejecución autorizada de D7C6B apply y una verificación POST-ROL read-only exitosa: vinto_identity existe en PostgreSQL17 QA, tiene conexión y ACL 03c; catálogo completo, 31 migraciones, 0 usuarios/grants, piloto/TVC intactos. El rol vinto_app conserva DML de identidad, D3B4 aún NO está aplicado. D7C4 es backup histórico PRE-IMPORTACIÓN; el operador decidió no tomar un backup nuevo.

## Código oficial verificado

- backend/roles/03d_d3b4_cut_identity_dml.sql — Git blob bc76423ed56506d55bff1fc0e4d9b82ea96f872b.
- backend/roles/rollback/ROLLBACK_D3B4.sql — Git blob 97041aa0c90b738d4f9be7fa71185b11f2240a9e.
- backend/tests/test_d3b3_two_role_gate.py: prueba integral de ambas conexiones y del corte/reversión SOLO en bases efímeras, no en QA persistente.

**Dependencia crítica:** antes del corte D3B4, la aplicación que atiende solicitudes debe tener IDENTITY_DATABASE_URL configurada para el rol dedicado y comprobar funcionalmente ambas conexiones con el rol de negocio (D3B3). El postverify D7C6B probó login al servidor PostgreSQL como vinto_identity, **NO** probó la configuración de FastAPI ni los flujos HTTP. La API QA todavía no está desplegada con acceso restringido; NO aplicar D3B4 solamente por haber creado el rol.

El SQL D3B4 retira INSERT/UPDATE/DELETE de identidad del rol vinto_app y acceso al hash de contraseña, conservando SELECT de identidad, columnas específicas de credenciales, UPDATE mínimo de sesiones y locks, además de auditoría. Tiene guardas y es transaccional pero requiere AUTORIZACIÓN INDEPENDIENTE.

ROLLBACK_D3B4 restaura los permisos de negocio ANTES de quitar IDENTITY_DATABASE_URL. Nunca quitar esa configuración primero después de un corte, pues podría dejar login y administración sin permisos (SQLSTATE 42501). El rollback no borra rol ni permisos 03c y NO está autorizado automáticamente.

## Auditoría propuesta D7C6C

scripts/off-03d7c6c-qa-precut-readonly.sh acepta SOLO audit:

1. Fija por Git blob el instalador anterior y ejecuta su modo POST-ROL verify, nunca inspect PRE-ROL. Exige identidad creada y autenticada, ACL 03c, catálogo/31 migraciones y 0 usuarios/grants.
2. Verifica checkout QA y SHA de scripts oficiales D3B4 y rollback, pero NO ejecuta ningún SQL de corte o reversión.
3. Consulta un SELECT de metadatos agregados en vinto_qa_offline, vía vinto_qa_bootstrap y default_transaction_read_only=on: dos roles, ACL efectivas, separación de membresías, D3B1, 31 migraciones y catálogo intactos.
4. Declara explícitamente que la configuración de las dos URLs en una API QA desplegada, PG_PRIVILEGE_MODE, la barrera HTTP y el gate funcional D3B3 están SIN VERIFICAR. La auditoría puede terminar PASS_READ_ONLY_WITH_FUNCTIONAL_GATES_OPEN sin que el corte esté autorizado.

No usar scripts D6C3/D7C6A/D7C6B-PRE/installer inspect, que exigen vinto_identity ausente. Tras rol creado, verificar solo con D7C6B verify.

## CI y secuencia restante

CI: pruebas negativas y el MISMO SELECT PRE-CUT contra PostgreSQL17 EFÍMERO con 31 migraciones, bundle oficial, 00c y 03c, antes de revertir el rol en ese mismo runner. No contacta la VPS real.

Siguiente: Codex read-only audit; luego preparar API QA privada con VPN/allowlist fail-closed y conexiones separadas DATABASE_URL de vinto_app e IDENTITY_DATABASE_URL de vinto_identity; probar ambas y bloqueo de escrituras operativas en APP_ENV=qa con pruebas negativas HTTP. Recién después preparar el corte D3B4 con auditoría POST-CUT y rollback, solicitando autorización separada. No crear usuarios/8 grants/Ed25519 ni tocar piloto/TVC/main por este PR.

**Estado:** solo GitHub Draft, sin despliegue ni corte de permisos.

# VINTO — OFF-03D.7C6B PRE: preparación del rol de identidad en QA (READ ONLY)

18-nov-2026. Este PR Draft está apilado sobre #214, y aún NO autoriza crear vinto_identity ni conceder/revocar privilegios. Únicamente incluye un preflight de solo lectura, contrato de CI, verificación de scripts oficiales y un plan de operación posterior con sus límites. No se ha modificado PostgreSQL QA, el piloto, TVC, Nginx, el API QA o main.

## Evidencia de partida

- D7C5A-R1: referencia oficial completa importada a vinto_qa_offline, 31 migraciones/checksums/ACL, respaldo POST-DDL D7C4 íntegro y restaurado, un import_batch con checksum, 4 versiones Calidad publicadas, 8 pares MP1/MP3, 0 usuarios/grants, idempotencia PASS_READ_ONLY y servicios piloto/TVC operativos.
- D7C6A Codex: OFF03D7C6A_AUDIT=PASS_READ_ONLY_WITH_IDENTITY_GATES_OPEN; IDENTITY_ROLE=ABSENT_NOT_PROVISIONED; APP_IDENTITY_DML=EXPOSED_LEGACY_BASELINE; CATALOG_WRITE_RESTRICTION_D3B1=PASS; IDENTITY_ROLE_CUT_D3B4=NOT_APPLIED; 0 usuarios y grants. Sin escrituras.
- D7C6A es un diagnóstico exitoso de la exposición **actual**: no indica que la cuenta sintética pueda crearse.

## Alcance específico del siguiente paso

La etapa D7C6B futura instalaría EXCLUSIVAMENTE el rol LOGIN vinto_identity en PostgreSQL17 del contenedor de QA vinto-qa-postgres, base vinto_qa_offline, red vinto-qa-internal y puerto 127.0.0.1:6554. Posteriormente aplicaría los GRANT oficiales de identidad 03c mediante vinto_migrator. El rol es GLOBAL a su clúster PostgreSQL, por eso es esencial que QA tenga contenedor/cluster independiente de piloto y TVC. No se modifica una instancia compartida, no se utilizan comandos de Docker de otro contenedor.

Los archivos oficiales del checkout inmutable QA (sha 7b9eb8c82a290d06e719ee4990c2020076bbd11b) coinciden con los del candidato GitHub:
- backend/roles/00c_create_identity_role.sql — Git blob 04bc90dfeaf225d2c139587899fa46ce54913fe5, crea LOGIN sin SUPERUSER/CREATEDB/CREATEROLE/INHERIT, contraseña por variable IDENTITY_PASSWORD; detecta colisión de rol existente.
- backend/roles/03c_d3b2_identity_role_grants.sql — Git blob 6df9ac8c96d6cf85a00aecccc6631f8eddc7450b, GRANT aditivo transaccional sobre identidades, sesiones y concesiones, verificando exactamente privilegios aprobados.
- backend/roles/rollback/ROLLBACK_D3B2.sql — Git blob 0039f4c530b611873f4b60710bf42aec54edd2c7. **Retira los privilegios de 03c pero NO elimina vinto_identity**. Exige que vinto_app todavía conserve DML de identidad y deniega la operación si D3B4 ya cortó esos privilegios sin revertirse antes.
- backend/roles/03d_d3b4_cut_identity_dml.sql — Git blob bc76423ed56506d55bff1fc0e4d9b82ea96f872b, **corte independiente** posterior de DML a vinto_app; no debe ejecutarse en D7C6B.

## Preflight D7C6B, permitido en solo lectura

scripts/off-03d7c6b-qa-identity-role-preflight.sh, modo único inspect:

1. Verifica por Git blob el auditor D7C6A original en /tmp; lo ejecuta solo en audit, exigendo catálogo/31 migraciones/backup/piloto/TVC intactos, 0 usuarios/grants, rol vinto_identity ausente, DML legado, protección D3B1 y ausencia del corte D3B4.
2. Comprueba el commit detached limpio del checkout QA, compara los cuatro SQL oficiales con su Git blob exacto (sin ejecutar ninguno).
3. Ejecuta un único SELECT agregado READ ONLY en vinto_qa_offline como vinto_qa_bootstrap, con PGOPTIONS default_transaction_read_only=on. Valida superusuario del contenedor QA, roles de migración/app/referencia presentes con LOGIN y no privilegiados, rol identidad y test-admin ausentes, ninguna membresía cruzada que permita evadir permisos, catálogo ya importado, 0 usuarios/perfiles concedidos/sectores concedidos/grants/credenciales/sesiones y conexión PUBLIC revocada.
4. Devuelve solo indicadores públicos, no secretos ni filas. Un resultado PASS confirma que se **puede solicitar autorización** para una próxima fase de instalación, no que la instalación haya ocurrido.

Resultados esperados:
- OFF03D7C6B_IMPORTED_QA_CATALOG_AND_BACKUP=PASS
- OFF03D7C6B_PILOT_TVC=PASS_AT_AUDIT
- OFF03D7C6B_IDENTITY_SQL_AND_ROLLBACK=PASS_PINNED
- OFF03D7C6B_IDENTITY_ROLE=ABSENT_READY_FOR_SEPARATE_APPROVAL
- OFF03D7C6B_QA_CLUSTER_ROLE_ISOLATION=PASS_READ_ONLY
- OFF03D7C6B_QA_USERS_GRANTS=ZERO
- OFF03D7C6B_ROLLBACK_D3B2=REVOKES_ONLY_ROLE_REMOVAL_OUT_OF_SCOPE
- OFF03D7C6B_IDENTITY_DML_CUT=NOT_APPLIED
- OFF03D7C6B_ROLE_CREATE_GRANTS=NOT_AUTHORIZED
- OFF03D7C6B_PREFLIGHT=PASS_READ_ONLY
- NO_DATABASE_WRITES=PASS

Si la realidad difiere de esta línea base, FAIL CLOSED; nunca crear el rol, reparar privilegios, instalar paquetes o repetir migraciones automáticamente.

## Entregables CI y límites de la evidencia

GitHub Actions ejecuta:
- Node/Bash: syntax, modos mutantes prohibidos, revisión de script oficial/hash y SQL READ ONLY sin contraseñas ni SELECT de personas.
- PostgreSQL17 efímero: 31 migraciones y catálogo oficial importado solo en el runner, misma consulta SELECT de preflight sin modificación de roles ni permisos del servidor real.
- La salida de CI no sustituye inspección de Codex sobre la VPS. No ejecutar instalador de identidad en el servidor durante estos ensayos.

## Plan operacional para D7C6B, NO autorizado actualmente

La instalación futura requiere nueva aprobación explícita para **CREATE ROLE** y **GRANT**, y protege una contraseña de 64 caracteres o equivalente generada aleatoriamente, bajo archivos root:0600 exclusivos QA; no imprimir ni pasar valores sensibles como argumentos del shell, GitHub, chat o logs. El flujo ejecutaría una sola creación 00c con administrador SOLO del contenedor PostgreSQL QA y un GRANT transaccional 03c con vinto_migrator. Debe verificar rol y permisos efectivos como dos identidades distintas, ausencia de membresías privilegiadas y que NO existen usuarios/grants creados. Detener si falla, sin reintentos ni rollbacks improvisados; la restauración de B2 PRE-DDL nunca debe ejecutarse.

**Reversión de permisos:** el archivo oficial ROLLBACK_D3B2.sql puede retirar grants de 03c solo mientras vinto_app conserve el DML legado (antes de D3B4). NO elimina el rol ni la contraseña; limpiar un rol inerte o rotar su clave requiere un procedimiento diferente y aprobación expresa, particularmente porque el rol es global al clúster QA. El backup POST-DDL D7C4 fue creado ANTES del rol nuevo y el dump de globals excluye contraseñas de roles; una copia de seguridad no reemplaza este plan de acceso/credenciales. Es recomendable preparar nueva evidencia de recuperación adecuada antes de aprobar un corte de privilegios.

**No realizar ahora:** D3B4 corte de DML, rollback, DROP ROLE, crear cuenta qa.offline.calidad, ocho grants, firma Ed25519, activar OFF-04, QA web / o /api, ni modificar Nginx/main/piloto/TVC. El middleware QA de deny-write está probado solo en código; se debe probar realmente en una API QA aislada detrás de VPN/allowlist deny-by-default antes de crear una cuenta operable.

## Siguiente secuencia

1. D7C6B PRE: CI 2/2 y Codex inspect solo lectura.
2. Pedir al operador autorización ESPECÍFICA para alta del rol y GRANT oficiales en el clúster QA con un procedimiento reversible y revisión de secretos.
3. Tras aprobación, proveer ejecutor inmutable de instalación con verificaciones postfase y sin tocar otros entornos.
4. D7C6C posterior y separado: probar conexión de ambas identidades, endurecer DML vinto_app con el corte oficial 03d solo tras una nueva aprobación y plan de rollback propio. No reutilizar auditor D7C6A/PRE que exigen ausencia de rol.
5. D7C6D: cuenta sintética CALIDAD y ocho concesiones, después de validar guard HTTP en servicio QA y acceso restringido; autorización independiente.

PR Draft sin merge a main ni despliegues.

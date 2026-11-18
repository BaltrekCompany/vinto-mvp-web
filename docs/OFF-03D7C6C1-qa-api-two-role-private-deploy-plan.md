# VINTO OFF-03D.7C6C1 — Preparación de API QA privada con dos conexiones

**18 de noviembre de 2026. Diseño y pruebas de código solamente.** No se despliega ni instala ningún servicio en la VPS, no se altera Nginx, PostgreSQL, firewall, roles, piloto/TVC ni main. PR Draft apilado sobre #218, cuya auditoría de PRE-CUT ya fue confirmada PASS_READ_ONLY por Codex.

## Estado verificado

- D7C6B: `vinto_identity` existe en clúster PG17 QA `vinto-qa-postgres`, DB `vinto_qa_offline`, aislada en `127.0.0.1:6554`; CREATE/CONNECT/03c y autenticación POST-ROL PASS; 31 migraciones, catálogo completo, cero usuarios/grants; D3B4 no aplicado.
- D7C6C: auditor PRE-CUT ejecutado solo en lectura con SHA verificado y código 0. Dos roles/ACL en PASS_PRECUT_READ_ONLY; `vinto_app` conserva intencionalmente DML de identidad, QA DB sin cuentas. Script D3B4 y rollback verificados por SHA, sin ejecución.
- GitHub: `backend/app/database.py` usa `get_identity_connection`/ `open_identity_connection` con `IDENTITY_DATABASE_URL` específica si está definida. Si falta, puede caer a `DATABASE_URL`. La conexión dedicada que falla no vuelve silenciosamente a la de negocio. `backend/app/auth/router.py` conecta login/logout a identidad, y `backend/app/admin/router.py` usa identidad para administración.
- `backend/app/main.py` instala `qa_offline_write_guard`: cuando `APP_ENV=qa`, rechaza POST/PUT/PATCH/DELETE de operaciones, admin y sync con HTTP 403 antes de su handler, excepto cuatro POST exactos (login, logout, scope y quality-package). Una prueba de esta función **en CI** no demuestra un servicio QA desplegado.
- **PENDIENTES reales:** no hay prueba de una API QA activa con `IDENTITY_DATABASE_URL` y `PG_PRIVILEGE_MODE=hardened`, control de red y guard HTTP real; tampoco prueba D3B3 de continuidad de login, sesiones y administración con ambos roles. D3B4 sigue NO autorizado.

## Próximo producto: QA privado, NO público

El primer despliegue a autorizar debe ejecutar exclusivamente el backend QA en proceso/servicio y puerto propios, con origen de código fijado y sin alterar el release del piloto/TVC. Mantener la conexión a PostgreSQL local por loopback (no exponer 6554). El backend QA debe ser inaccesible desde Internet mientras no exista una allowlist/VPN **fail closed** verificada desde dos orígenes diferentes. La resolución DNS y el certificado TLS del hostname no constituyen autorización de acceso.

**Configuración objetivo a verificar en el proceso real, sin imprimir secretos:**

| Propiedad | Requisito |
|---|---|
| APP_ENV | `qa` |
| DATABASE_URL | conexión al DB QA como `vinto_app` |
| IDENTITY_DATABASE_URL | conexión al **mismo** DB QA como `vinto_identity` |
| PG_PRIVILEGE_MODE | `hardened`, sujeto a comprobación de todas sus dependencias de runtime |
| CORS_ORIGINS | solo origen del hostname QA autorizado |
| Cookies | Secure / HttpOnly; nombre exclusivo QA si comparten navegador |
| OFFLINE_SCOPE_ISSUE_ENABLED | `false` en etapa previa |
| OFFLINE_QUALITY_PACKAGE_ISSUE_ENABLED | `false` en etapa previa |
| AUTHZ_QUALITY_MACHINE_CAPTURES_MODE | mantener estado no operativo; **no** confundir `off` con bloquear endpoints |
| Red | backend propio por loopback; hostname solo VPN/allowlist autorizada |
| Datos | catálogo canónico y 31 migraciones sin alterar; no crear usuarios ni grants en este incremento |

**Secretos:** no copiar password de rol a variables en la terminal, argumentos, GitHub ni registros. Leer la credencial root:0600 de identidad mediante un mecanismo de servicio protegido diseñado tras inventario (por ejemplo systemd credentials), sin debilitar ACL de root ni hacer legible el secreto por el frontend. No crear `.env` compartido con el piloto. Configuración de la clave de firma Ed25519 se deja APAGADA.

## Puertas antes de cualquier despliegue / corte

1. **Inventario VPS solo lectura:** Codex informa nombre y estado de servicios, orígenes exactos de backend/frontend QA si ya existen, puertos vinculados y reglas de acceso (sin volcar Nginx completo ni contenido de `.env`, DSN, tokens o claves). Confirma que el QA DB sigue en 127.0.0.1:6554 y que piloto/TVC continúan operativos. No modifica nada.
2. **CI código:** pruebas de API FastAPI realmente importada bajo `APP_ENV=qa` y de middleware 403 antes de handler; cuatro excepciones POST exactas; ruta de login/admin con `get_identity_connection`; conexión dedicada usa identidad y falla cerrado ante error. Se hace con mocks, sin DB ni VPS. Puede dar PASS aunque no exista un servicio QA.
3. **Plan de release:** determinar puerto libre, unidad systemd/servicio de QA, versiones del checkout, forma privada de cargar las dos credenciales, host QA y acceso de red, pruebas de disponibilidad y rollback/STOP. Preparar ejecutor con checks de integridad y aprobación **nueva** para instalar/arrancar backend QA.
4. **Cierre funcional en QA real tras despliegue autorizado:** confirmar por proceso `APP_ENV=qa`, `PG_PRIVILEGE_MODE=hardened`, modo `identity_connection_mode=dedicated`, dos conexiones diferentes y mismo clúster QA; verificar ruta y middleware con solicitudes negativas HTTP. Sin usuarios iniciales no puede completarse la prueba integral de login exitoso; la cuenta sintética necesitará autorización independiente.
5. **D3B3/D3B4:** para autorizar D3B4, probar continuidad funcional de login/administración con dos roles y procedimientos de rollback. D3B4 retira DML de identidad a `vinto_app` **solo bajo aprobación explícita independiente**, y no se ejecutará en este incremento.

## Consideraciones de secuencia

La prueba móvil read-only deberá ocurrir después de la API restringida, la cuenta sintética y las firmas QA. Hasta entonces **OFF-04 captura/sync está deshabilitada**. El estado de D7C4 sigue histórico PRE-IMPORTACIÓN por renuncia expresa a un respaldo más reciente; no restaurarlo para revertir un corte ni para publicar QA.

## Prohibiciones de este PR

No instalar o reiniciar servicios; no mostrar ni cambiar credenciales; no escribir Nginx/systemd; no aplicar D3B4/ROLLBACK_D3B4; no crear usuarios/grants/firma; no habilitar endpoints, backend público, main o merge; no tocar piloto/TVC. Los tests locales no se presentarán como evidencia de despliegue.

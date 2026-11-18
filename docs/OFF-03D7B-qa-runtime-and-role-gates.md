# VINTO OFF-03D.7B — runtime portable de QA y auditoría del rol aplicativo

**18-nov-2026 — Diseño/CI GitHub y auditoría remota READ ONLY.** Este incremento se apila sobre PR #205 y NO autoriza instalación, build, reinicio, configuración, deploy, seed o merge a `main`. El piloto, TVC y PostgreSQL QA con 31 migraciones deben quedar intactos.

## Entrada: inventario D7A de Codex

| Control | Estado/evidencia |
|---|---|
| DNS / TLS QA | PASS; certificado Let's Encrypt verificado, válido 17-nov-2026 a 15-feb-2027 |
| Nginx QA | PENDING; vhosts HTTP/HTTPS + `/qa-ready`; sin upstream comprobado para `/` o `/api` |
| TCP 3200 / 8200 | libres **en momento del inventario**, sin reserva |
| Node / pnpm VPS | Node `v20.20.2`; pnpm ausente. El frontend exige Node `>=22.18.0`, pnpm `11.25.0`. |
| PostgreSQL QA | `vinto_qa_offline` con 31 migraciones y ACL y auditoría B2/C3 PASS (reportados por Codex); rol `vinto_app` sin prueba de login efectiva en D7A |
| Web/API QA | No desplegados |
| Móvil físico | No probado; control de acceso a QA por definir |

## A. GitHub: arranque real de frontend portable, sin VPS

1. Seleccionar como candidato **el HEAD exacto de este PR** (apilado sobre D7A); nunca `main`, `/srv/vinto-qa-offline/source` (checkout de migraciones) ni el despliegue piloto.
2. GitHub Actions efímero, Node **22.18.0**, pnpm **11.25.0**, `pnpm install --frozen-lockfile`. Ejecutar TypeScript, ESLint y build con `NEXT_PUBLIC_API_URL=https://qa-vinto-mvp.baltrekservices.com`. Confirmar `dist/standalone/server.js`, assets públicos e identidad de bundle `offline-boot.js`.
3. Ejecutar `scripts/off-03d7b-vinext-standalone-smoke.sh smoke` **solo en el runner**: lanzar `node dist/standalone/server.js` con `HOSTNAME=127.0.0.1`, `PORT=33200`, `NODE_ENV=production`. Comprobar desde loopback `/`, `/offline-preparacion`, recursos PWA, SW y que `/api/auth/me` no entregue sesión exitosa cuando no hay backend. El proceso se destruye y se borran los logs temporales al salir. Si algo falla, **no adaptar el puerto ni usar Wrangler como solución silenciosa**; corregir el contrato dentro del PR.
4. `pnpm start` en este repositorio ejecuta Wrangler `dev --local` y no equivale automáticamente a servicio productivo Node. No modificar este comando para el piloto. Un smoke CI positivo permite planear un arranque QA independiente, pero **no confirma aún compatibilidad con systemd, VPS, red ni política de acceso**.

## B. VPS Codex: prueba del rol `vinto_app` READ ONLY

Script versionado `scripts/off-03d7b-qa-app-role-audit.sh`, un único modo `audit`. Tras descargar con SHA completo y validar `git hash-object` y `bash -n`, Codex podrá ejecutar **solo lectura** usando `sudo -n`:

- Rechaza contenedor equivocado, puerto distinto a `127.0.0.1:6554`, imagen no PG17, cambio de red, servicio piloto o TVC detenido.
- Consulta catálogos con `vinto_qa_bootstrap`, sesión `default_transaction_read_only=on`: DB exacta, historial 31, ausencia de CONNECT PUBLIC, app LOGIN no superuser/createdb/createrole/bypassrls, CREATE DB negado, USAGE mínimo sobre master/config/auth, acceso meta denegado y D3B1 de catálogos vigentes.
- **Comprueba inicio de sesión real** como `vinto_app` con secreto existente `/etc/vinto-qa/role-app.password` (root:0600). El archivo se lee únicamente dentro de una tubería al proceso `psql` del propio contenedor QA, sin mostrarlo, guardarlo en otro archivo, pasarlo por argumentos de proceso ni copiarlo a GitHub. Consulta solamente `current_user`, DB, `default_transaction_read_only=on`, SELECT en user/form/auth y restricciones sobre meta/CREATE/D3B1. No examina filas de usuarios, formularios o credenciales.
- El script **no hace** migraciones, DML/DDL, backup, restore, QA seed, login de aplicación, construcción de frontend o cambios en servicios.
- `OFF03D7B_QA_APP_LOGIN=PASS_READ_ONLY` demuestra el login SQL del rol contra QA y permisos declarados, pero **no** valida aún que FastAPI tenga su `DATABASE_URL` correcta ni que `POST /api/auth/login` funcione con usuario de prueba.

## C. Aislamiento propuesto para un release posterior (sin tocar servicios actuales)

```
Móvil en VPN/allowlist aprobada
  -> qa-vinto-mvp.baltrekservices.com HTTPS / 443 (cert TLS actual)
  -> vhost Nginx exclusivo QA (rutas no configuradas todavía)
     /api/* -> 127.0.0.1:8200 FastAPI QA (APP_ENV=qa + guard D7A)
     /*     -> 127.0.0.1:3200 Vinext Node standalone QA
                       |
                   FastAPI QA -> 127.0.0.1:6554 / vinto_qa_offline (vinto_app)
```

3200/8200 son **candidatos, no reservas**; Nginx y SSL del piloto y TVC no se modifican. Instalar Node 22/pnpm 11.25 únicamente en un prefijo o artefacto exclusivo QA previamente aprobado (por ejemplo `/opt/vinto-qa-runtime`), **no reemplazar Node 20 global** ni cambiar el `PATH` de los servicios existentes. Se requiere plan de instalación verificable con hashes, rollback de archivos, servicio systemd propio y bloqueo de acceso público.

Revisar además:
- `APP_ENV=qa` y middleware bloquean POST/PATCH/PUT/DELETE operativos; login/logout y emisión de alcances de solo lectura pueden modificar sesiones/auditorías QA, pero **no crean capturas**.
- `NEXT_PUBLIC_API_URL` debe fijarse en el build al mismo origen público QA; nunca loopback visible al celular.
- Credenciales SQL `vinto_app` y semilla Ed25519 exclusivos QA y protegidos, no logs ni Git.
- Cookies `Secure, HttpOnly`, CORS mismo origen, proxy `X-Forwarded-Proto` restringido a loopback, VPN/allowlist, jamás habilitar QA público por conveniencia.
- Rutas sensibles del frontend y endpoints GET de administración requieren autenticación y prueba de no divulgación, incluso con guard QA: el guard no sustituye la autorización efectiva del backend.
- Usar **solo datos ficticios** y un usuario sintético Calidad con perfil/concesiones mínimos en otro incremento autorizado (D7C). Los formularios P1-18/22/26/27 deben estar publicados y homologados; no suponer que las 31 migraciones cargaron datos.

## D. Gate pendiente Nginx / API

Codex revisará de forma sanitizada el vhost Nginx del dominio QA (solo nombres de rutas, dominios, upstream/puertos sin contenido de secretos). Debe confirmar si `/` y `/api` siguen sin upstream o si existe alguna ruta de fallback que pueda dirigirse a piloto. No ejecutar `nginx -T` completo en respuesta ni guardar configuración. **Ningún HTTP 200 equivale a prueba de aislamiento; verificar Host/SNI, vhost y reglas de acceso por separado.**

## E. Criterios de decisión

**D7B GitHub PASS:** Node22/pnpm11 + build, arranque real standalone loopback en CI, carga de pantalla de preparación y assets, scripts read-only con tests negativos, CI 2/2 PASS. Esto no autoriza instalación.

**D7B VPS PASS:** el operador aporta salida `OFF03D7B_AUDIT=PASS_READ_ONLY` y evidencias sanitizadas de Nginx/puertos. Si falla autenticación o permisos, detener sin cambiar roles ni contraseñas.

**D7C/D7D aún pendientes:** seeds ficticios, firma QA, controles de acceso y rollback de vhost; instalación autorizada por separado y ensayo físico M01–M11/N01–N06. Ninguna escritura OFF-04 permitida.

**No ejecutar post-DDL los verificadores B2/C1 del estado de esquema vacío; no repetir la migración C2.**

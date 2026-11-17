# VINTO OFF-03D.2 — PostgreSQL de QA: aprovisionamiento aislado por fases

**17 de noviembre de 2026. Estado: CANDIDATO / SOLO GITHUB.**

## Evidencia de VPS aportada por operador (sin acceso remoto desde este PR)

- Piloto actual: `vinto-mvp-frontend` `127.0.0.1:3100`, `vinto-mvp-backend` `127.0.0.1:8100`, PostgreSQL `vinto-mvp-postgres` `127.0.0.1:6544`, base `vinto_piloto`, SHA `771ff334179d470605f6295e6cb29a5ce7dbf18f`.
- TVC: `vinto-web` y `postgres-vinto` separados; **no tocar** `/opt/vinto-web`, puerto `6543` o servicios TVC.
- QA: DNS `qa-vinto-mvp.baltrekservices.com` -> `51.79.65.225`, certificado Let's Encrypt válido hasta 2027-02-15; `https://qa-vinto-mvp.baltrekservices.com/qa-ready` devuelve `VINTO_QA_HTTPS_READY` y `QA_SNI=PASS`, según pruebas aportadas el 17 de noviembre.
- Recursos VPS: 22 GiB RAM, 173 GiB libres de disco en auditoría anterior, puertos candidatos 3110/8110/6554 disponibles en ese momento. **Revalidar inmediatamente antes de provisionar**.
- `docker compose` no está disponible; **no instalar Docker Compose global ni ejecutar la plantilla antigua del piloto**.

Las pruebas reportadas verifican conectividad HTTPS y no demuestran que exista una base o aplicación QA. El release offline sigue en PRs Draft #184–#194, no fusionados ni activos en la VPS.

## Reglas de frontera

Este PR prepara **solo PostgreSQL 17 vacío** en un clúster Docker nuevo, sin inventario de usuarios/recetas ni migraciones. El script no usa ni modifica el volumen, red, puerto, rol o base del piloto y TVC. No contiene credenciales reales, no lee los `.env` existentes, no despliega código ni cambia Nginx o systemd.

| Recurso | Existente — no tocar | Propuesto para QA |
|---|---|---|
| Contenedor | `vinto-mvp-postgres`, `postgres-vinto` | `vinto-qa-postgres` |
| Puerto host | `6544`, `6543` | `127.0.0.1:6554` |
| Red Docker | `vinto-mvp-internal`, `vinto_default` | `vinto-qa-internal` |
| Volumen Docker | datos existentes | `vinto-qa-offline-pgdata` |
| DB | `vinto_piloto` | `vinto_qa_offline` |
| Superusuario DB | identidades existentes | `vinto_qa_bootstrap` exclusivo |
| Contraseña | secretos existentes | nueva aleatoria de 256 bits en `/etc/vinto-qa/postgres-bootstrap.password` (root 0600); nunca imprimir |

Docker monta el archivo secreto de solo lectura y usa `POSTGRES_PASSWORD_FILE`; la contraseña **no se coloca en un argumento de proceso ni como valor del entorno Docker**. El rol bootstrap **no** es el rol de la aplicación. Antes de conectar la API se deben ejecutar con revisión y aprobación independiente los scripts versionados de roles de mínimo privilegio, migraciones y grants, exclusivamente contra este clúster.

## Fase A — Solo lectura (operador VPS)

Desde un checkout o archivo exacto del PR candidato, **primero inspeccionar el script**:

```bash
bash -n scripts/off-03d2-qa-postgres.sh
sudo bash scripts/off-03d2-qa-postgres.sh preflight
```

**PASS requerido:** `QA_HTTPS=PASS`, `PILOT_TVC_RUNNING=PASS`, `QA_PORT_6554=AVAILABLE`, `QA_NAMES_COLLISION=NONE`, `POSTGRES17_IMAGE_LOCAL=PASS`, `OFF03D2_PREFLIGHT=PASS`, `CHANGES_MADE=NONE`.

Bloquear si falta la imagen local `postgres:17`; no se descarga una imagen implícitamente. No ejecutar `docker compose` ni scripts `deploy/mvp/scripts/deploy.sh` apuntando al piloto.

## Fase B — Escritura estrictamente QA (requiere aprobación separada)

```bash
sudo env CONFIRM_QA_DB_CREATE=YES bash scripts/off-03d2-qa-postgres.sh install
```

**No ejecutar sin autorización explícita de creación de recursos QA en la VPS.** El `install` repite el preflight y se niega a continuar si existe alguno de los nombres reservados. Crea solo nueva ruta de secretos, nueva red, nuevo volumen y contenedor PostgreSQL 17. Límite 1 GiB RAM / 2 CPU / PID 256. Si un paso falla, **conserva recursos QA para auditoría**; no borra el volumen ni el secreto automáticamente.

## Fase C — Verificar aislamiento (solo lectura)

```bash
sudo bash scripts/off-03d2-qa-postgres.sh verify
```

Exige contenedor saludable y etiqueta QA, imagen `postgres:17`, red exclusiva, *PortBindings* en `127.0.0.1:6554`, volumen exclusivo y metadatos PostgreSQL `vinto_qa_offline` / `vinto_qa_bootstrap`, con `vinto_piloto` **ausente dentro del clúster QA**. `OFF03D2_VERIFY=PASS_BOOTSTRAP_ONLY` no avala todavía autenticación, roles aplicativos, migraciones o funciones offline.

El operador debe contrastar que los servicios piloto/TVC siguen activos, sin imprimir secretos ni datos de usuarios. No se ejecutan migraciones hasta que el gate de base aislada pase.

## Gate del siguiente incremento OFF-03D.3

1. Preparar roles `vinto_app`, `vinto_migrator`, `vinto_reference` y opcional `vinto_identity` en el **clúster nuevo**; SQL versionado `backend/roles`, respetar el orden y los permisos mínimos. Ninguna contraseña en Git ni stdout.
2. Ejecutar migraciones únicamente sobre `vinto_qa_offline`, con rol migrador y comprobación explícita del host `127.0.0.1:6554`; nunca `vinto_piloto`.
3. Preparar catálogo, máquinas MP1/MP3, 4 formularios Calidad, QA operator ficticio y concesiones efectivas con una política de datos sintéticos.
4. Crear API y frontend QA como servicios **propios** en `127.0.0.1:8110` y `127.0.0.1:3110`; no compartir `/opt/vinto-mvp-web/current`, `.env` o runtime del piloto. Build frontend con `NEXT_PUBLIC_API_URL=https://qa-vinto-mvp.baltrekservices.com` **en build time**.
5. Activar solo en QA `OFFLINE_SCOPE_ISSUE_ENABLED`, `OFFLINE_QUALITY_PACKAGE_ISSUE_ENABLED` y semilla Ed25519 exclusiva; comprobar cabeceras de proxy confiadas solo desde loopback. Publicar `/` y `/api` de QA por HTTPS tras autorización propia, sin tocar los bloques piloto/TVC.
6. Ejecutar `scripts/off-03d1-https-preflight.sh` desde la red del móvil, luego M01-M11 y N01-N06 de OFF-03C.3 en dispositivo físico.

**Sin merge de los PR Draft ni despliegue del piloto. OFF-04 de captura sigue fuera de alcance.**
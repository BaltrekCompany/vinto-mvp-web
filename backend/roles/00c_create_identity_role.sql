-- MF-13-01D.3B.2: vinto_identity, el rol de IDENTIDAD (login, logout, administración de usuarios/sectores/concesiones y CLI). SEPARADO de 00_create_roles.sql a propósito:
-- crearlo es OPCIONAL y no cambia nada para quien no lo use (deploy.sh no ejecuta este archivo; ver backend/roles/README.md, sección D.3B.2).
--
-- Ejecuta el administrador del clúster. Mismo patrón que 00_create_roles.sql / 00b: idempotente, marcado con COMMENT ON ROLE, aborta sin tocar nada si el nombre ya existe y no fue
-- creado por este script, y la contraseña se lee de una variable de ENTORNO (IDENTITY_PASSWORD), nunca de un argumento -v. No es superusuario, no crea bases ni roles, no es
-- propietario de nada. No tiene privilegios hasta ejecutar 03c_d3b2_identity_role_grants.sql.

\set ON_ERROR_STOP on

\getenv identity_password IDENTITY_PASSWORD

SELECT (NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_identity'))::text AS should_create \gset
\if :should_create
CREATE ROLE vinto_identity LOGIN PASSWORD :'identity_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE vinto_identity SET search_path = '';
COMMENT ON ROLE vinto_identity IS 'mf-13-01d3b2: rol de identidad (login, administración de usuarios y concesiones), creado por backend/roles/00c_create_identity_role.sql';
\else
SELECT EXISTS (SELECT 1 FROM pg_shdescription d JOIN pg_roles r ON r.oid = d.objoid
               WHERE r.rolname = 'vinto_identity' AND d.description LIKE 'mf-13-01d3b2:%')::text AS is_ours \gset
\if :is_ours
\echo 'vinto_identity ya existe y es de mf-13-01d3b2: se omite su creación'
\else
DO $$ BEGIN RAISE EXCEPTION 'vinto_identity ya existe y NO está marcado como propio de mf-13-01d3b2: posible colisión de nombres; abortando sin modificarlo'; END $$;
\endif
\endif

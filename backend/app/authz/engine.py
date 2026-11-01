"""Motor central de autorización efectiva por usuario, máquina y formulario (MF-13-01D.1). SOLO LECTURA y NO conectado todavía a ningún endpoint.

Una operación funcional queda AUTORIZADA únicamente si se cumplen A LA VEZ:
  1. usuario existente, activo y autenticado (el llamador entrega un `AuthenticatedUser`; el motor NO se fía de sus permisos ni sectores: todo se relee de la base de datos);
  2. permiso funcional derivado de sus perfiles ACTIVOS (unión de los perfiles; la concesión nunca lo sustituye);
  3. sector de la máquina activo, operativo (app/sectors.py) y concedido al usuario (la concesión de una máquina NUNCA concede el sector);
  4. máquina y formulario activos;
  5. la política de la ruta admite el formulario (app/authz/policies.py);
  6. versión publicada VIGENTE del formulario —la de número más alto de CUALQUIER área, como la ve el catálogo y exige el servicio de concesiones— cuya área es la de la política y que
     está vinculada a la máquina; un vínculo solo histórico, o una versión vigente de otra área, no cuenta (MF-13-01D.1.1);
  7. concesión ACTIVA de la terna exacta (usuario, máquina, formulario).
No hay permisos implícitos: cualquier duda es una denegación, y un fallo de infraestructura (tabla ausente, privilegio, bloqueo, tiempo, red) levanta AuthorizationUnavailable —NUNCA se
interpreta como acceso concedido—.

Resultado explícito (`Decision`): permitido / denegado (`forbidden`) / recurso inexistente (`not_found`). La razón interna (`Decision.reason`) es para auditoría; las respuestas públicas
(app/authz/errors.py) son fijas.

── Concurrencia y revocación ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
Una operación de escritura debe llamar a `authorize(..., lock=True)` (o `require`) DENTRO de la MISMA transacción que registra la captura. Con `lock=True` cada fila que decide el resultado se
lee con `FOR SHARE` (donde el rol puede bloquear, ver más abajo), que se mantiene hasta COMMIT/ROLLBACK de esa transacción:
  - `FOR SHARE` bloquea un `UPDATE` de `revoked_at` (y cualquier UPDATE/DELETE de la fila) hasta que la captura termine, y una revocación ya confirmada se ve (la lectura se reevalúa con
    `revoked_at IS NULL`): una captura que empieza después de una revocación confirmada se deniega, y una revocación no puede colarse entre la autorización y el registro.
  - `FOR KEY SHARE` NO sirve: el UPDATE de `revoked_at` no cambia columnas clave (el índice único es parcial y no cuenta como clave) y no choca con él. Lo demuestran las pruebas con dos conexiones.
Se exige un bloque `connection.transaction()` explícito (las conexiones son autocommit: fuera de él los bloqueos se liberarían al terminar cada sentencia): sin transacción abierta el motor
levanta AuthorizationUnavailable en lugar de "autorizar" sin proteger nada. Requiere READ COMMITTED (el valor por defecto); bajo REPEATABLE READ un conflicto da SerializationFailure, que
también es AuthorizationUnavailable (falla cerrado).

QUÉ SE BLOQUEA (límite de privilegios): PostgreSQL exige privilegio UPDATE para cualquier bloqueo de fila (FOR SHARE y también FOR KEY SHARE). El rol `vinto_app` (backend/roles/03_table_grants.sql)
lo tiene en usuario, perfil, perfil-de-usuario, sector, máquina y concesión, pero NO en `user_sector` (solo SELECT/INSERT/DELETE) ni en `vinto_config.*` (solo SELECT). Pedir el bloqueo allí daría
42501 en producción y el motor negaría TODO (503). Por eso solo se bloquean las filas que el rol puede bloquear: usuario, perfiles, máquina+sector y concesión. Riesgos residuales, documentados y
con propuesta de endurecimiento en docs/MF-13-01D1-motor-autorizacion-efectiva.md: (a) retirar una concesión de SECTOR concurrente a una captura (DELETE de `user_sector`, no bloqueable); la
RESUELTO para la ruta de la aplicación en MF-13-01D.3A: `revoke_sector` toma `FOR NO KEY UPDATE` sobre la fila del usuario, que choca con el `FOR SHARE` de este motor; (b) cambios del catálogo/vínculos
(`vinto_config`), que solo hace el importador de referencias fuera de línea.

Orden de adquisición de bloqueos (fijo, para evitar interbloqueos): usuario → perfiles del usuario → máquina y su sector → concesión (la fila más disputada, al final). Quien MODIFICA esas
filas (administración de concesiones, desactivación de usuarios) toca UNA sola fila de autorización por transacción, así que no puede formar un ciclo con este orden. Orden global recomendado para las rutas: bloqueo asesor `vinto-capture-id` (ya existente) → este motor →
bloqueo asesor de máquina y asignación (ya existentes) → inserciones.

Reintentos idempotentes: llamar de nuevo al motor en la misma transacción es inofensivo (los bloqueos son reentrantes). La repetición de una captura ya guardada se vuelve a AUTORIZAR (una
revocación posterior la deniega): es la opción segura ante una regla funcional ambigua y se documenta en docs/MF-13-01D1-motor-autorizacion-efectiva.md.
"""

import uuid
from dataclasses import dataclass

import psycopg
from psycopg import pq

from app.auth.permissions import permissions_for_profiles
from app.auth.service import AuthenticatedUser
from app.authz.errors import AuthorizationDenied, AuthorizationUnavailable, ResourceNotFound
from app.authz.policies import OperationPolicy, policy_for
from app.sectors import is_operational_sector

ALLOWED, FORBIDDEN, NOT_FOUND = "allowed", "forbidden", "not_found"

# Razones internas (estables; para auditoría y pruebas, nunca para el cliente).
R_ALLOWED = "ALLOWED"
R_USER_NOT_FOUND, R_MACHINE_NOT_FOUND, R_FORM_NOT_FOUND = "USER_NOT_FOUND", "MACHINE_NOT_FOUND", "FORM_NOT_FOUND"
R_USER_INACTIVE, R_PERMISSION_MISSING = "USER_INACTIVE", "PERMISSION_MISSING"
R_SECTOR_INACTIVE, R_SECTOR_NOT_OPERATIONAL, R_SECTOR_NOT_GRANTED = "SECTOR_INACTIVE", "SECTOR_NOT_OPERATIONAL", "SECTOR_NOT_GRANTED"
R_MACHINE_INACTIVE, R_FORM_INACTIVE = "MACHINE_INACTIVE", "FORM_INACTIVE"
R_POLICY_DOES_NOT_ADMIT_FORM, R_NO_EFFECTIVE_VERSION, R_PAIR_NOT_OFFERED = "POLICY_DOES_NOT_ADMIT_FORM", "NO_EFFECTIVE_VERSION", "PAIR_NOT_OFFERED"
R_EFFECTIVE_VERSION_OTHER_AREA = "EFFECTIVE_VERSION_OTHER_AREA"
R_GRANT_MISSING = "GRANT_MISSING"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    kind: str  # allowed | forbidden | not_found
    reason: str  # razón interna estable
    operation: str
    user_id: uuid.UUID
    machine_code: object
    form_code: object
    effective_version: int | None = None  # versión publicada vigente con la que se autorizó
    grant_id: uuid.UUID | None = None  # concesión activa que respalda la autorización


def _require_open_transaction(connection) -> None:
    """Con lock=True los bloqueos solo duran dentro de una transacción: en autocommit y fuera de `connection.transaction()` no habría protección, así que se rechaza (falla cerrado)."""
    if connection.autocommit and connection.info.transaction_status == pq.TransactionStatus.IDLE:
        raise AuthorizationUnavailable("NO_TRANSACTION")


def authorize(connection, user: AuthenticatedUser, operation, machine_code, form_code, *, lock: bool = False) -> Decision:
    """Decide si `user` puede ejecutar `operation` sobre (máquina, formulario). `lock=True` es OBLIGATORIO para las operaciones de escritura (ver el módulo).

    Lanza AuthorizationUnavailable si no se pudo decidir. TypeError ante un llamador mal formado (usuario no autenticado u operación desconocida): un error de programación, no una autorización.
    """
    if not isinstance(user, AuthenticatedUser):
        raise TypeError("authorize exige un AuthenticatedUser (un principal autenticado)")
    policy = policy_for(operation)
    if lock:
        _require_open_transaction(connection)
    try:
        return _evaluate(connection, user.user_id, policy, machine_code, form_code, lock)
    except psycopg.Error as error:
        raise AuthorizationUnavailable(error.sqlstate or type(error).__name__) from None


def require(connection, user: AuthenticatedUser, operation, machine_code, form_code, *, lock: bool = True) -> Decision:
    """Como `authorize`, pero levanta AuthorizationDenied / ResourceNotFound si no se permite. Por defecto toma los bloqueos (uso en rutas de escritura)."""
    decision = authorize(connection, user, operation, machine_code, form_code, lock=lock)
    if decision.allowed:
        return decision
    if decision.kind == NOT_FOUND:
        raise ResourceNotFound(decision)
    raise AuthorizationDenied(decision)


def _evaluate(connection, user_id, policy: OperationPolicy, machine_code, form_code, lock: bool) -> Decision:
    share = " FOR SHARE" if lock else ""

    def result(allowed, kind, reason, **extra) -> Decision:
        return Decision(allowed, kind, reason, policy.operation.value, user_id, machine_code, form_code, **extra)

    def deny(reason) -> Decision:
        return result(False, FORBIDDEN, reason)

    def missing(reason) -> Decision:
        return result(False, NOT_FOUND, reason)

    # 1 · usuario (bloqueo 1)
    row = connection.execute('SELECT active FROM vinto_master."user" WHERE id = %s' + share, (user_id,)).fetchone()
    if row is None:
        return missing(R_USER_NOT_FOUND)
    if not row[0]:
        return deny(R_USER_INACTIVE)
    # 2 · permiso derivado de los perfiles ACTIVOS (bloqueo 2)
    codes = [r[0] for r in connection.execute(
        "SELECT p.code FROM vinto_master.user_profile up JOIN vinto_master.profile p ON p.id = up.profile_id WHERE up.user_id = %s AND p.active ORDER BY p.id"
        + (" FOR SHARE OF up, p" if lock else ""), (user_id,)).fetchall()]
    if policy.permission not in permissions_for_profiles(codes):
        return deny(R_PERMISSION_MISSING)
    # 3 · máquina y su sector (bloqueo 3) y concesión de sector (SIN bloqueo: vinto_app no tiene UPDATE sobre user_sector)
    machine = connection.execute(
        "SELECT m.id, m.active, s.id, s.code, s.active FROM vinto_master.machine m JOIN vinto_master.sector s ON s.id = m.sector_id WHERE m.code = %s"
        + (" FOR SHARE OF m, s" if lock else ""), (machine_code,)).fetchone() if isinstance(machine_code, str) else None
    if machine is None:
        return missing(R_MACHINE_NOT_FOUND)
    machine_id, machine_active, sector_id, sector_code, sector_active = machine
    sector_grant = connection.execute("SELECT 1 FROM vinto_master.user_sector WHERE user_id = %s AND sector_id = %s", (user_id, sector_id)).fetchone()
    if not sector_active:
        return deny(R_SECTOR_INACTIVE)
    if not is_operational_sector(sector_code):
        return deny(R_SECTOR_NOT_OPERATIONAL)
    if sector_grant is None:
        return deny(R_SECTOR_NOT_GRANTED)  # la concesión de la máquina jamás concede el sector
    if not machine_active:
        return deny(R_MACHINE_INACTIVE)
    # 4 · formulario (SIN bloqueo: vinto_config es de solo lectura para vinto_app)
    form = connection.execute("SELECT id, active FROM vinto_config.form WHERE code = %s", (form_code,)).fetchone() if isinstance(form_code, str) else None
    if form is None:
        return missing(R_FORM_NOT_FOUND)
    form_id, form_active = form
    if not form_active:
        return deny(R_FORM_INACTIVE)
    # 5 · la política de ESTA ruta admite el formulario (conjuntos disjuntos por ruta)
    if form_code not in policy.admitted():
        return deny(R_POLICY_DOES_NOT_ADMIT_FORM)
    # 6 · versión publicada vigente vinculada a la máquina (SIN bloqueo, mismo motivo; solo el importador de referencias escribe aquí)
    version = connection.execute(
        "SELECT fv.id, fv.version_number, fv.area FROM vinto_config.form_version fv WHERE fv.form_id = %s AND fv.status = 'published' ORDER BY fv.version_number DESC LIMIT 1",
        (form_id,)).fetchone()
    if version is None:
        return deny(R_NO_EFFECTIVE_VERSION)
    if version[2] != policy.area:
        return deny(R_EFFECTIVE_VERSION_OTHER_AREA)  # la vigente es de otra área: el catálogo ya no ofrece este par para esta ruta (una versión anterior del área no lo revive)
    linked = connection.execute("SELECT 1 FROM vinto_config.form_version_machine WHERE form_version_id = %s AND machine_id = %s", (version[0], machine_id)).fetchone()
    if linked is None:
        return deny(R_PAIR_NOT_OFFERED)  # un vínculo que solo existe en una versión histórica no cuenta
    # 7 · concesión ACTIVA de la terna exacta (bloqueo 4: FOR SHARE bloquea un UPDATE de revoked_at)
    grant = connection.execute(
        "SELECT id FROM vinto_master.user_machine_form_grant WHERE user_id = %s AND machine_id = %s AND form_id = %s AND revoked_at IS NULL" + share, (user_id, machine_id, form_id)).fetchone()
    if grant is None:
        return deny(R_GRANT_MISSING)
    return result(True, ALLOWED, R_ALLOWED, effective_version=version[1], grant_id=grant[0])

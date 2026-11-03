"""MF-13-03B PR5: visibilidad de LECTURA por máquina (asignaciones, líneas activas, OT y capturas centrales) para perfiles que no gestionan.

Define "tiene acceso operativo a una máquina" SIN crear un sistema paralelo: una máquina es visible para el usuario si el motor de autorización efectiva
(app/authz/engine.py) PERMITE al menos una operación de captura sobre (máquina, formulario) con una concesión ACTIVA. Es decir, el motor aplica todo lo
de MF-13-01 (usuario activo, permiso de los perfiles activos, sector concedido y operativo, máquina y formulario activos, versión vigente vinculada y
concesión activa de la terna). Consecuencias:
  - La concesión es por máquina Y formulario: cualquier formulario de la política de la operación abre la VISIBILIDAD de las líneas de esa máquina. La
    CAPTURA de un formulario concreto sigue exigiendo su propia concesión (compuerta de cada POST); ver ≠ capturar.
  - Cada operación usa su permiso y su área: una concesión de un formulario de Calidad NO abre producción (un perfil sin QUALITY_CAPTURE ni siquiera evalúa las
    operaciones de Calidad; un perfil de producción no evalúa un formulario de Calidad como producción). Sin permiso del perfil, sin sector o con la concesión
    revocada, la máquina no es visible.
  - El sector NO equivale a la máquina: leer un sector no concede ninguna máquina.

Quién NO está restringido: perfiles que gestionan (`work_order.manage` Jefatura o `assignment.manage` Supervisión) conservan su alcance por sector. Operación,
Calidad y DATA_BALTREK solo ven lo que este módulo autoriza (DATA_BALTREK no tiene permisos de captura, así que no ve ninguna línea: falla cerrado).

Cuándo se aplica (servidor; el cliente no puede cambiarlo):
  - Contrato operativo nuevo (`/active-lines`, `/operational-lines`): SIEMPRE para los no gestores (no tiene consumidores anteriores).
  - Rutas históricas (`/active`, listado de asignaciones, OT, capturas centrales): cuando `authz_assignment_reads_mode == "enforce"` O la compuerta multimáquina
    está encendida (no se puede publicar una OT multimáquina sin esta protección). `observe` registra qué se ocultaría y NO cambia la respuesta. `off` + compuerta
    apagada = comportamiento anterior (alcance por sector): brecha conocida y documentada hasta decidir `enforce`.
Un fallo del motor levanta AuthorizationUnavailable (503): nunca se interpreta como acceso.
"""

import logging

from app.auth.permissions import ASSIGNMENT_MANAGE, WORK_ORDER_MANAGE
from app.authz.engine import authorize
from app.authz.policies import POLICIES
from app.config import settings

logger = logging.getLogger("vinto.authz")
OFF, OBSERVE, ENFORCE = "off", "observe", "enforce"


def unrestricted(user) -> bool:
    """Jefatura (`work_order.manage`) y Supervisión (`assignment.manage`) conservan su alcance por sector."""
    return user.can(WORK_ORDER_MANAGE) or user.can(ASSIGNMENT_MANAGE)


def authorized_machine_codes(connection, user) -> frozenset:
    """Códigos de las máquinas cuyas líneas puede ver el usuario según el motor (ver el módulo). Solo se evalúan las ternas con concesión ACTIVA: condición
    necesaria del paso 7 del motor, así que es una poda y no una decisión; la decisión final es SIEMPRE del motor."""
    pairs = connection.execute(
        """SELECT m.code, f.code FROM vinto_master.user_machine_form_grant g JOIN vinto_master.machine m ON m.id = g.machine_id
           JOIN vinto_config.form f ON f.id = g.form_id WHERE g.user_id = %s AND g.revoked_at IS NULL ORDER BY m.code, f.code""", (user.user_id,)).fetchall()
    visible = set()
    for machine_code, form_code in pairs:
        if machine_code in visible:
            continue
        for operation, policy in POLICIES.items():
            if form_code in policy.admitted() and authorize(connection, user, operation, machine_code, form_code, lock=False).allowed:
                visible.add(machine_code)
                break
    return frozenset(visible)


def operational_scope(connection, user):
    """Contrato operativo nuevo: None (sin restricción de máquina) para quien gestiona; si no, el conjunto de máquinas autorizadas (puede ser vacío)."""
    return None if unrestricted(user) else authorized_machine_codes(connection, user)


def read_filter_active() -> bool:
    return settings.authz_assignment_reads_mode == ENFORCE or settings.work_orders_multi_machine_enabled is True


def legacy_scope(connection, user, route: str):
    """Rutas históricas: ver el módulo. `observe` calcula y registra, pero devuelve None (sin filtrar)."""
    if unrestricted(user):
        return None
    if read_filter_active():
        return authorized_machine_codes(connection, user)
    if settings.authz_assignment_reads_mode == OBSERVE:
        try:
            visible = authorized_machine_codes(connection, user)
            logger.info("authz reads mode=observe route=%s machines_visible=%d (sin filtrar: solo registro)", route, len(visible))
        except Exception as error:  # noqa: BLE001 — observar nunca debe romper la lectura
            logger.error("authz reads mode=observe route=%s error=%s", route, type(error).__name__)
    return None

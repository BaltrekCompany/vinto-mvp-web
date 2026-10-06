"""Matriz de permisos por perfil, en código y sin acceso a la base de datos.

Un perfil desconocido no concede nada. Un nombre de permiso desconocido es un error de programación
(ValueError) en lugar de una denegación silenciosa.

DATA_BALTREK administra catálogos y usuarios, pero NO recibe permisos funcionales de planta
(work_order.manage, assignment.manage, production.capture, quality.capture, quality.release): la
administración técnica no debe operar en nombre de la planta.
"""

from typing import Iterable

WORK_ORDER_READ = "work_order.read"
WORK_ORDER_MANAGE = "work_order.manage"
ASSIGNMENT_READ = "assignment.read"
ASSIGNMENT_MANAGE = "assignment.manage"
PRODUCTION_CAPTURE = "production.capture"
QUALITY_CAPTURE = "quality.capture"
QUALITY_RELEASE = "quality.release"
CATALOG_READ = "catalog.read"
CATALOG_MANAGE = "catalog.manage"
USER_MANAGE = "user.manage"

ALL_PERMISSIONS = frozenset({
    WORK_ORDER_READ, WORK_ORDER_MANAGE, ASSIGNMENT_READ, ASSIGNMENT_MANAGE, PRODUCTION_CAPTURE,
    QUALITY_CAPTURE, QUALITY_RELEASE, CATALOG_READ, CATALOG_MANAGE, USER_MANAGE,
})

JEFATURA = "JEFATURA"
SUPERVISION = "SUPERVISION"
OPERACION = "OPERACION"
CALIDAD = "CALIDAD"
DATA_BALTREK = "DATA_BALTREK"

PROFILE_PERMISSIONS: dict[str, frozenset[str]] = {
    JEFATURA: frozenset({WORK_ORDER_READ, WORK_ORDER_MANAGE, ASSIGNMENT_READ, CATALOG_READ}),
    SUPERVISION: frozenset({WORK_ORDER_READ, ASSIGNMENT_READ, ASSIGNMENT_MANAGE, CATALOG_READ}),
    OPERACION: frozenset({WORK_ORDER_READ, ASSIGNMENT_READ, PRODUCTION_CAPTURE, CATALOG_READ}),
    CALIDAD: frozenset({WORK_ORDER_READ, ASSIGNMENT_READ, QUALITY_CAPTURE, QUALITY_RELEASE, CATALOG_READ}),
    DATA_BALTREK: frozenset({WORK_ORDER_READ, ASSIGNMENT_READ, CATALOG_READ, CATALOG_MANAGE, USER_MANAGE}),
}


def permissions_for_profiles(profile_codes: Iterable[str]) -> frozenset[str]:
    """Unión de los permisos de todos los perfiles dados; los desconocidos no aportan nada."""
    granted: set[str] = set()
    for code in profile_codes:
        granted |= PROFILE_PERMISSIONS.get(code, frozenset())
    return frozenset(granted)


def has_permission(profile_codes: Iterable[str], permission: str) -> bool:
    if permission not in ALL_PERMISSIONS:
        raise ValueError(f"Permiso desconocido: {permission!r}")
    return permission in permissions_for_profiles(profile_codes)

"""Alcance operativo por sector: ÚNICO punto de verdad de qué sectores pueden operar.

Un sector "operativo" es el que el backend acepta para OT, asignaciones, capturas, Bobinas y Calidad. Cualquier máquina, OT, asignación,
captura o Bobina de un sector que NO es operativo se comporta como inexistente (404) o se rechaza (422): los servicios filtran por
`operational_sector_codes()` en SQL y por `is_operational_sector()` en Python. Ningún otro módulo debe repetir la lista.

Reglas de seguridad de esta configuración:
- Hoy SOLO BOBINAS es operativo. REBOBINADO y CONVERSION están RECONOCIDOS (para poder reservar su código y validar) pero NO habilitados.
- La lista se valida al importar el módulo (`validate_operational_sectors`): una edición incorrecta impide arrancar el backend en lugar de abrir un
  sector por accidente. No hay variable de entorno ni interruptor en tiempo de ejecución: habilitar un sector exige un cambio de código revisado.
- Habilitar un sector NO concede permisos. Los permisos siguen siendo por PERFIL (app/auth/permissions.py), sin relación con sectores ni máquinas;
  este módulo no importa nada de `app.auth` y `app.auth` no importa este módulo. Lo que sí cambia al habilitar un sector es el alcance de DATOS:
  todas las máquinas del sector pasan a ser operables por los perfiles que ya tienen el permiso correspondiente (ver backend/README.md).
- Habilitar un sector requiere antes, y fuera de este módulo, datos aprobados: sector, máquinas, turnos con vigencia, relaciones artículo-máquina y
  formularios publicados para esas máquinas. Este módulo no inventa ninguno de ellos.
"""

from collections.abc import Iterable

SECTOR_BOBINAS = "BOBINAS"
SECTOR_REBOBINADO = "REBOBINADO"
SECTOR_CONVERSION = "CONVERSION"

# Lista CERRADA de códigos de sector que el producto reconoce. Un código fuera de esta lista nunca puede ser operativo.
KNOWN_SECTOR_CODES = frozenset({SECTOR_BOBINAS, SECTOR_REBOBINADO, SECTOR_CONVERSION})

# Sectores operativos por defecto. M1-A mantiene BOBINAS como único sector habilitado.
DEFAULT_OPERATIONAL_SECTORS = (SECTOR_BOBINAS,)


class SectorConfigError(ValueError):
    """La configuración de sectores operativos no es válida (se detecta al importar el módulo)."""


def validate_operational_sectors(codes) -> tuple[str, ...]:
    """Devuelve la configuración como tupla inmutable o lanza SectorConfigError.

    Exige: una colección (no un texto suelto), no vacía, sin repetidos, solo códigos reconocidos y escritos exactamente como en KNOWN_SECTOR_CODES
    (mayúsculas, sin espacios), y que BOBINAS siga operativo (los demás sectores se suman a la base de Bobinas, nunca la reemplazan).
    """
    if isinstance(codes, (str, bytes)) or not isinstance(codes, Iterable):
        raise SectorConfigError("Los sectores operativos deben ser una colección de códigos, no un texto")
    items = tuple(codes)
    if not items:
        raise SectorConfigError("Debe haber al menos un sector operativo")
    if not all(isinstance(code, str) for code in items):
        raise SectorConfigError("Los códigos de sector deben ser texto")
    if len(set(items)) != len(items):
        raise SectorConfigError("Códigos de sector repetidos")
    unknown = sorted(code for code in items if code not in KNOWN_SECTOR_CODES)
    if unknown:
        raise SectorConfigError(f"Sector no reconocido: {', '.join(repr(code) for code in unknown)}")
    if SECTOR_BOBINAS not in items:
        raise SectorConfigError("BOBINAS debe seguir siendo un sector operativo")
    return items


_OPERATIONAL = validate_operational_sectors(DEFAULT_OPERATIONAL_SECTORS)


def operational_sector_codes() -> tuple[str, ...]:
    """Códigos de los sectores operativos (tupla inmutable). Úsala para filtrar en SQL: `s.code = ANY(%s)` con `list(...)`."""
    return _OPERATIONAL


def is_operational_sector(code) -> bool:
    return isinstance(code, str) and code in _OPERATIONAL

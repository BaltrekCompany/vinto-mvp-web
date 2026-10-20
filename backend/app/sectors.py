"""Alcance operativo por sector: ÚNICO punto de verdad de qué sectores pueden operar.

Un sector "operativo" es el que el backend acepta para OT, asignaciones, capturas, Bobinas y Calidad. Cualquier máquina, OT, asignación,
captura o Bobina de un sector que NO es operativo se comporta como inexistente (404) o se rechaza (422): los servicios filtran por
`operational_sector_codes()` en SQL y por `is_operational_sector()` en Python. Ningún otro módulo debe repetir la lista.

Reglas de seguridad de esta configuración:
- BOBINAS y, desde CLOUD-DEP G.12-C4-COMPLETE, REBOBINADO son operativos para el piloto de QA. CONVERSION está RECONOCIDO (para poder reservar su
  código y validar) pero NO habilitado: sus 3 candidatos de captura (P1-12/13/16) son hipótesis de prueba con un contrato distinto al de la
  definición legacy aprobada, no una homologación -- activar CONVERSION sin formularios reales que respalden ese contrato no tendría efecto
  verificable y expondría datos bajo un código de formulario que no representa lo que dice representar.
- La lista se valida al importar el módulo (`validate_operational_sectors`): una edición incorrecta impide arrancar el backend en lugar de abrir un
  sector por accidente. No hay variable de entorno ni interruptor en tiempo de ejecución: habilitar un sector exige un cambio de código revisado.
- Habilitar un sector NO concede permisos. Los permisos siguen siendo por PERFIL (app/auth/permissions.py), sin relación con sectores ni máquinas;
  este módulo no importa nada de `app.auth` y `app.auth` no importa este módulo. Lo que sí cambia al habilitar un sector es el alcance de DATOS:
  todas las máquinas del sector pasan a ser operables por los perfiles que ya tienen el permiso correspondiente (ver backend/README.md).
- Habilitar un sector requiere antes, y fuera de este módulo, datos aprobados: sector, máquinas, turnos con vigencia, relaciones artículo-máquina y
  formularios publicados para esas máquinas. Este módulo no inventa ninguno de ellos. Para REBOBINADO esos datos son CANDIDATOS técnicos derivados
  de PRODUCTS_BY_MACHINE legacy (docs/M4-B1-homologacion-rebobinado.md), sin homologación formal de VINTO, pero autorizados explícitamente para
  este piloto de QA con datos sintéticos (CLOUD-DEP G.12-C4-COMPLETE sección A): la falta de homologación histórica no bloquea un piloto autorizado.
"""

from collections.abc import Iterable

SECTOR_BOBINAS = "BOBINAS"
SECTOR_REBOBINADO = "REBOBINADO"
SECTOR_CONVERSION = "CONVERSION"

# Lista CERRADA de códigos de sector que el producto reconoce. Un código fuera de esta lista nunca puede ser operativo.
KNOWN_SECTOR_CODES = frozenset({SECTOR_BOBINAS, SECTOR_REBOBINADO, SECTOR_CONVERSION})

# Sectores operativos por defecto. CLOUD-DEP G.12-C4-COMPLETE suma REBOBINADO (piloto de QA, datos candidatos).
DEFAULT_OPERATIONAL_SECTORS = (SECTOR_BOBINAS, SECTOR_REBOBINADO)


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


def scoped_sector_codes(sectors) -> tuple[str, ...]:
    """Sectores visibles para una operación: la intersección de los operativos con los autorizados al usuario.

    El alcance es OBLIGATORIO y no tiene valor por defecto: omitirlo (o pasar None) es un error, nunca «todos los sectores». Un llamador interno
    sin usuario (scripts, pruebas de servicio) que necesite acceso amplio debe pedirlo explícitamente con `operational_sector_codes()`; los routers
    pasan `user.sectors` (verificado por test). Una colección vacía significa NINGÚN sector: la ausencia de una concesión nunca amplía el acceso.
    Los códigos desconocidos o no operativos se descartan.
    """
    if sectors is None:
        raise SectorConfigError("El alcance de sectores es obligatorio: None no significa «todos»; indica los sectores explícitamente")
    if isinstance(sectors, (str, bytes)):
        raise SectorConfigError("Los sectores autorizados deben ser una colección de códigos, no un texto")
    allowed = set(sectors)
    return tuple(code for code in _OPERATIONAL if code in allowed)


def in_scope(code, sectors) -> bool:
    return isinstance(code, str) and code in scoped_sector_codes(sectors)


# Frentes visibles de la interfaz -> código de sector. «Calidad» no es un sector: agrupa capturas de formularios de área quality.
FRONT_SECTOR_CODES = {"Bobinas": SECTOR_BOBINAS, "Rebobinado": SECTOR_REBOBINADO, "Conversión": SECTOR_CONVERSION}

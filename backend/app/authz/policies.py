"""Políticas funcionales por operación para el motor de autorización efectiva (MF-13-01D.1).

Cada operación de ESCRITURA tiene su propia política: el permiso de perfil que exige, el área de formulario cuya versión publicada vigente se usa y el conjunto de formularios que su ruta
admite. Los conjuntos se leen EN VIVO de las constantes que ya usan los servicios de captura (no se copian, no se amplían y no se habilita ningún candidato): si una de esas constantes
cambia, el motor sigue a la ruta real. Los cuatro conjuntos son DISJUNTOS: un formulario admitido por una ruta especializada no queda autorizado en otra solo por pertenecer al catálogo
central (p. ej. VINTO-P1-03 se registra por /api/bobbins y NO por la captura central).

Este módulo no toca la base de datos ni ningún endpoint.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from app.auth.permissions import PRODUCTION_CAPTURE, QUALITY_CAPTURE


class Operation(str, Enum):
    PRODUCTION_CAPTURE = "production_capture"          # POST /api/captures (captura central de producción)
    BOBBIN_PRODUCTION = "bobbin_production"            # POST /api/bobbins (registro especializado F3, VINTO-P1-03)
    QUALITY_BOBBIN_CAPTURE = "quality_bobbin_capture"  # POST /api/quality/bobbins/{id}/captures (Calidad por bobina)
    QUALITY_MACHINE_CAPTURE = "quality_machine_capture"  # POST /api/quality/machines/{code}/captures (Calidad por máquina)


@dataclass(frozen=True)
class OperationPolicy:
    operation: Operation
    permission: str  # permiso funcional que deben dar los perfiles ACTIVOS (la concesión nunca lo sustituye)
    area: str  # área del formulario: la versión publicada vigente se busca en esa área
    route: str
    admitted: Callable[[], frozenset]  # formularios que la ruta admite HOY (se evalúa en cada decisión)


def _central() -> frozenset:
    from app import capture_service
    return frozenset(capture_service.CENTRAL_FORM_CODES)


def _bobbin_f3() -> frozenset:
    from app.bobbins import service
    return frozenset({service.FORM_CODE})


def _quality_by_bobbin() -> frozenset:
    from app.quality import capture_service as quality
    return frozenset(quality.CENTRAL_BOBBIN_FORM_CODES) | (frozenset(quality.BOBBIN_CANDIDATE_FORM_CODES) & frozenset(quality.ENABLED_BOBBIN_CANDIDATE_FORM_CODES))


def _quality_by_machine() -> frozenset:
    from app.quality import machine_capture_service
    return frozenset(machine_capture_service.MACHINE_QUALITY_FORM_CODES)


POLICIES: dict = {
    Operation.PRODUCTION_CAPTURE: OperationPolicy(Operation.PRODUCTION_CAPTURE, PRODUCTION_CAPTURE, "production", "POST /api/captures", _central),
    Operation.BOBBIN_PRODUCTION: OperationPolicy(Operation.BOBBIN_PRODUCTION, PRODUCTION_CAPTURE, "production", "POST /api/bobbins", _bobbin_f3),
    Operation.QUALITY_BOBBIN_CAPTURE: OperationPolicy(Operation.QUALITY_BOBBIN_CAPTURE, QUALITY_CAPTURE, "quality", "POST /api/quality/bobbins/{id}/captures", _quality_by_bobbin),
    Operation.QUALITY_MACHINE_CAPTURE: OperationPolicy(Operation.QUALITY_MACHINE_CAPTURE, QUALITY_CAPTURE, "quality", "POST /api/quality/machines/{code}/captures", _quality_by_machine),
}


def policy_for(operation) -> OperationPolicy:
    """Política de una operación conocida; una operación desconocida es un error de programación (nunca una autorización implícita)."""
    try:
        return POLICIES[Operation(operation)]
    except (ValueError, KeyError):
        raise TypeError(f"Operación desconocida: {operation!r}") from None

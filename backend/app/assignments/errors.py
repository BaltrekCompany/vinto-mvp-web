"""Errores de asignaciones. Heredan de WorkOrderError para compartir el manejador HTTP (código, estado y mensaje público)."""

from app.work_orders.errors import WorkOrderError


class AssignmentError(WorkOrderError):
    code = "ASSIGNMENT_ERROR"


class AssignmentNotFoundError(AssignmentError):
    http_status, code, public_message = 404, "ASSIGNMENT_NOT_FOUND", "Asignación no encontrada"


class BaselineLineNotFoundError(AssignmentError):
    http_status, code, public_message = 404, "BASELINE_LINE_NOT_FOUND", "Línea base no encontrada en esa orden"


class WorkOrderNotActivatableError(AssignmentError):
    http_status, code, public_message = 409, "WORK_ORDER_NOT_ACTIVATABLE", "La orden no se puede activar en su estado actual"


class OperationalVersionError(AssignmentError):
    http_status, code, public_message = 409, "OPERATIONAL_VERSION_ERROR", "La versión operativa no es coherente con la línea base"


class InvalidAssignmentFilterError(AssignmentError):
    http_status, code, public_message = 422, "INVALID_FILTER", "Filtro inválido"

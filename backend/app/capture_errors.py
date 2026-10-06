"""Errores de las capturas de producción. Comparten el manejador HTTP de WorkOrderError (estado, código y mensaje
público sin SQL); solo los 422 devuelven su detalle, que lista nombres de campos y nunca valores internos."""

from app.work_orders.errors import WorkOrderError


class CaptureError(WorkOrderError):
    code = "CAPTURE_ERROR"


class CaptureNotFoundError(CaptureError):
    http_status, code, public_message = 404, "CAPTURE_NOT_FOUND", "Captura no encontrada"


class CaptureValidationError(CaptureError):
    http_status, code, public_message = 422, "CAPTURE_VALIDATION", "Los valores de la captura no son válidos"


class UnsupportedFormError(CaptureError):
    http_status, code, public_message = 422, "UNSUPPORTED_FORM", "Formulario no soportado por este endpoint"


class CaptureIdempotencyConflictError(CaptureError):
    http_status, code, public_message = 409, "CAPTURE_IDEMPOTENCY_CONFLICT", "Ya existe una captura con ese identificador y contenido distinto"


class AssignmentNotActiveError(CaptureError):
    http_status, code, public_message = 409, "ASSIGNMENT_NOT_ACTIVE", "La asignación no está activa o no admite capturas"


class AssignmentStaleError(CaptureError):
    http_status, code, public_message = 409, "ASSIGNMENT_STALE", "La asignación corresponde a otro turno o fecha operativa; Supervisión debe reactivarla"


class DeviceInactiveError(CaptureError):
    http_status, code, public_message = 409, "DEVICE_INACTIVE", "El dispositivo está desactivado"


class DeviceMachineMismatchError(CaptureError):
    http_status, code, public_message = 409, "DEVICE_MACHINE_MISMATCH", "El dispositivo está asociado a otra máquina"


class FormNotAvailableError(CaptureError):
    http_status, code, public_message = 409, "FORM_NOT_AVAILABLE", "El formulario no está publicado para esa máquina"


class UnsupportedFormDefinitionError(CaptureError):
    http_status, code, public_message = 409, "UNSUPPORTED_FORM_DEFINITION", "La definición del formulario no es soportada por este endpoint"

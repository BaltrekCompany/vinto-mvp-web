"""Errores propios de Bobbin. Comparten el manejador HTTP de WorkOrderError (estado, código y mensaje público)."""

from app.work_orders.errors import WorkOrderError


class BobbinNotFoundError(WorkOrderError):
    http_status, code, public_message = 404, "BOBBIN_NOT_FOUND", "Bobina no encontrada"

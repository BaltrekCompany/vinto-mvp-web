"""Errores del dominio de órdenes de trabajo. Cada uno lleva su código HTTP y un mensaje público sin detalles de SQL."""


class WorkOrderError(Exception):
    http_status = 400
    code = "WORK_ORDER_ERROR"
    public_message = "Solicitud inválida"

    def __init__(self, detail: str | None = None):
        # `detail` es solo para quien llama dentro del proceso; la API responde con `public_message` salvo en los 422 de datos.
        self.detail = detail
        super().__init__(detail or self.public_message)


class WorkOrderNotFoundError(WorkOrderError):
    http_status, code, public_message = 404, "WORK_ORDER_NOT_FOUND", "Orden de trabajo no encontrada"


class MachineNotFoundError(WorkOrderError):
    http_status, code, public_message = 404, "MACHINE_NOT_FOUND", "Máquina no encontrada"


class ArticleNotFoundError(WorkOrderError):
    http_status, code, public_message = 404, "ARTICLE_NOT_FOUND", "Artículo no encontrado"


class MachineOutsideScopeError(WorkOrderError):
    http_status, code, public_message = 422, "MACHINE_OUTSIDE_SCOPE", "La máquina no está disponible para órdenes de Bobinas"


class ArticleNotAllowedForMachineError(WorkOrderError):
    http_status, code, public_message = 422, "ARTICLE_NOT_ALLOWED_FOR_MACHINE", "El artículo no está permitido para esa máquina"


class InvalidWorkOrderLineError(WorkOrderError):
    http_status, code, public_message = 422, "INVALID_LINE", "Línea inválida"


class WorkOrderNotDraftError(WorkOrderError):
    http_status, code, public_message = 409, "WORK_ORDER_NOT_DRAFT", "La orden no está en borrador; la línea base publicada no se modifica"


class WorkOrderAlreadyPublishedError(WorkOrderNotDraftError):
    code, public_message = "WORK_ORDER_ALREADY_PUBLISHED", "La línea base ya está publicada y no admite cambios"


class WorkOrderNotPublishableError(WorkOrderError):
    http_status, code, public_message = 409, "WORK_ORDER_NOT_PUBLISHABLE", "La orden no se puede publicar en su estado actual"

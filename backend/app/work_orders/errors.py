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


class WorkOrderReprogramBlockedError(WorkOrderError):
    http_status, code, public_message = 409, "WORK_ORDER_REPROGRAM_BLOCKED", "La OT no admite reprogramación ordinaria: debe estar publicada y sin asignaciones ni ejecución"


class WorkOrderHandoffPendingError(WorkOrderError):
    http_status, code, public_message = (409, "WORK_ORDER_HANDOFF_PENDING",
                                        "La linea esta reservada para un relevo supervisado")


class WorkOrderD1DisabledError(WorkOrderError):
    http_status, code, public_message = 409, "WORK_ORDER_D1_DISABLED", "La reprogramacion controlada de lineas sin iniciar no esta habilitada"


class WorkOrderD1BlockedError(WorkOrderError):
    http_status, code, public_message = 409, "WORK_ORDER_D1_BLOCKED", "La linea no admite reprogramacion D1; comprobar estado e historial"


class WorkOrderReprogramConflictError(WorkOrderError):
    http_status, code, public_message = 409, "WORK_ORDER_REPROGRAM_CONFLICT", "La programación cambió; vuelve a consultar la versión vigente"


class SupervisionRevisionConflictError(WorkOrderError):
    http_status, code, public_message = (
        409, "SUPERVISION_REVISION_CHANGED",
        "La version vigente cambió; actualiza los avisos antes de confirmar")


class WorkOrderNotDraftError(WorkOrderError):
    http_status, code, public_message = 409, "WORK_ORDER_NOT_DRAFT", "La orden no está en borrador; la línea base publicada no se modifica"


class WorkOrderDraftChangedError(WorkOrderError):
    http_status, code, public_message = 409, "WORK_ORDER_DRAFT_CHANGED", "La línea fue modificada; actualiza la OT antes de volver a editar"


class WorkOrderAlreadyPublishedError(WorkOrderNotDraftError):
    code, public_message = "WORK_ORDER_ALREADY_PUBLISHED", "La línea base ya está publicada y no admite cambios"


class WorkOrderNotPublishableError(WorkOrderError):
    http_status, code, public_message = 409, "WORK_ORDER_NOT_PUBLISHABLE", "La orden no se puede publicar en su estado actual"


class MultiMachineDisabledError(WorkOrderError):
    http_status, code, public_message = 422, "MULTI_MACHINE_DISABLED", "Las órdenes con líneas en distintas máquinas no están habilitadas"

class WorkOrderArchiveBlockedError(WorkOrderError):
    http_status, code, public_message = 409, "WORK_ORDER_ARCHIVE_BLOCKED", "La OT no se puede archivar en su estado actual o tiene asignaciones"


class WorkOrderNotArchivedError(WorkOrderError):
    http_status, code, public_message = 409, "WORK_ORDER_NOT_ARCHIVED", "La OT no está archivada"

"""Errores de la API administrativa. Cada uno lleva su código HTTP y un mensaje público sin SQL, sin identificadores internos y sin secretos."""


class AdminError(Exception):
    http_status = 400
    code = "ADMIN_ERROR"
    public_message = "Solicitud inválida"


class UserNotFound(AdminError):
    http_status, code, public_message = 404, "USER_NOT_FOUND", "Usuario no encontrado"


class SectorNotFound(AdminError):
    http_status, code, public_message = 404, "SECTOR_NOT_FOUND", "Sector no encontrado"


class SectorInactive(AdminError):
    http_status, code, public_message = 422, "SECTOR_INACTIVE", "El sector está inactivo y no admite nuevas concesiones"


class ActorNotAuthorized(AdminError):
    """El administrador perdió el permiso (desactivado o sin perfil con user.manage) entre la comprobación de la petición y la escritura: no se escribe nada."""
    http_status, code, public_message = 403, "ACTOR_NOT_AUTHORIZED", "Permiso insuficiente"


class OriginNotAllowed(AdminError):
    http_status, code, public_message = 403, "ORIGIN_NOT_ALLOWED", "Origen no autorizado"


class UnsupportedMediaType(AdminError):
    http_status, code, public_message = 415, "UNSUPPORTED_MEDIA_TYPE", "El cuerpo debe ser application/json"


class MachineNotFound(AdminError):
    http_status, code, public_message = 404, "MACHINE_NOT_FOUND", "Máquina no encontrada"


class FormNotFound(AdminError):
    http_status, code, public_message = 404, "FORM_NOT_FOUND", "Formulario no encontrado"


class PairNotOffered(AdminError):
    """El par (máquina, formulario) no se ofrece hoy: no se concede. Revocar un par así sí se permite (la concesión inerte debe poder retirarse)."""

    http_status, code = 409, "PAIR_NOT_OFFERED"
    public_message = "El formulario no se ofrece hoy para esa máquina: formulario, máquina o sector inactivos, o la versión publicada vigente no la vincula"

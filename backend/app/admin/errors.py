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


class OriginNotAllowed(AdminError):
    http_status, code, public_message = 403, "ORIGIN_NOT_ALLOWED", "Origen no autorizado"


class UnsupportedMediaType(AdminError):
    http_status, code, public_message = 415, "UNSUPPORTED_MEDIA_TYPE", "El cuerpo debe ser application/json"

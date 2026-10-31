"""Errores del motor de autorización y su traducción a respuestas PÚBLICAS seguras.

Tres clases distintas, que una ruta futura debe tratar por separado:
  - AuthorizationDenied     el usuario existe pero la operación NO está autorizada (403).
  - ResourceNotFound        el usuario, la máquina o el formulario no existen (404).
  - AuthorizationUnavailable la infraestructura de autorización no pudo decidir (tabla ausente, privilegio, bloqueo, tiempo, red): 503. JAMÁS se interpreta como acceso concedido.

La razón interna exacta de una denegación (`Decision.reason`) es para auditoría y registros del servidor: las respuestas públicas son fijas y no revelan qué condición falló, SQL, nombres de
tablas, sectores, perfiles ni identificadores.
"""


class AuthorizationError(Exception):
    """Base de los errores del motor."""


class AuthorizationDenied(AuthorizationError):
    def __init__(self, decision):
        self.decision = decision
        super().__init__("Acceso no autorizado")


class ResourceNotFound(AuthorizationError):
    def __init__(self, decision):
        self.decision = decision
        super().__init__("Recurso no encontrado")


class AuthorizationUnavailable(AuthorizationError):
    """No se pudo decidir. `cause` es un código corto y seguro (SQLSTATE o una etiqueta interna), nunca un mensaje de la base de datos."""

    def __init__(self, cause: str):
        self.cause = cause
        super().__init__("Autorización no disponible")


PUBLIC_FORBIDDEN = (403, {"detail": "Acceso no autorizado", "code": "FORBIDDEN"})
PUBLIC_NOT_FOUND = (404, {"detail": "Recurso no encontrado", "code": "NOT_FOUND"})
PUBLIC_UNAVAILABLE = (503, {"detail": "Autorización no disponible", "code": "AUTHORIZATION_UNAVAILABLE"})


def public_response(error: AuthorizationError) -> tuple:
    """(estado HTTP, cuerpo) fijos para un error del motor. Una excepción desconocida se trata como NO disponible, nunca como permitido."""
    if isinstance(error, AuthorizationDenied):
        return PUBLIC_FORBIDDEN[0], dict(PUBLIC_FORBIDDEN[1])
    if isinstance(error, ResourceNotFound):
        return PUBLIC_NOT_FOUND[0], dict(PUBLIC_NOT_FOUND[1])
    return PUBLIC_UNAVAILABLE[0], dict(PUBLIC_UNAVAILABLE[1])

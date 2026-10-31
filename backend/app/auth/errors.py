"""Errores del dominio de autenticación. Los mensajes nunca contienen contraseñas, hashes ni tokens.

Una futura API debe exponer `InvalidCredentialsError` y `AccountLockedError` con un mensaje externo
genérico para no permitir enumeración de usuarios.
"""


class AuthError(Exception):
    """Base de los errores de autenticación."""


class InvalidUsernameError(AuthError):
    """El username no cumple ^[a-z0-9._-]{1,64}$ tras normalizarlo."""


class InvalidPasswordPolicyError(AuthError):
    """La contraseña no cumple la política (12 a 256 caracteres)."""


class UserAlreadyExistsError(AuthError):
    """Ya existe una credencial con ese username (sin distinguir mayúsculas)."""


class ProfileNotFoundError(AuthError):
    """El perfil no existe o está inactivo."""


class InvalidCredentialsError(AuthError):
    """Usuario inexistente, usuario inactivo o contraseña incorrecta: indistinguibles para quien llama."""

    def __init__(self):
        super().__init__("Credenciales inválidas")


class AccountLockedError(AuthError):
    """La cuenta está bloqueada temporalmente por intentos fallidos."""

    def __init__(self, locked_until):
        self.locked_until = locked_until
        super().__init__("Cuenta bloqueada temporalmente")


class InvalidDisplayNameError(AuthError):
    """El nombre visible está vacío o es demasiado largo."""


class InvalidSessionError(AuthError):
    """Token inexistente, inválido, expirado, revocado o de un usuario inactivo (indistinguibles)."""

    def __init__(self):
        super().__init__("Sesión no válida")


class UserNotFoundError(AuthError):
    """El usuario no existe."""


class InvalidReasonError(AuthError):
    """El motivo de la operación administrativa está vacío o no es texto."""


class LastAdministratorError(AuthError):
    """La operación dejaría cero cuentas activas con un perfil que otorga user.manage."""


class SectorNotFoundError(AuthError):
    """El sector no existe."""


class MachineNotFoundError(AuthError):
    """La máquina no existe."""


class FormNotFoundError(AuthError):
    """El formulario no existe."""


class FormNotLinkedToMachineError(AuthError):
    """El formulario no tiene ninguna versión publicada vinculada a la máquina: no se concede un par que el catálogo no ofrece."""

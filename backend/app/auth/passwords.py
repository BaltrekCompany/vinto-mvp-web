"""Contraseñas con Argon2id (argon2-cffi). No hay criptografía propia ni se registra ningún secreto.

Parámetros: los valores por defecto de argon2-cffi (RFC 9106, perfil de baja memoria:
time_cost=3, memory_cost=64 MiB, parallelism=4). Cada hash incluye su sal y sus parámetros,
así que verify funciona aunque los parámetros cambien en el futuro (ver `needs_rehash`).
"""

import secrets
from functools import cache

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.auth.errors import InvalidPasswordPolicyError

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256
HASH_ALGORITHM = "argon2id"  # valor permitido por vinto_auth.credential.hash_algorithm

_hasher = PasswordHasher(type=Type.ID)


def validate_password_policy(password: str) -> None:
    """La longitud es la única regla: 12 a 256 caracteres. Sin exigir mayúsculas, números ni símbolos."""
    if not isinstance(password, str):
        raise InvalidPasswordPolicyError("La contraseña debe ser texto")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidPasswordPolicyError(f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise InvalidPasswordPolicyError(f"La contraseña no puede superar {MAX_PASSWORD_LENGTH} caracteres")


def hash_password(password: str) -> str:
    """Hash Argon2id codificado ($argon2id$...). No valida la política: usar validate_password_policy antes."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """True solo si coincide. Un hash inválido o una contraseña incorrecta devuelven False, sin excepciones."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@cache
def dummy_hash() -> str:
    """Hash válido de un secreto aleatorio que nadie conoce: permite una verificación de coste real para
    usuarios inexistentes sin revelar la diferencia de tiempo. Se calcula una vez por proceso."""
    return hash_password(secrets.token_urlsafe(32))

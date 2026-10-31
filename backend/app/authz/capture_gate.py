"""Compuerta de la autorización efectiva para operaciones de captura. Conectada a POST /api/captures (MF-13-01D.2A, `authz_central_captures_mode`) y a POST /api/bobbins
(F3, MF-13-01D.2B, `authz_bobbin_production_mode`); cada operación tiene su propia configuración y una no activa la otra. Calidad aún no la usa.

Modos (configuración exclusiva del servidor; el valor inicial de cada operación es `off`):
  off      el router no construye la compuerta: el flujo es exactamente el anterior.
  observe  evalúa SIN bloqueos y dentro de un savepoint, registra la decisión y NUNCA cambia datos ni respuesta (cualquier fallo del motor se registra y se ignora).
  enforce  exige la autorización con `authz.require(lock=True)` en la MISMA transacción que registra la captura: 403/404 si se deniega, 503 si no se puede decidir.

La máquina nunca viene del cliente: se obtiene de la asignación registrada en PostgreSQL (captura nueva) o de la propia captura persistida (reintento). Tras tomar el bloqueo de máquina y asignación se
comprueba que el contexto definitivo coincide con el autorizado; si no, falla cerrado (503, el cliente puede reintentar).

Orden de bloqueos con la compuerta (ver también capture_service): capture_id → bloqueos de autorización (usuario, perfiles, máquina+sector, concesión; FOR SHARE) → bloqueo asesor de máquina →
asignación (FOR SHARE) → dispositivo → inserciones. Los bloqueos de autorización se mantienen hasta el COMMIT/ROLLBACK de la captura.

Registros técnicos (logger `vinto.authz`): modo, operación, resultado, razón interna segura e identificador de solicitud. Nunca cookies, credenciales, identificadores de usuario ni valores del formulario.
"""

import logging

from app.auth.service import AuthenticatedUser
from app.authz.engine import authorize, require
from app.authz.errors import AuthorizationDenied, AuthorizationError, AuthorizationUnavailable, ResourceNotFound
from app.authz.policies import Operation

logger = logging.getLogger("vinto.authz")
OFF, OBSERVE, ENFORCE = "off", "observe", "enforce"
OPERATION = Operation.PRODUCTION_CAPTURE  # operación de la captura central (valor por defecto)


def gate_for(user: AuthenticatedUser, mode: str, request_id: str, operation: Operation = OPERATION):
    """None en modo `off` (comportamiento anterior); la compuerta en `observe`/`enforce`. Un modo desconocido es un error de configuración: falla cerrado."""
    if mode == OFF:
        return None
    if mode not in (OBSERVE, ENFORCE):
        raise AuthorizationUnavailable("INVALID_MODE")
    return OperationGate(user, mode, request_id, operation)


class OperationGate:
    """Compuerta de UNA operación (`operation` fija la política del motor: el cliente no la elige). El formulario lo aporta el servicio desde su constante funcional."""

    def __init__(self, user: AuthenticatedUser, mode: str, request_id: str, operation: Operation = OPERATION):
        self.user, self.mode, self.request_id, self.operation = user, mode, request_id, operation

    def _log(self, level, outcome, reason):
        logger.log(level, "authz mode=%s operation=%s outcome=%s reason=%s request_id=%s", self.mode, self.operation.value, outcome, reason, self.request_id)

    def check_existing(self, connection, capture_id, stored_form_code) -> None:
        """Reintento de una captura ya guardada: el par (máquina, formulario) sale de los datos persistidos, no del reintento. Una asignación ya terminada no importa aquí."""
        row = connection.execute("SELECT m.code FROM vinto_txn.capture c JOIN vinto_master.machine m ON m.id = c.machine_id WHERE c.id = %s", (capture_id,)).fetchone()
        if row is None:  # no debería ocurrir (acabamos de leerla bajo el bloqueo de capture_id): en enforce, falla cerrado
            self._unresolved()
            return
        self._decide(connection, row[0], stored_form_code)

    def check_new(self, connection, machine_id, machine_code, form_code):
        """Captura nueva: autoriza la máquina de la asignación (leída de PostgreSQL) y devuelve su id para confirmarla bajo el bloqueo de máquina."""
        self._decide(connection, machine_code, form_code)
        return machine_id

    def confirm_context(self, authorized_machine_id, definitive_machine_id) -> None:
        """El contexto definitivo (bajo bloqueo de máquina y asignación) debe ser la máquina que se autorizó."""
        if authorized_machine_id == definitive_machine_id:
            return
        self._log(logging.WARNING, "context_changed", "CONTEXT_CHANGED")
        if self.mode == ENFORCE:
            raise AuthorizationUnavailable("CONTEXT_CHANGED")

    def _unresolved(self):
        self._log(logging.WARNING, "unavailable", "CONTEXT_UNRESOLVED")
        if self.mode == ENFORCE:
            raise AuthorizationUnavailable("CONTEXT_UNRESOLVED")

    def _decide(self, connection, machine_code, form_code) -> None:
        if self.mode == ENFORCE:
            try:
                decision = require(connection, self.user, self.operation, machine_code, form_code, lock=True)
            except (AuthorizationDenied, ResourceNotFound) as error:
                self._log(logging.WARNING, error.decision.kind, error.decision.reason)
                raise
            except AuthorizationError as error:
                self._log(logging.ERROR, "unavailable", getattr(error, "cause", "UNKNOWN"))
                raise
            self._log(logging.INFO, "allowed", decision.reason)
            return
        try:  # observe: sin bloqueos, en un savepoint (un fallo SQL no aborta la transacción de la captura) y sin que nada pueda alterar la respuesta
            with connection.transaction():
                decision = authorize(connection, self.user, self.operation, machine_code, form_code, lock=False)
            self._log(logging.INFO if decision.allowed else logging.WARNING, "would_" + decision.kind if not decision.allowed else "allowed", decision.reason)
        except Exception as error:  # noqa: BLE001 — observar nunca debe romper la captura
            self._log(logging.ERROR, "observe_error", getattr(error, "cause", type(error).__name__))


class CentralCaptureGate(OperationGate):
    """Compuerta de POST /api/captures (PRODUCTION_CAPTURE)."""

    def __init__(self, user: AuthenticatedUser, mode: str, request_id: str):
        super().__init__(user, mode, request_id, Operation.PRODUCTION_CAPTURE)

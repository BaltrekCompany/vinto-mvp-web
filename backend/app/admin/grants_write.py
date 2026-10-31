"""Alta y baja administrativa de concesiones máquina-formulario (MF-13-01C.2).

SOLO delega en `app.auth.machine_form_grants.grant_machine_form` / `revoke_machine_form` (el único SQL de escritura de la tabla): aquí no hay INSERT ni UPDATE. Lo que añade este módulo es el
contrato HTTP y la traducción de errores de dominio a errores administrativos con código público.

- El actor es SIEMPRE el administrador autenticado (el router lo toma de la sesión); el `request_id` lo genera el servidor. El cliente no puede fijar ninguno de los dos.
- Conceder exige que el par SE OFREZCA hoy (la política de `grant_machine_form`: formulario, máquina y sector activos y versión publicada vigente vinculada). Revocar no lo exige: una
  concesión inerte debe poder retirarse.
- Conceder NO exige que el usuario esté activo ni que tenga el sector de la máquina, y no concede perfiles ni sectores: esas reglas no cambian. La respuesta lo informa en `context`.
- No activa ninguna autorización: las concesiones todavía no se consultan en capturas, órdenes, bobinas ni liberaciones.
"""

import uuid

from app.admin.errors import FormNotFound, MachineNotFound, PairNotOffered, UserNotFound
from app.admin.grants_read import pair_state
from app.auth.errors import FormNotFoundError, FormNotLinkedToMachineError, MachineNotFoundError, UserNotFoundError
from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form


def change_machine_form_grant(connection, *, operation, user_id, machine_code, form_code, actor_id) -> dict:
    """operation: "grant" | "revoke". Idempotente: `changed` es False si no había nada que cambiar (y entonces no se escribe ni se audita nada)."""
    assert operation in ("grant", "revoke")
    request_id = f"admin-machine-form-{operation}:{uuid.uuid4()}"  # generado por el servidor; el cliente no puede fijarlo
    action = grant_machine_form if operation == "grant" else revoke_machine_form
    try:
        changed = action(connection, user_id=user_id, machine_code=machine_code, form_code=form_code, actor_id=actor_id, request_id=request_id)
    except UserNotFoundError:
        raise UserNotFound() from None
    except MachineNotFoundError:
        raise MachineNotFound() from None
    except FormNotFoundError:
        raise FormNotFound() from None
    except FormNotLinkedToMachineError:
        raise PairNotOffered() from None
    state = pair_state(connection, user_id, machine_code, form_code)
    return {"user_id": user_id, "machine_code": machine_code, "form_code": form_code, "operation": operation, "changed": changed,
            "active": state["active"], "request_id": request_id if changed else None, "grant": state["grant"], "catalog": state["catalog"], "context": state["context"]}

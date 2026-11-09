"""Política MP3 RG-MP3-01: aislamiento de máquina y una captura por turno.

Este módulo se invoca dentro de submit_production_capture, DESPUÉS de tomar el
mismo advisory lock de máquina que usan las asignaciones, y ANTES del INSERT.
El mismo capture_id se reconcilia en capture_service antes de alcanzar esta política.

Ámbito de unicidad: MP3 + fecha operativa (no fecha de servidor) + turno
(shift_id, no schedule_id, para soportar revisiones del horario).
Cambios de OT, asignación, usuario o dispositivo NO abren otra captura del turno.
La historia de VINTO-P1-01 de MP3 durante el turno de transición TAMBIÉN ocupa
esa franja: no se registra dos veces la inspección con códigos diferentes.
"""

from app.capture_errors import FormNotAvailableError, ShiftCaptureAlreadyExistsError

RG_MP3_FORM_CODE = "VINTO-MP3-01"
SHARED_OLD_FORM_CODE = "VINTO-P1-01"
MP3_MACHINE_CODE = "MP3"

SHIFT_ALREADY_TAKEN_SQL = """
    SELECT 1
    FROM vinto_txn.capture c
    JOIN vinto_config.form_version v ON v.id = c.form_version_id
    JOIN vinto_config.form f ON f.id = v.form_id
    JOIN vinto_config.shift_schedule existing_schedule ON existing_schedule.id = c.shift_schedule_id
    JOIN vinto_config.shift_schedule new_schedule ON new_schedule.id = %s
    WHERE f.code = ANY(%s)
      AND c.machine_id = %s
      AND c.operating_date = %s
      AND existing_schedule.shift_id = new_schedule.shift_id
      AND c.status IN ('submitted', 'closed', 'blocked')
    LIMIT 1
"""


def allowed_for_machine(form_code: str, machine_code: str) -> bool:
    """Alcance explícito adicional al vínculo de versión publicada."""
    if form_code == RG_MP3_FORM_CODE:
        return machine_code == MP3_MACHINE_CODE
    if form_code == SHARED_OLD_FORM_CODE and machine_code == MP3_MACHINE_CODE:
        return False
    return True


def assert_form_machine(connection, form_code: str, machine_id) -> None:
    if form_code not in {RG_MP3_FORM_CODE, SHARED_OLD_FORM_CODE}:
        return
    row = connection.execute(
        "SELECT code FROM vinto_master.machine WHERE id = %s",
        (machine_id,),
    ).fetchone()
    if row is None or not allowed_for_machine(form_code, row[0]):
        raise FormNotAvailableError()


def assert_one_per_shift(connection, *, form_code: str, machine_id, operating_date, shift_schedule_id) -> None:
    """Llamar solo manteniendo el advisory lock transaccional de esa máquina."""
    if form_code != RG_MP3_FORM_CODE:
        return
    taken = connection.execute(
        SHIFT_ALREADY_TAKEN_SQL,
        (shift_schedule_id, [RG_MP3_FORM_CODE, SHARED_OLD_FORM_CODE], machine_id, operating_date),
    ).fetchone()
    if taken is not None:
        raise ShiftCaptureAlreadyExistsError()

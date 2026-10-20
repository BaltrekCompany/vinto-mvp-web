"""Controles de Calidad POR MÁQUINA (DEV-Q1, candidato): capturas de formularios de área `quality` que NO pertenecen a una Bobina ni a una asignación (p. ej. VINTO-P1-22 y VINTO-P1-26).

Reutiliza vinto_txn.capture SIN migración: `assignment_id` y `bobbin_id` son nullables; la máquina, el dispositivo, el turno y la fecha operativa son los del instante del registro. Es independiente de:
  - el servicio de Producción (`/api/captures`): no se reutiliza su endpoint ni se exige una asignación, y
  - los controles por Bobina P1-19 / P1-20 (`quality/capture_service.py`): no se modifican y sus consultas siguen filtrando `bobbin_id IS NOT NULL`, así que estos controles no aparecen en ellas.
Nunca crea bobinas, relaciones con OT / asignación ni toca quality_release: capturar un control no libera ni rechaza nada.

POLÍTICA EXPLÍCITA (`MACHINE_QUALITY_FORM_CODES`): VACÍA en la configuración real. Un formulario publicado NO se acepta por el solo hecho de existir; habilitar uno es un cambio de código revisado (hoy solo
los entornos de prueba lo hacen con patch.object). Cada captura exige además versión publicada de área `quality`, formulario activo y vínculo formulario-máquina.

`captured_at` es la HORA DE REGISTRO (reloj de PostgreSQL al crear la captura), NO la hora real del ensayo: el contrato candidato no tiene un campo de hora de muestreo y no se inventa uno. Turno y fecha operativa
se resuelven con el backend (resolve_shift) a esa hora de registro. El responsable es el usuario autenticado (`created_by`), solo informativo: no es una firma.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from app import capture_service as cs
from app.capture_errors import CaptureIdempotencyConflictError, CaptureNotFoundError, CaptureValidationError, FormNotAvailableError, UnsupportedFormDefinitionError, UnsupportedFormError
from app.quality.form_availability import available_quality_forms
from app.sectors import in_scope, scoped_sector_codes
from app.shifts import resolve_shift
from app.work_orders.errors import MachineNotFoundError, MachineOutsideScopeError

QUALITY_AREA = "quality"
REASON = "submit quality machine capture"
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200

# POLÍTICA: formularios de Calidad por máquina habilitados.
#
# CLOUD-DEP G.12-C4: habilitados P1-18/22/26/27 EXCLUSIVAMENTE para QA interno sobre MP1/MP3 (ver
# backend/seed_data/forms/VINTO-P1-{18,22,26,27}.json, ya publicados y vinculados a esas máquinas).
# Ninguno de los cuatro homologado por VINTO (contratos, rangos ni unidades aprobados); ninguno toca
# quality_release.
MACHINE_QUALITY_FORM_CODES: frozenset = frozenset({"VINTO-P1-18", "VINTO-P1-22", "VINTO-P1-26", "VINTO-P1-27"})


@dataclass(frozen=True)
class MachineCaptureView:
    id: uuid.UUID
    status: str
    revision: int
    captured_at: datetime  # hora de REGISTRO (no la hora del ensayo)
    submitted_at: datetime | None
    operating_date: date
    form_code: str
    form_version_number: int
    form_name: str
    machine_code: str
    machine_name: str
    shift_code: str
    shift_name: str
    recorded_by_id: uuid.UUID | None
    recorded_by_name: str | None
    values: dict = field(default_factory=dict)  # decimales como texto exacto


@dataclass(frozen=True)
class MachineCaptureResult:
    capture: MachineCaptureView
    created: bool
    already_submitted: bool


_VIEW_SQL = """SELECT c.id, c.status, c.revision, c.captured_at, c.submitted_at, c.operating_date, f.code, fv.version_number, fv.name, m.code, m.name, sh.code, sh.name, u.id, u.display_name
               FROM vinto_txn.capture c
               JOIN vinto_config.form_version fv ON fv.id = c.form_version_id
               JOIN vinto_config.form f ON f.id = fv.form_id
               JOIN vinto_master.machine m ON m.id = c.machine_id
               JOIN vinto_master.sector s ON s.id = m.sector_id
               JOIN vinto_config.shift_schedule sc ON sc.id = c.shift_schedule_id
               JOIN vinto_config.shift sh ON sh.id = sc.shift_id
               LEFT JOIN vinto_master."user" u ON u.id = c.created_by
               WHERE fv.area = 'quality' AND c.bobbin_id IS NULL AND c.assignment_id IS NULL AND f.code = ANY(%s) AND s.code = ANY(%s)"""


def _codes() -> list[str]:
    return sorted(MACHINE_QUALITY_FORM_CODES)


def _to_view(connection, row) -> MachineCaptureView:
    return MachineCaptureView(*row, values={k: cs._serialize(v) for k, v in cs._stored_values(connection, row[0]).items()})


def get_machine_capture(connection, capture_id, *, sectors) -> MachineCaptureView:
    capture_id = cs._uuid(capture_id, CaptureNotFoundError)
    row = connection.execute(_VIEW_SQL + " AND c.id = %s", (_codes(), list(scoped_sector_codes(sectors)), capture_id)).fetchone()
    if row is None:
        raise CaptureNotFoundError()
    return _to_view(connection, row)


def _machine(connection, machine_code, sectors):
    if not isinstance(machine_code, str) or not machine_code.strip():
        raise MachineNotFoundError("machine_code es obligatorio")
    row = connection.execute(
        """SELECT m.id, m.active, s.id, s.code FROM vinto_master.machine m JOIN vinto_master.sector s ON s.id = m.sector_id WHERE m.code = %s""", (machine_code.strip(),)).fetchone()
    if row is None:
        raise MachineNotFoundError()
    if not row[1] or not in_scope(row[3], sectors):
        raise MachineOutsideScopeError()
    return row[0], row[2]


def list_machine_captures(connection, machine_code, *, form_code=None, limit=DEFAULT_LIST_LIMIT, sectors) -> list[MachineCaptureView]:
    """Controles enviados de una máquina del alcance (más recientes primero; orden solo de presentación). `form_code` opcional; si no está habilitado por la política: 422."""
    machine_id, _ = _machine(connection, machine_code, sectors)
    codes = _codes()
    if form_code is not None:
        if form_code not in MACHINE_QUALITY_FORM_CODES:
            raise UnsupportedFormError()
        codes = [form_code]
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    rows = connection.execute(_VIEW_SQL + " AND c.machine_id = %s AND c.status IN ('submitted','closed') ORDER BY c.captured_at DESC, c.id DESC LIMIT %s",
                              (codes, list(scoped_sector_codes(sectors)), machine_id, limit)).fetchall()
    return [_to_view(connection, r) for r in rows]


def available_forms(connection, sectors) -> list[dict]:
    """Máquinas activas del alcance con los formularios de Calidad por máquina que el backend publica para ellas (política + versión publicada de área quality + vínculo). Solo lectura."""
    return available_quality_forms(connection, sectors, MACHINE_QUALITY_FORM_CODES)


def _context(connection, actor_id, request_id):
    connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
    connection.execute("SELECT set_config('vinto.request_id', %s, true)", (request_id,))
    connection.execute("SELECT set_config('vinto.reason', %s, true)", (REASON,))


def _existing_matches(connection, existing, *, actor_id, machine_id, form_code, device_key, values) -> bool:
    """¿El reintento coincide EXACTAMENTE (actor, máquina, formulario de Calidad por máquina, dispositivo y valores normalizados con la versión guardada)?"""
    capture_id, status, created_by, stored_machine, stored_bobbin, stored_assignment, form_version_id, stored_form_code, stored_area, stored_device_key = existing
    if (status not in ("submitted", "closed") or created_by != actor_id or stored_machine != machine_id or stored_bobbin is not None or stored_assignment is not None
            or stored_area != QUALITY_AREA or stored_form_code != form_code or stored_device_key != device_key):
        return False
    try:
        incoming = cs.validate_values(cs.load_fields(connection, form_version_id), values)
    except (CaptureValidationError, UnsupportedFormDefinitionError):
        return False
    return incoming == cs._stored_values(connection, capture_id)


def submit_machine_capture(connection, *, actor_id, machine_code, capture_id, form_code, device_key, values, request_id=None, sectors) -> MachineCaptureResult:
    """Crea y envía un control de Calidad de una máquina, de forma atómica e idempotente (capture.id = capture_id del cliente)."""
    capture_id = cs._uuid(capture_id, CaptureValidationError)
    device_key = str(cs._uuid(device_key, CaptureValidationError))
    if not isinstance(form_code, str) or not form_code.strip():
        raise CaptureValidationError("form_code es obligatorio")
    if form_code not in MACHINE_QUALITY_FORM_CODES:
        raise UnsupportedFormError()  # política: un formulario publicado NO se acepta por el solo hecho de existir
    request_id = request_id or f"quality-machine-capture:{uuid.uuid4()}"
    with connection.transaction():
        cs._lock(connection, f"vinto-capture-id:{capture_id}")  # misma clave que F6/F3/Calidad: un capture_id es único entre todas las capturas
        _context(connection, actor_id, request_id)
        machine_id, sector_id = _machine(connection, machine_code, sectors)
        existing = connection.execute(
            """SELECT c.id, c.status, c.created_by, c.machine_id, c.bobbin_id, c.assignment_id, c.form_version_id, f.code, fv.area, d.external_key
               FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id
               JOIN vinto_master.device d ON d.id = c.device_id WHERE c.id = %s""", (capture_id,)).fetchone()
        if existing is not None:
            if _existing_matches(connection, existing, actor_id=actor_id, machine_id=machine_id, form_code=form_code, device_key=device_key, values=values):
                return MachineCaptureResult(get_machine_capture(connection, capture_id, sectors=sectors), created=False, already_submitted=True)
            raise CaptureIdempotencyConflictError()

        now = cs._now(connection)  # reloj de PostgreSQL: hora de REGISTRO
        shift = resolve_shift(connection, now, sector_id=sector_id)  # SHIFT_NOT_CONFIGURED / SHIFT_AMBIGUOUS siguen su manejo seguro
        device_id = cs._resolve_device(connection, device_key, machine_id)
        form_version_id = cs.published_form_version(connection, form_code, machine_id, area=QUALITY_AREA)  # FormNotAvailableError si no está publicado / vinculado
        fields = cs.load_fields(connection, form_version_id)  # solo campos manuales sin grupo; lo demás -> UNSUPPORTED_FORM_DEFINITION
        clean = cs.validate_values(fields, values)  # los campos automáticos o calculados enviados no existen en la definición: 422

        connection.execute(
            """INSERT INTO vinto_txn.capture (id, form_version_id, machine_id, shift_schedule_id, device_id, assignment_id, operating_date, captured_at, status, bobbin_id)
               VALUES (%s,%s,%s,%s,%s,NULL,%s,%s,'draft',NULL)""", (capture_id, form_version_id, machine_id, shift.shift_schedule_id, device_id, shift.operating_date, now))
        cs._insert_details(connection, capture_id, form_version_id, fields, clean)
        connection.execute("UPDATE vinto_txn.capture SET status = 'submitted', submitted_at = clock_timestamp() WHERE id = %s", (capture_id,))
    return MachineCaptureResult(get_machine_capture(connection, capture_id, sectors=sectors), created=True, already_submitted=False)

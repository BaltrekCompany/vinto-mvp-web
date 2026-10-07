"""Producción de bobinas F3 (VINTO-P1-03): captura + vinto_txn.bobbin + quality_release 'pending' en UNA transacción.

Operación solo entrega hora_inicio, hora_fin, diametro, peso_kg, numero_de_cortes y observaciones. Todo lo demás sale del
backend: máquina/turno/fecha operativa/OT/línea/artículo de la asignación vigente, operador del usuario autenticado,
descripción y gramaje del maestro (article_version + article_version_spec) y el código de bobina del correlativo.

Correlativo: independiente por máquina y por gestión (01/04 -> 31/03, año de inicio derivado de la fecha operativa
CENTRAL con vinto_txn.management_start_year). Código visible = número ("1", "2", ...). Se reserva con un
INSERT .. ON CONFLICT DO UPDATE sobre vinto_txn.bobbin_sequence dentro de la misma transacción: un fallo posterior
revierte también el incremento y un reintento idempotente (mismo capture_id) no toca el contador.

Orden de locks (igual que F6): capture_id -> máquina (advisory) -> asignación (FOR SHARE) -> device_key -> fila del contador.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal

from app import capture_service as cs
from app.assignments.errors import AssignmentNotFoundError
from app.bobbins.errors import BobbinNotFoundError
from app.capture_errors import CaptureIdempotencyConflictError, CaptureNotFoundError, CaptureValidationError
from app.work_orders.service import ALLOWED_SECTOR_CODES

FORM_CODE = "VINTO-P1-03"
REASON = "register bobbin production"
NON_NEGATIVE = ("peso_kg",)  # CHECK (weight_kg >= 0) ya existe desde 0001; diametro NO tiene rango confirmado


@dataclass(frozen=True)
class BobbinView:
    id: uuid.UUID
    code: str
    capture_id: uuid.UUID
    machine_code: str
    machine_name: str
    management_start_year: int
    sequence_number: int
    start_time: time
    end_time: time
    diameter_mm: str
    weight_kg: str
    grammage_g_m2: str | None
    number_of_cuts: str
    notes: str | None
    article_code: str
    article_description: str
    quality_status: str
    created_at: datetime


@dataclass(frozen=True)
class BobbinResult:
    bobbin: BobbinView
    capture: cs.CaptureView
    created: bool
    already_submitted: bool


_BOBBIN_SQL = """SELECT b.id, b.code, b.source_capture_id, m.code, m.name, b.management_start_year, b.sequence_number, b.start_time, b.end_time,
                        b.diameter_mm, b.weight_kg, b.grammage_g_m2, b.number_of_cuts, b.notes, ar.code, av.description, q.status, b.created_at
                 FROM vinto_txn.bobbin b
                 JOIN vinto_master.machine m ON m.id = b.machine_id
                 JOIN vinto_master.article_version av ON av.id = b.article_version_id
                 JOIN vinto_master.article ar ON ar.id = av.article_id
                 JOIN vinto_txn.quality_release q ON q.bobbin_id = b.id
                 JOIN vinto_master.sector s ON s.id = m.sector_id
                 WHERE b.sequence_number IS NOT NULL AND s.code = ANY(%s)"""


def _fmt(value):
    return None if value is None else format(value, "f")


def _bobbin_view(row) -> BobbinView:
    r = list(row)
    r[9], r[10], r[11] = _fmt(r[9]), _fmt(r[10]), _fmt(r[11])
    return BobbinView(*r)


def _capture_view(connection, capture_id) -> cs.CaptureView:
    rows = connection.execute(cs._VIEW_SQL + " AND c.id = %s", (FORM_CODE, list(ALLOWED_SECTOR_CODES), capture_id)).fetchall()
    if not rows:
        raise CaptureNotFoundError()
    return cs._to_view(connection, rows[0])


def get_bobbin(connection, bobbin_id) -> BobbinView:
    bobbin_id = cs._uuid(bobbin_id, BobbinNotFoundError)
    row = connection.execute(_BOBBIN_SQL + " AND b.id = %s", (list(ALLOWED_SECTOR_CODES), bobbin_id)).fetchone()
    if row is None:
        raise BobbinNotFoundError()
    return _bobbin_view(row)


def _result(connection, capture_id, *, created) -> BobbinResult:
    row = connection.execute(_BOBBIN_SQL + " AND b.source_capture_id = %s", (list(ALLOWED_SECTOR_CODES), capture_id)).fetchone()
    if row is None:
        raise CaptureIdempotencyConflictError()
    return BobbinResult(_bobbin_view(row), _capture_view(connection, capture_id), created=created, already_submitted=not created)


def _context(connection, actor_id, request_id):
    connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
    connection.execute("SELECT set_config('vinto.request_id', %s, true)", (request_id,))
    connection.execute("SELECT set_config('vinto.reason', %s, true)", (REASON,))


def _check_manual_values(clean: dict) -> None:
    problems = []
    for key in ("hora_inicio", "hora_fin"):
        if clean[key].tzinfo is not None:
            problems.append(f"{key}: debe ser una hora HH:MM sin zona horaria")
    for key in NON_NEGATIVE:
        if clean[key] < Decimal(0):
            problems.append(f"{key}: no puede ser negativo")
    if problems:
        raise CaptureValidationError("; ".join(problems))


def _grammage(connection, article_version_id):
    """Gramaje estructurado heredado del artículo; None si el artículo no lo tiene (no bloquea F3)."""
    row = connection.execute("SELECT grammage_g_m2 FROM vinto_master.article_version_spec WHERE article_version_id = %s", (article_version_id,)).fetchone()
    return None if row is None else row[0]


def _allocate_sequence(connection, machine_id, management_year) -> int:
    return connection.execute(
        """INSERT INTO vinto_txn.bobbin_sequence (machine_id, management_start_year, last_value) VALUES (%s, %s, 1)
           ON CONFLICT (machine_id, management_start_year) DO UPDATE SET last_value = vinto_txn.bobbin_sequence.last_value + 1
           RETURNING last_value""", (machine_id, management_year)).fetchone()[0]


def _insert_bobbin(connection, *, capture_id, machine_id, article_version_id, management_year, sequence, clean, grammage) -> uuid.UUID:
    return connection.execute(
        """INSERT INTO vinto_txn.bobbin (code, source_capture_id, article_version_id, weight_kg, machine_id, management_start_year, sequence_number,
                                         start_time, end_time, diameter_mm, grammage_g_m2, number_of_cuts, notes)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (str(sequence), capture_id, article_version_id, clean["peso_kg"], machine_id, management_year, sequence, clean["hora_inicio"], clean["hora_fin"],
         clean["diametro"], grammage, clean["numero_de_cortes"], clean.get("observaciones"))).fetchone()[0]


def _insert_quality_release(connection, bobbin_id) -> None:
    connection.execute("INSERT INTO vinto_txn.quality_release (bobbin_id, status) VALUES (%s, 'pending')", (bobbin_id,))


def submit_bobbin_production(connection, *, actor_id, capture_id, assignment_id, device_key, values, request_id=None) -> BobbinResult:
    """Registra una bobina F3 de forma atómica e idempotente (capture.id = capture_id del cliente)."""
    capture_id = cs._uuid(capture_id, CaptureValidationError)
    assignment_id = cs._uuid(assignment_id, AssignmentNotFoundError)
    device_key = str(cs._uuid(device_key, CaptureValidationError))
    request_id = request_id or f"bobbin:{uuid.uuid4()}"
    with connection.transaction():
        cs._lock(connection, f"vinto-capture-id:{capture_id}")
        _context(connection, actor_id, request_id)
        existing = connection.execute(
            """SELECT c.id, c.status, c.created_by, c.assignment_id, c.form_version_id, f.code, d.external_key
               FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id
               JOIN vinto_master.device d ON d.id = c.device_id WHERE c.id = %s""", (capture_id,)).fetchone()
        if existing is not None:
            if cs._existing_matches(connection, existing, actor_id=actor_id, form_code=FORM_CODE, assignment_id=assignment_id,
                                    device_key=device_key, values=values):
                return _result(connection, capture_id, created=False)
            raise CaptureIdempotencyConflictError()

        context = cs.lock_active_assignment(connection, assignment_id)
        device_id = cs._resolve_device(connection, device_key, context.machine_id)
        form_version_id = cs.published_form_version(connection, FORM_CODE, context.machine_id)
        fields = cs.load_fields(connection, form_version_id)
        clean = cs.validate_values(fields, values)
        _check_manual_values(clean)
        grammage = _grammage(connection, context.article_version_id)
        management_year = connection.execute("SELECT vinto_txn.management_start_year(%s)", (context.operating_date,)).fetchone()[0]
        sequence = _allocate_sequence(connection, context.machine_id, management_year)

        connection.execute(
            """INSERT INTO vinto_txn.capture (id, form_version_id, machine_id, shift_schedule_id, device_id, assignment_id, operating_date, captured_at, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'draft')""",
            (capture_id, form_version_id, context.machine_id, context.shift_schedule_id, device_id, assignment_id, context.operating_date, context.now))
        cs._insert_details(connection, capture_id, form_version_id, fields, clean)
        connection.execute("UPDATE vinto_txn.capture SET status = 'submitted', submitted_at = clock_timestamp() WHERE id = %s", (capture_id,))
        bobbin_id = _insert_bobbin(connection, capture_id=capture_id, machine_id=context.machine_id, article_version_id=context.article_version_id,
                                   management_year=management_year, sequence=sequence, clean=clean, grammage=grammage)
        _insert_quality_release(connection, bobbin_id)
    return _result(connection, capture_id, created=True)

"""Captura productiva central: F6 (VINTO-P1-06), formulario manual sin grupos.

La asignación activa es la autoridad COMPLETA del contexto: máquina, turno, fecha operativa, OT, PV y producto salen de
ella; el cliente no decide nada de eso. Las definiciones de campos, tipos, obligatoriedad y opciones se leen de
vinto_config (form, form_version, field_definition, field_option); el único valor fijo aquí es el código del formulario
que habilita este endpoint.

Una captura es UNA transacción:
  lock(capture_id) -> idempotencia -> contexto de auditoría -> reloj de PostgreSQL -> asignación vigente (lock de máquina,
  la misma clave que usan activate/finish) -> dispositivo (lock por device_key) -> versión publicada del formulario ->
  validación de valores -> INSERT capture (draft) -> INSERT capture_detail tipados -> UPDATE draft->submitted.
Por 0003 la primera presentación termina en revision = 1. Un fallo en cualquier punto (incluida la validación diferida
de obligatorios al COMMIT) revierte todo, también el dispositivo creado.

Orden de locks (sin interbloqueos): capture_id -> máquina (advisory, compartido con assignments) -> asignación (FOR SHARE) ->
device_key. activate toma OT -> máquina -> asignación y finish máquina -> asignación; la captura nunca toma la OT.
"""

import hashlib
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from app.assignments.errors import AssignmentNotFoundError
from app.assignments.service import _machine_lock
from app.capture_errors import (AssignmentNotActiveError, AssignmentStaleError, CaptureIdempotencyConflictError, CaptureNotFoundError,
                                CaptureValidationError, DeviceInactiveError, DeviceMachineMismatchError, FormNotAvailableError,
                                UnsupportedFormDefinitionError, UnsupportedFormError)
from app.shifts import resolve_shift
from app.work_orders.service import ALLOWED_SECTOR_CODES

FORM_CODE = "VINTO-P1-06"  # único formulario habilitado en este checkpoint
REASON = "submit production capture"
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200
MAX_TEXT_LENGTH = 10_000  # límites técnicos, no funcionales
MAX_DECIMAL_CHARS = 40
INT_LIMIT = 9_223_372_036_854_775_807
DECIMAL_PATTERN = re.compile(r"-?[0-9]+(\.[0-9]+)?")
INTEGER_PATTERN = re.compile(r"-?[0-9]+")


@dataclass(frozen=True)
class FieldDef:
    id: uuid.UUID
    key: str
    value_type: str
    source: str
    required: bool
    group_id: object
    unit: str | None
    display_order: int
    options: tuple = ()


@dataclass(frozen=True)
class CaptureView:
    id: uuid.UUID
    status: str
    revision: int
    captured_at: datetime
    submitted_at: datetime | None
    operating_date: date
    form_code: str
    form_version_number: int
    form_name: str
    machine_code: str
    machine_name: str
    shift_code: str
    shift_name: str
    assignment_id: uuid.UUID
    work_order_id: uuid.UUID
    work_order_number: str
    line_id: uuid.UUID
    line_code: str
    pv_reference: str
    article_code: str
    article_description: str
    values: dict = field(default_factory=dict)  # clave -> valor ya serializable (decimales como texto)


@dataclass(frozen=True)
class CaptureResult:
    capture: CaptureView
    created: bool
    already_submitted: bool


# ---------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------

def _now(connection) -> datetime:
    """Instante actual del reloj de PostgreSQL: es `captured_at` y el instante con el que se comprueba la vigencia."""
    return connection.execute("SELECT clock_timestamp()").fetchone()[0]


def _lock(connection, name: str) -> None:
    key = int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:8], "big", signed=True)
    connection.execute("SELECT pg_advisory_xact_lock(%s)", (key,))


def _context(connection, actor_id, request_id):
    connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
    connection.execute("SELECT set_config('vinto.request_id', %s, true)", (request_id,))
    connection.execute("SELECT set_config('vinto.reason', %s, true)", (REASON,))


def _uuid(value, error):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise error() from None


# ---------------------------------------------------------------------------------------------------
# definition and values
# ---------------------------------------------------------------------------------------------------

def load_fields(connection, form_version_id) -> list[FieldDef]:
    """Campos de la versión. Este endpoint solo soporta campos manuales sin grupo; lo demás se rechaza en vez de aceptarse a medias."""
    rows = connection.execute(
        """SELECT f.id, f.key, f.value_type, f.source, f.required, f.field_group_id, u.code, f.display_order
           FROM vinto_config.field_definition f LEFT JOIN vinto_master.unit u ON u.id = f.unit_id
           WHERE f.form_version_id = %s ORDER BY f.display_order, f.key""", (form_version_id,)).fetchall()
    options: dict = {}
    for field_id, option_key in connection.execute(
            "SELECT field_definition_id, option_key FROM vinto_config.field_option WHERE form_version_id = %s", (form_version_id,)).fetchall():
        options.setdefault(field_id, []).append(option_key)
    fields = [FieldDef(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], tuple(options.get(r[0], ()))) for r in rows]
    unsupported = [f.key for f in fields if f.source != "manual" or f.group_id is not None]
    if unsupported:
        raise UnsupportedFormDefinitionError(f"Campos no soportados: {', '.join(unsupported)}")
    return fields


def _normalize(definition: FieldDef, raw):
    """Devuelve (valor, problema). valor None = ausente."""
    if raw is None:
        return None, None
    kind = definition.value_type
    if kind in ("text", "textarea"):
        if not isinstance(raw, str):
            return None, "debe ser texto"
        text = raw.strip()
        if not text:
            return None, None
        if len(text) > MAX_TEXT_LENGTH:
            return None, f"supera {MAX_TEXT_LENGTH} caracteres"
        if definition.options and text not in definition.options:
            return None, "valor no permitido (se espera una opción válida)"
        return text, None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None, None
    if kind == "integer":
        if isinstance(raw, bool):
            return None, "debe ser un entero"
        if isinstance(raw, int):
            value = raw
        elif isinstance(raw, str) and INTEGER_PATTERN.fullmatch(raw):
            value = int(raw)
        else:
            return None, "debe ser un entero"
        return (value, None) if abs(value) <= INT_LIMIT else (None, "fuera de rango")
    if kind == "decimal":
        if isinstance(raw, bool):
            return None, "debe ser un número decimal"
        if isinstance(raw, float):
            if not math.isfinite(raw):
                return None, "debe ser un número finito"
            text = repr(raw)
            value = Decimal(text) if "e" not in text.lower() else Decimal(format(Decimal(text), "f"))
        elif isinstance(raw, int):
            value = Decimal(raw)
        elif isinstance(raw, str) and len(raw) <= MAX_DECIMAL_CHARS and DECIMAL_PATTERN.fullmatch(raw):
            value = Decimal(raw)
        else:
            return None, "debe ser un número decimal"
        if not value.is_finite():
            return None, "debe ser un número finito"
        return (value, None) if len(str(value)) <= MAX_DECIMAL_CHARS else (None, "demasiados dígitos")
    if kind == "boolean":
        return (raw, None) if isinstance(raw, bool) else (None, "debe ser verdadero o falso")
    if kind == "date":
        try:
            return date.fromisoformat(raw), None
        except (ValueError, TypeError):
            return None, "debe ser una fecha AAAA-MM-DD"
    if kind == "time":
        try:
            return time.fromisoformat(raw), None
        except (ValueError, TypeError):
            return None, "debe ser una hora HH:MM"
    return None, "tipo no soportado"


def validate_values(fields: list[FieldDef], values) -> dict:
    """Normaliza y valida `values` contra la definición: claves desconocidas y obligatorios faltantes dan 422."""
    if not isinstance(values, dict):
        raise CaptureValidationError("values debe ser un objeto")
    by_key = {f.key: f for f in fields}
    problems = [f"{key}: campo desconocido" for key in sorted(k for k in values if k not in by_key)]
    clean = {}
    for definition in fields:
        value, problem = _normalize(definition, values.get(definition.key))
        if problem:
            problems.append(f"{definition.key}: {problem}")
        elif value is None:
            if definition.required:
                problems.append(f"{definition.key}: obligatorio")
        else:
            clean[definition.key] = value
    if problems:
        raise CaptureValidationError("; ".join(problems))
    return clean


_COLUMNS = {"text": "value_text", "textarea": "value_text", "decimal": "value_decimal", "integer": "value_integer",
            "boolean": "value_boolean", "date": "value_date", "time": "value_time"}


def _insert_details(connection, capture_id, form_version_id, fields, clean):
    for definition in fields:  # una sola columna de valor por detalle, según el tipo del campo
        if definition.key in clean:
            connection.execute(
                f"""INSERT INTO vinto_txn.capture_detail (capture_id, form_version_id, field_definition_id, value_type, {_COLUMNS[definition.value_type]})
                    VALUES (%s,%s,%s,%s,%s)""", (capture_id, form_version_id, definition.id, definition.value_type, clean[definition.key]))


def _serialize(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, time)):
        return value.isoformat()
    return value


# ---------------------------------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------------------------------

_VIEW_SQL = """SELECT c.id, c.status, c.revision, c.captured_at, c.submitted_at, c.operating_date, f.code, fv.version_number, fv.name,
                      m.code, m.name, sh.code, sh.name, a.id, wo.id, wo.number, l.id, l.line_code, l.pv_reference, ar.code, av.description
               FROM vinto_txn.capture c
               JOIN vinto_config.form_version fv ON fv.id = c.form_version_id
               JOIN vinto_config.form f ON f.id = fv.form_id
               JOIN vinto_master.machine m ON m.id = c.machine_id
               JOIN vinto_master.sector s ON s.id = m.sector_id
               JOIN vinto_config.shift_schedule sc ON sc.id = c.shift_schedule_id
               JOIN vinto_config.shift sh ON sh.id = sc.shift_id
               JOIN vinto_txn.assignment a ON a.id = c.assignment_id
               JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
               JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
               JOIN vinto_txn.work_order wo ON wo.id = v.work_order_id
               JOIN vinto_master.article_version av ON av.id = l.article_version_id
               JOIN vinto_master.article ar ON ar.id = av.article_id
               WHERE f.code = %s AND s.code = ANY(%s)"""


def _stored_values(connection, capture_id) -> dict:
    rows = connection.execute(
        """SELECT f.key, f.display_order, f.value_type, d.value_text, d.value_decimal, d.value_integer, d.value_boolean, d.value_date, d.value_time
           FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id
           WHERE d.capture_id = %s ORDER BY f.display_order, f.key""", (capture_id,)).fetchall()
    return {r[0]: next(v for v in r[3:] if v is not None) for r in rows}


def _to_view(connection, row) -> CaptureView:
    return CaptureView(*row, values={k: _serialize(v) for k, v in _stored_values(connection, row[0]).items()})


def get_capture(connection, capture_id) -> CaptureView:
    capture_id = _uuid(capture_id, CaptureNotFoundError)
    rows = connection.execute(_VIEW_SQL + " AND c.id = %s", (FORM_CODE, list(ALLOWED_SECTOR_CODES), capture_id)).fetchall()
    if not rows:
        raise CaptureNotFoundError()
    return _to_view(connection, rows[0])


def list_captures(connection, *, assignment_id=None, machine_code=None, operating_date=None, limit=DEFAULT_LIST_LIMIT) -> list[CaptureView]:
    """Capturas F6 enviadas (submitted/closed), más recientes primero. Sin borradores."""
    sql, params = _VIEW_SQL + " AND c.status IN ('submitted','closed')", [FORM_CODE, list(ALLOWED_SECTOR_CODES)]
    for clause, value in ((" AND a.id = %s", assignment_id), (" AND m.code = %s", machine_code), (" AND c.operating_date = %s", operating_date)):
        if value is not None:
            sql += clause
            params.append(value)
    rows = connection.execute(sql + " ORDER BY c.captured_at DESC, c.id DESC LIMIT %s", (*params, max(1, min(int(limit), MAX_LIST_LIMIT)))).fetchall()
    return [_to_view(connection, r) for r in rows]


# ---------------------------------------------------------------------------------------------------
# command
# ---------------------------------------------------------------------------------------------------

def _existing_matches(connection, existing, *, actor_id, form_code, assignment_id, device_key, values) -> bool:
    """¿El reintento coincide EXACTAMENTE con la captura ya guardada (actor, formulario, asignación, dispositivo y valores normalizados)?"""
    capture_id, status, created_by, stored_assignment, form_version_id, stored_form_code, stored_device_key = existing
    if (status not in ("submitted", "closed") or created_by != actor_id or stored_assignment != assignment_id
            or stored_form_code != form_code or stored_device_key != device_key):
        return False
    try:
        incoming = validate_values(load_fields(connection, form_version_id), values)
    except (CaptureValidationError, UnsupportedFormDefinitionError):
        return False
    return incoming == _stored_values(connection, capture_id)


def submit_production_capture(connection, *, actor_id, capture_id, form_code, assignment_id, device_key, values, request_id=None) -> CaptureResult:
    """Crea y envía una captura F6 de forma atómica e idempotente (capture.id = capture_id del cliente)."""
    if form_code != FORM_CODE:
        raise UnsupportedFormError(f"Solo se admite el formulario {FORM_CODE}")
    capture_id = _uuid(capture_id, CaptureValidationError)
    assignment_id = _uuid(assignment_id, AssignmentNotFoundError)
    device_key = str(_uuid(device_key, CaptureValidationError))
    request_id = request_id or f"capture:{uuid.uuid4()}"
    with connection.transaction():
        _lock(connection, f"vinto-capture-id:{capture_id}")
        _context(connection, actor_id, request_id)
        existing = connection.execute(
            """SELECT c.id, c.status, c.created_by, c.assignment_id, c.form_version_id, f.code, d.external_key
               FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id
               JOIN vinto_master.device d ON d.id = c.device_id WHERE c.id = %s""", (capture_id,)).fetchone()
        if existing is not None:
            if _existing_matches(connection, existing, actor_id=actor_id, form_code=form_code, assignment_id=assignment_id, device_key=device_key, values=values):
                return CaptureResult(get_capture(connection, capture_id), created=False, already_submitted=True)
            raise CaptureIdempotencyConflictError()

        head = connection.execute(
            """SELECT a.machine_id FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id = a.machine_id
               JOIN vinto_master.sector s ON s.id = m.sector_id WHERE a.id = %s AND s.code = ANY(%s)""", (assignment_id, list(ALLOWED_SECTOR_CODES))).fetchone()
        if head is None:
            raise AssignmentNotFoundError()
        _machine_lock(connection, head[0])  # serializa con activate/finish de la misma máquina
        now = _now(connection)  # tras obtener el lock: el instante refleja el estado que se valida
        row = connection.execute(
            """SELECT a.status, a.machine_id, a.shift_schedule_id, a.operating_date, m.active, s.id, v.kind, wo.status
               FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id = a.machine_id JOIN vinto_master.sector s ON s.id = m.sector_id
               JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
               JOIN vinto_txn.work_order wo ON wo.id = v.work_order_id WHERE a.id = %s FOR SHARE OF a""", (assignment_id,)).fetchone()
        status, machine_id, schedule_id, operating_date, machine_active, sector_id, version_kind, order_status = row
        if status != "active" or not machine_active or version_kind != "operational" or order_status == "closed":
            raise AssignmentNotActiveError()
        shift = resolve_shift(connection, now, sector_id=sector_id)  # SHIFT_NOT_CONFIGURED / SHIFT_AMBIGUOUS siguen su manejo seguro
        if (shift.shift_schedule_id, shift.operating_date) != (schedule_id, operating_date):
            raise AssignmentStaleError()

        device_id = _resolve_device(connection, device_key, machine_id)

        version = connection.execute(
            """SELECT fv.id FROM vinto_config.form f JOIN vinto_config.form_version fv ON fv.form_id = f.id
               WHERE f.code = %s AND f.active AND fv.status = 'published' AND fv.area = 'production' ORDER BY fv.version_number DESC LIMIT 1""",
            (form_code,)).fetchone()
        if version is None:
            raise FormNotAvailableError()
        form_version_id = version[0]
        allowed = connection.execute("SELECT 1 FROM vinto_config.form_version_machine WHERE form_version_id = %s AND machine_id = %s",
                                     (form_version_id, machine_id)).fetchone()
        if allowed is None:
            raise FormNotAvailableError()
        fields = load_fields(connection, form_version_id)
        clean = validate_values(fields, values)

        connection.execute(
            """INSERT INTO vinto_txn.capture (id, form_version_id, machine_id, shift_schedule_id, device_id, assignment_id, operating_date, captured_at, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'draft')""",
            (capture_id, form_version_id, machine_id, schedule_id, device_id, assignment_id, operating_date, now))
        _insert_details(connection, capture_id, form_version_id, fields, clean)
        connection.execute("UPDATE vinto_txn.capture SET status = 'submitted', submitted_at = clock_timestamp() WHERE id = %s", (capture_id,))
    return CaptureResult(get_capture(connection, capture_id), created=True, already_submitted=False)


def _resolve_device(connection, device_key: str, machine_id):
    """Dispositivo por external_key; si no existe se crea sin máquina (machine_id NULL: puede operar MP1 o MP3)."""
    _lock(connection, f"vinto-device:{device_key}")  # un solo creador por device_key, sin UniqueViolation para el llamador
    row = connection.execute("SELECT id, machine_id, active FROM vinto_master.device WHERE external_key = %s", (device_key,)).fetchone()
    if row is None:
        row = connection.execute(
            "INSERT INTO vinto_master.device (external_key, machine_id, active) VALUES (%s, NULL, true) ON CONFLICT (external_key) DO NOTHING RETURNING id, machine_id, active",
            (device_key,)).fetchone()
        if row is None:  # defensa: otro proceso lo creó fuera del lock
            row = connection.execute("SELECT id, machine_id, active FROM vinto_master.device WHERE external_key = %s", (device_key,)).fetchone()
    device_id, bound_machine, active = row
    if not active:
        raise DeviceInactiveError()
    if bound_machine is not None and bound_machine != machine_id:
        raise DeviceMachineMismatchError()
    return device_id

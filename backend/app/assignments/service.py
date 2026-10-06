"""Copia operativa y asignaciones de Bobinas.

Flujo: Jefatura publica la baseline (v1) -> Supervisión activa una línea -> el backend garantiza una versión
`operational` publicada (copia COMPLETA de la baseline) -> la asignación apunta a la línea de esa versión operativa,
con turno y fecha operativa resueltos por el backend en el instante actual de PostgreSQL.

Garantías:
- La baseline NUNCA se modifica; las asignaciones nunca apuntan a una línea baseline.
- La primera activación de una OT crea la versión operativa (siguiente version_number): INSERT con published_at NULL,
  copia de todas las líneas y solo entonces published_at. Las siguientes activaciones reutilizan la operativa publicada
  de mayor version_number; no se crea una versión por turno ni por asignación.
- Una sola asignación activa por máquina (índice parcial de 0001 + lock transaccional por máquina). Orden de locks
  (evita interbloqueos): work_order (FOR UPDATE) -> máquina (advisory) -> asignación (FOR UPDATE). `finish` toma
  máquina -> asignación. Una asignación `finished` nunca se reactiva: se crea una nueva.
- Turno y fecha operativa vienen de `resolve_shift` con `clock_timestamp()` de PostgreSQL; el cliente no los envía.
- Auditoría: cada paso fija un `vinto.reason` propio; el actor y un `request_id` del servidor van en todas las filas.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from app.assignments.errors import (AssignmentNotFoundError, BaselineLineNotFoundError, InvalidAssignmentFilterError,
                                    OperationalVersionError, WorkOrderNotActivatableError)
from app.shifts import ResolvedShift, ShiftResolutionError, resolve_shift
from app.work_orders.errors import MachineNotFoundError, MachineOutsideScopeError, WorkOrderNotFoundError
from app.work_orders.service import ALLOWED_SECTOR_CODES

ASSIGNMENT_STATUSES = ("active", "finished")
DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 500


@dataclass(frozen=True)
class AssignmentLineView:
    id: uuid.UUID
    line_code: str
    pv_reference: str
    article_code: str
    article_description: str
    quantity: object
    unit: str
    due_date: date


@dataclass(frozen=True)
class AssignmentView:
    id: uuid.UUID
    status: str
    operating_date: date
    created_at: datetime
    finished_at: datetime | None
    machine_code: str
    machine_name: str
    shift_code: str
    shift_name: str
    work_order_id: uuid.UUID
    work_order_number: str
    operational_version_number: int
    line: AssignmentLineView
    assigned_by_id: uuid.UUID
    assigned_by_name: str


@dataclass(frozen=True)
class ActivationResult:
    assignment: AssignmentView
    created: bool
    already_active: bool
    finished_assignment_id: uuid.UUID | None


@dataclass(frozen=True)
class ActiveAssignment:
    assignment: AssignmentView | None
    current_shift_code: str | None
    current_shift_name: str | None
    current_operating_date: date | None
    stale: bool | None  # None cuando no se puede resolver el turno actual


# ---------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------

def _now(connection) -> datetime:
    """Instante actual según el reloj de PostgreSQL (datetime aware). Es la única fuente de 'ahora'."""
    return connection.execute("SELECT clock_timestamp()").fetchone()[0]


def _context(connection, actor_id, request_id, reason):
    connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
    connection.execute("SELECT set_config('vinto.request_id', %s, true)", (request_id,))
    connection.execute("SELECT set_config('vinto.reason', %s, true)", (reason,))


def _reason(connection, reason):
    connection.execute("SELECT set_config('vinto.reason', %s, true)", (reason,))


def _machine_lock(connection, machine_id):
    key = int.from_bytes(hashlib.sha256(f"vinto-assignment-machine:{machine_id}".encode()).digest()[:8], "big", signed=True)
    connection.execute("SELECT pg_advisory_xact_lock(%s)", (key,))


def _uuid(value, error):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise error() from None


def _machine_info(connection, machine_code):
    if not isinstance(machine_code, str) or not machine_code.strip():
        raise MachineNotFoundError("machine_code es obligatorio")
    row = connection.execute(
        """SELECT m.id, m.name, m.active, s.id, s.code FROM vinto_master.machine m
           JOIN vinto_master.sector s ON s.id = m.sector_id WHERE m.code = %s""", (machine_code.strip(),)).fetchone()
    if row is None:
        raise MachineNotFoundError()
    if not row[2] or row[4] not in ALLOWED_SECTOR_CODES:
        raise MachineOutsideScopeError()
    return row[0], row[1], row[3]


_VIEW_SQL = """SELECT a.id, a.status, a.operating_date, a.created_at, a.finished_at, m.code, m.name, sh.code, sh.name,
                      wo.id, wo.number, v.version_number,
                      l.id, l.line_code, l.pv_reference, ar.code, av.description, l.quantity, u.code, l.due_date,
                      usr.id, usr.display_name
               FROM vinto_txn.assignment a
               JOIN vinto_master.machine m ON m.id = a.machine_id
               JOIN vinto_master.sector s ON s.id = m.sector_id
               JOIN vinto_config.shift_schedule sc ON sc.id = a.shift_schedule_id
               JOIN vinto_config.shift sh ON sh.id = sc.shift_id
               JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
               JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
               JOIN vinto_txn.work_order wo ON wo.id = v.work_order_id
               JOIN vinto_master.article_version av ON av.id = l.article_version_id
               JOIN vinto_master.article ar ON ar.id = av.article_id
               JOIN vinto_master.unit u ON u.id = l.unit_id
               JOIN vinto_master."user" usr ON usr.id = a.assigned_by
               WHERE s.code = ANY(%s)"""


def _to_view(row) -> AssignmentView:
    (a_id, status, operating_date, created_at, finished_at, m_code, m_name, sh_code, sh_name, wo_id, wo_number, version_number,
     l_id, line_code, pv, article_code, description, quantity, unit, due_date, user_id, user_name) = row
    return AssignmentView(a_id, status, operating_date, created_at, finished_at, m_code, m_name, sh_code, sh_name, wo_id, wo_number,
                          version_number, AssignmentLineView(l_id, line_code, pv, article_code, description, quantity, unit, due_date), user_id, user_name)


def get_assignment(connection, assignment_id) -> AssignmentView:
    assignment_id = _uuid(assignment_id, AssignmentNotFoundError)
    rows = connection.execute(_VIEW_SQL + " AND a.id = %s", (list(ALLOWED_SECTOR_CODES), assignment_id)).fetchall()
    if not rows:
        raise AssignmentNotFoundError()
    return _to_view(rows[0])


# ---------------------------------------------------------------------------------------------------
# operational version
# ---------------------------------------------------------------------------------------------------

def _ensure_operational(connection, work_order_id, baseline_version_id):
    """Devuelve el id de la versión operativa publicada de mayor version_number; la crea si no existe.

    Se llama con la fila de la OT bloqueada (FOR UPDATE): otro proceso que active la misma OT espera, vuelve a
    comprobar y encuentra la operativa ya publicada, así que nunca se crean v2 y v3 por accidente.
    """
    row = connection.execute(
        """SELECT id FROM vinto_txn.work_order_version
           WHERE work_order_id = %s AND kind = 'operational' AND published_at IS NOT NULL
           ORDER BY version_number DESC LIMIT 1""", (work_order_id,)).fetchone()
    if row is not None:
        return row[0]
    _reason(connection, "create operational work order version")
    version_id = connection.execute(
        """INSERT INTO vinto_txn.work_order_version (work_order_id, version_number, kind)
           SELECT %s, coalesce(max(version_number), 0) + 1, 'operational' FROM vinto_txn.work_order_version WHERE work_order_id = %s
           RETURNING id""", (work_order_id, work_order_id)).fetchone()[0]
    copied = connection.execute(
        """INSERT INTO vinto_txn.work_order_line (work_order_version_id, line_code, pv_reference, article_version_id, unit_id, quantity, due_date)
           SELECT %s, line_code, pv_reference, article_version_id, unit_id, quantity, due_date
           FROM vinto_txn.work_order_line WHERE work_order_version_id = %s ORDER BY length(line_code), line_code""",
        (version_id, baseline_version_id)).rowcount
    if copied == 0:
        raise OperationalVersionError("La baseline no tiene líneas que copiar")
    # Publicar DESPUÉS de copiar: una vez publicada, los triggers de 0001 la hacen inmutable.
    connection.execute("UPDATE vinto_txn.work_order_version SET published_at = clock_timestamp() WHERE id = %s", (version_id,))
    return version_id


# ---------------------------------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------------------------------

def activate(connection, *, actor_id, work_order_id, baseline_line_id, request_id=None) -> ActivationResult:
    """Activa una línea (identificada por su línea BASE) en la máquina de la OT. Idempotente en el mismo turno y fecha."""
    work_order_id = _uuid(work_order_id, WorkOrderNotFoundError)
    baseline_line_id = _uuid(baseline_line_id, BaselineLineNotFoundError)
    request_id = request_id or f"assignment:{uuid.uuid4()}"
    with connection.transaction():
        _context(connection, actor_id, request_id, "create operational work order version")
        order = connection.execute(
            """SELECT wo.status, wo.machine_id, m.active, s.id, s.code FROM vinto_txn.work_order wo
               JOIN vinto_master.machine m ON m.id = wo.machine_id JOIN vinto_master.sector s ON s.id = m.sector_id
               WHERE wo.id = %s FOR UPDATE OF wo""", (work_order_id,)).fetchone()
        if order is None or order[4] not in ALLOWED_SECTOR_CODES:
            raise WorkOrderNotFoundError()
        status, machine_id, machine_active, sector_id, _ = order
        if status not in ("published", "in_progress"):
            raise WorkOrderNotActivatableError(f"La orden está en estado {status}")
        if not machine_active:
            raise WorkOrderNotActivatableError("La máquina de la orden está inactiva")
        base = connection.execute(
            """SELECT l.line_code, v.id FROM vinto_txn.work_order_line l JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
               WHERE l.id = %s AND v.work_order_id = %s AND v.kind = 'baseline' AND v.version_number = 1 AND v.published_at IS NOT NULL""",
            (baseline_line_id, work_order_id)).fetchone()
        if base is None:
            raise BaselineLineNotFoundError()
        line_code, baseline_version_id = base
        shift: ResolvedShift = resolve_shift(connection, _now(connection), sector_id=sector_id)  # antes de escribir: sin turno no hay nada que revertir
        operational_version_id = _ensure_operational(connection, work_order_id, baseline_version_id)
        operational_line = connection.execute(
            "SELECT id FROM vinto_txn.work_order_line WHERE work_order_version_id = %s AND line_code = %s", (operational_version_id, line_code)).fetchone()
        if operational_line is None:
            raise OperationalVersionError(f"La versión operativa no contiene la línea {line_code}")
        operational_line_id = operational_line[0]
        _machine_lock(connection, machine_id)
        current = connection.execute(
            """SELECT id, work_order_line_id, shift_schedule_id, operating_date FROM vinto_txn.assignment
               WHERE machine_id = %s AND status = 'active' FOR UPDATE""", (machine_id,)).fetchone()
        if current and (current[1], current[2], current[3]) == (operational_line_id, shift.shift_schedule_id, shift.operating_date):
            existing = current[0]
            return ActivationResult(get_assignment(connection, existing), created=False, already_active=True, finished_assignment_id=None)
        finished_id = None
        if current:
            _reason(connection, "finish previous assignment")
            connection.execute("UPDATE vinto_txn.assignment SET status = 'finished', finished_at = clock_timestamp() WHERE id = %s", (current[0],))
            finished_id = current[0]
        _reason(connection, "activate assignment")
        new_id = connection.execute(
            """INSERT INTO vinto_txn.assignment (work_order_line_id, machine_id, shift_schedule_id, operating_date, assigned_by)
               VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (operational_line_id, machine_id, shift.shift_schedule_id, shift.operating_date, actor_id)).fetchone()[0]
        if status == "published":
            connection.execute("UPDATE vinto_txn.work_order SET status = 'in_progress' WHERE id = %s", (work_order_id,))
        result_id = new_id
    return ActivationResult(get_assignment(connection, result_id), created=True, already_active=False, finished_assignment_id=finished_id)


def finish(connection, *, actor_id, assignment_id, request_id=None) -> AssignmentView:
    """Finaliza una asignación activa. Si ya está finalizada no escribe nada (idempotente)."""
    assignment_id = _uuid(assignment_id, AssignmentNotFoundError)
    request_id = request_id or f"assignment:{uuid.uuid4()}"
    with connection.transaction():
        _context(connection, actor_id, request_id, "finish assignment")
        row = connection.execute(
            """SELECT a.machine_id FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id = a.machine_id
               JOIN vinto_master.sector s ON s.id = m.sector_id WHERE a.id = %s AND s.code = ANY(%s)""",
            (assignment_id, list(ALLOWED_SECTOR_CODES))).fetchone()
        if row is None:
            raise AssignmentNotFoundError()
        _machine_lock(connection, row[0])  # mismo orden que activate: máquina -> asignación
        state = connection.execute("SELECT status FROM vinto_txn.assignment WHERE id = %s FOR UPDATE", (assignment_id,)).fetchone()
        if state is None:
            raise AssignmentNotFoundError()
        if state[0] == "active":
            connection.execute("UPDATE vinto_txn.assignment SET status = 'finished', finished_at = clock_timestamp() WHERE id = %s", (assignment_id,))
    return get_assignment(connection, assignment_id)


# ---------------------------------------------------------------------------------------------------
# queries
# ---------------------------------------------------------------------------------------------------

def list_assignments(connection, *, machine_code=None, status=None, operating_date=None, work_order_id=None, limit=DEFAULT_LIST_LIMIT) -> list[AssignmentView]:
    if status is not None and status not in ASSIGNMENT_STATUSES:
        raise InvalidAssignmentFilterError(f"status debe ser uno de {', '.join(ASSIGNMENT_STATUSES)}")
    sql, params = _VIEW_SQL, [list(ALLOWED_SECTOR_CODES)]
    for clause, value in ((" AND m.code = %s", machine_code), (" AND a.status = %s", status), (" AND a.operating_date = %s", operating_date),
                          (" AND wo.id = %s", None if work_order_id is None else _uuid(work_order_id, WorkOrderNotFoundError))):
        if value is not None:
            sql += clause
            params.append(value)
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    rows = connection.execute(sql + " ORDER BY a.created_at DESC, a.id DESC LIMIT %s", (*params, limit)).fetchall()
    return [_to_view(r) for r in rows]


def get_active(connection, *, machine_code) -> ActiveAssignment:
    """¿Qué OT/línea/producto tengo activo en esta máquina ahora? Incluye el turno actual y si la asignación quedó vencida."""
    machine_id, _, sector_id = _machine_info(connection, machine_code)
    rows = connection.execute(_VIEW_SQL + " AND m.code = %s AND a.status = 'active' LIMIT 1", (list(ALLOWED_SECTOR_CODES), machine_code.strip())).fetchall()
    assignment = _to_view(rows[0]) if rows else None
    try:
        shift = resolve_shift(connection, _now(connection), sector_id=sector_id)
    except ShiftResolutionError:
        return ActiveAssignment(assignment, None, None, None, None)
    stale = None
    if assignment is not None:
        current = connection.execute("SELECT shift_schedule_id, operating_date FROM vinto_txn.assignment WHERE id = %s", (assignment.id,)).fetchone()
        stale = (current[0], current[1]) != (shift.shift_schedule_id, shift.operating_date)
    return ActiveAssignment(assignment, shift.shift_code, shift.shift_name, shift.operating_date, stale)

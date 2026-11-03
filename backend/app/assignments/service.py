"""Copia operativa y asignaciones de Bobinas.

Flujo: Jefatura publica la baseline (v1) -> Supervisión activa una línea -> el backend garantiza una versión
`operational` publicada (copia COMPLETA de la baseline) -> la asignación apunta a la línea de esa versión operativa,
con turno y fecha operativa resueltos por el backend en el instante actual de PostgreSQL.

Garantías:
- La baseline NUNCA se modifica; las asignaciones nunca apuntan a una línea baseline.
- La primera activación de una OT crea la versión operativa (siguiente version_number): INSERT con published_at NULL,
  copia de todas las líneas y solo entonces published_at. Las siguientes activaciones reutilizan la operativa publicada
  de mayor version_number; no se crea una versión por turno ni por asignación.
- La máquina de la asignación es la de la LÍNEA baseline (0010), no la de la cabecera de la OT.
- Compuerta WORK_ORDERS_MULTI_MACHINE_ENABLED (apagada por defecto):
  * apagada = semántica histórica: una sola asignación activa por máquina; activar otra línea (o de otra OT) reemplaza la
    anterior. Si una máquina ya tiene VARIAS asignaciones activas (compuerta apagada después de usarla) no se finaliza nada
    por adivinación: 409 MULTIPLE_ACTIVE_ASSIGNMENTS hasta que se finalicen explícitamente con `finish`.
  * encendida = varias líneas de la MISMA OT activas a la vez en una máquina; otra OT en esa máquina -> 409
    MACHINE_ACTIVE_WITH_OTHER_WORK_ORDER (nunca se finaliza la ajena). La BD lo garantiza (0011: índice único por línea activa
    y trigger serializado con el mismo lock de máquina).
- Asignaciones vencidas (turno o fecha operativa distintos de los actuales): la siguiente activación en esa máquina las
  finaliza (finished_at, mismo registro, mismo contexto histórico para sus capturas) y no cuentan para el conflicto entre OT.
- Orden de locks (evita interbloqueos): work_order (FOR UPDATE) -> máquinas (advisory, ordenadas por id) -> asignaciones
  (FOR UPDATE). `finish` toma máquina -> asignación; las capturas, máquina -> asignación. `_load_target` y `_activate_target`
  están separados para que la activación masiva (PR4) valide y active varias líneas en UNA transacción con ese orden.
  Una asignación `finished` nunca se reactiva: se crea una nueva.
- Turno y fecha operativa vienen de `resolve_shift` con `clock_timestamp()` de PostgreSQL; el cliente no los envía.
- Auditoría: cada paso fija un `vinto.reason` propio; el actor y un `request_id` del servidor van en todas las filas.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from app.assignments.errors import (AssignmentNotFoundError, BaselineLineNotFoundError, InvalidAssignmentFilterError,
                                    MachineBusyWithOtherWorkOrderError, MultipleActiveAssignmentsError, OperationalVersionError,
                                    WorkOrderNotActivatableError)
from app.config import settings
from app.shifts import ResolvedShift, ShiftResolutionError, resolve_shift
from app.work_orders.errors import (MachineNotFoundError, MachineOutsideScopeError, MultiMachineDisabledError,
                                    WorkOrderNotFoundError)
from app.sectors import in_scope, scoped_sector_codes

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
    finished_assignment_id: uuid.UUID | None  # solo cuando se finalizó exactamente una; la lista completa va en finished_assignment_ids
    finished_assignment_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class ActiveItem:
    assignment: AssignmentView
    stale: bool | None  # None cuando no se puede resolver el turno actual


@dataclass(frozen=True)
class ActiveAssignment:
    assignment: AssignmentView | None
    current_shift_code: str | None
    current_shift_name: str | None
    current_operating_date: date | None
    stale: bool | None  # None cuando no se puede resolver el turno actual


@dataclass(frozen=True)
class ActiveLines:
    current_shift_code: str | None
    current_shift_name: str | None
    current_operating_date: date | None
    items: tuple[ActiveItem, ...]  # TODAS las activas de la máquina, antiguas primero


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


def _multi_machine_enabled() -> bool:
    return settings.work_orders_multi_machine_enabled is True  # solo configuración del servidor; el cliente no puede cambiarla


def _machine_lock(connection, machine_id):
    key = int.from_bytes(hashlib.sha256(f"vinto-assignment-machine:{machine_id}".encode()).digest()[:8], "big", signed=True)
    connection.execute("SELECT pg_advisory_xact_lock(%s)", (key,))


def _uuid(value, error):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise error() from None


def _machine_info(connection, machine_code, sectors):
    if not isinstance(machine_code, str) or not machine_code.strip():
        raise MachineNotFoundError("machine_code es obligatorio")
    row = connection.execute(
        """SELECT m.id, m.name, m.active, s.id, s.code FROM vinto_master.machine m
           JOIN vinto_master.sector s ON s.id = m.sector_id WHERE m.code = %s""", (machine_code.strip(),)).fetchone()
    if row is None:
        raise MachineNotFoundError()
    if not row[2] or not in_scope(row[4], sectors):
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


def get_assignment(connection, assignment_id, *, sectors) -> AssignmentView:
    assignment_id = _uuid(assignment_id, AssignmentNotFoundError)
    rows = connection.execute(_VIEW_SQL + " AND a.id = %s", (list(scoped_sector_codes(sectors)), assignment_id)).fetchall()
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

@dataclass(frozen=True)
class _Target:
    """Línea baseline a activar, ya validada. La máquina es la de la LÍNEA."""
    line_code: str
    baseline_version_id: uuid.UUID
    machine_id: uuid.UUID
    sector_id: uuid.UUID


def _lock_machines(connection, machine_ids):
    """Locks de máquina en orden determinista (por id): dos activaciones multi-máquina nunca se esperan en ciclo."""
    for machine_id in sorted(set(machine_ids), key=str):
        _machine_lock(connection, machine_id)


def _load_target(connection, *, work_order_id, baseline_line_id, sectors) -> tuple[str, _Target]:
    """Bloquea la OT (FOR UPDATE) y valida todo lo que no depende del turno. Devuelve (estado de la OT, destino).

    Visibilidad: la OT es visible si la máquina de su cabecera o de alguna línea baseline está en el alcance del actor; si no, 404 como
    si no existiera. La línea cuya máquina está fuera del alcance es indistinguible de una inexistente (BASELINE_LINE_NOT_FOUND).
    """
    order = connection.execute("SELECT status, machine_id FROM vinto_txn.work_order WHERE id = %s FOR UPDATE", (work_order_id,)).fetchone()
    codes = list(scoped_sector_codes(sectors))
    if order is None or not connection.execute(
            """SELECT EXISTS (SELECT 1 FROM vinto_master.machine m JOIN vinto_master.sector s ON s.id = m.sector_id WHERE m.id = %s AND s.code = ANY(%s))
                   OR EXISTS (SELECT 1 FROM vinto_txn.work_order_line l JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
                              JOIN vinto_master.machine m ON m.id = l.machine_id JOIN vinto_master.sector s ON s.id = m.sector_id
                              WHERE v.work_order_id = %s AND v.kind = 'baseline' AND s.code = ANY(%s))""",
            (order[1], codes, work_order_id, codes)).fetchone()[0]:
        raise WorkOrderNotFoundError()
    status, header_machine_id = order
    if status not in ("published", "in_progress"):
        raise WorkOrderNotActivatableError(f"La orden está en estado {status}")
    base = connection.execute(
        """SELECT l.line_code, v.id, l.machine_id, m.active, s.id, s.code FROM vinto_txn.work_order_line l
           JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
           JOIN vinto_master.machine m ON m.id = l.machine_id JOIN vinto_master.sector s ON s.id = m.sector_id
           WHERE l.id = %s AND v.work_order_id = %s AND v.kind = 'baseline' AND v.version_number = 1 AND v.published_at IS NOT NULL""",
        (baseline_line_id, work_order_id)).fetchone()
    if base is None or base[5] not in codes:
        raise BaselineLineNotFoundError()
    line_code, baseline_version_id, machine_id, machine_active, sector_id, _ = base
    if machine_id != header_machine_id and not _multi_machine_enabled():
        raise MultiMachineDisabledError()
    if not machine_active:
        raise WorkOrderNotActivatableError("La máquina de la línea está inactiva")
    return status, _Target(line_code, baseline_version_id, machine_id, sector_id)


def _activate_target(connection, *, actor_id, work_order_id, order_status, target: _Target, shift: ResolvedShift, sectors) -> ActivationResult:
    """Activa un destino ya validado. Exige la OT bloqueada; toma el lock de la máquina (re-entrante si el llamador ya lo tiene)."""
    multi = _multi_machine_enabled()
    _lock_machines(connection, [target.machine_id])
    operational_version_id = _ensure_operational(connection, work_order_id, target.baseline_version_id)
    operational_line = connection.execute(
        "SELECT id, machine_id FROM vinto_txn.work_order_line WHERE work_order_version_id = %s AND line_code = %s", (operational_version_id, target.line_code)).fetchone()
    if operational_line is None:
        raise OperationalVersionError(f"La versión operativa no contiene la línea {target.line_code}")
    if operational_line[1] != target.machine_id:
        raise OperationalVersionError(f"La línea operativa {target.line_code} no está en la misma máquina que su baseline")
    operational_line_id = operational_line[0]
    actives = connection.execute(
        """SELECT a.id, a.work_order_line_id, a.shift_schedule_id, a.operating_date, v.work_order_id
           FROM vinto_txn.assignment a JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
           JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
           WHERE a.machine_id = %s AND a.status = 'active' ORDER BY a.created_at, a.id FOR UPDATE OF a""", (target.machine_id,)).fetchall()
    context = (shift.shift_schedule_id, shift.operating_date)
    current = [row for row in actives if (row[2], row[3]) == context]
    stale = [row for row in actives if (row[2], row[3]) != context]
    for row in current:
        if row[1] == operational_line_id:  # mismo contexto: idempotente, sin escribir (ni siquiera las vencidas)
            return ActivationResult(get_assignment(connection, row[0], sectors=sectors), created=False, already_active=True, finished_assignment_id=None)
    replaced = []
    if multi:
        if any(row[4] != work_order_id for row in current):
            raise MachineBusyWithOtherWorkOrderError()
    elif len(current) > 1:
        raise MultipleActiveAssignmentsError()  # nada se ha escrito todavía; tampoco se finaliza ninguna por adivinación
    else:
        replaced = current  # semántica histórica: la anterior se sustituye
    finished = [row[0] for row in (*stale, *replaced)]
    if finished:
        _reason(connection, "finish previous assignment")
        for assignment_id in finished:
            connection.execute("UPDATE vinto_txn.assignment SET status = 'finished', finished_at = clock_timestamp() WHERE id = %s", (assignment_id,))
    _reason(connection, "activate assignment")
    new_id = connection.execute(
        """INSERT INTO vinto_txn.assignment (work_order_line_id, machine_id, shift_schedule_id, operating_date, assigned_by)
           VALUES (%s,%s,%s,%s,%s) RETURNING id""",
        (operational_line_id, target.machine_id, shift.shift_schedule_id, shift.operating_date, actor_id)).fetchone()[0]
    if order_status == "published":
        connection.execute("UPDATE vinto_txn.work_order SET status = 'in_progress' WHERE id = %s", (work_order_id,))
    return ActivationResult(get_assignment(connection, new_id, sectors=sectors), created=True, already_active=False,
                            finished_assignment_id=finished[0] if len(finished) == 1 else None, finished_assignment_ids=tuple(finished))


def activate(connection, *, actor_id, work_order_id, baseline_line_id, request_id=None, sectors) -> ActivationResult:
    """Activa una línea (identificada por su línea BASE) en la máquina de ESA línea. Idempotente en el mismo turno y fecha."""
    work_order_id = _uuid(work_order_id, WorkOrderNotFoundError)
    baseline_line_id = _uuid(baseline_line_id, BaselineLineNotFoundError)
    request_id = request_id or f"assignment:{uuid.uuid4()}"
    with connection.transaction():
        _context(connection, actor_id, request_id, "create operational work order version")
        order_status, target = _load_target(connection, work_order_id=work_order_id, baseline_line_id=baseline_line_id, sectors=sectors)
        shift: ResolvedShift = resolve_shift(connection, _now(connection), sector_id=target.sector_id)  # antes de escribir: sin turno no hay nada que revertir
        return _activate_target(connection, actor_id=actor_id, work_order_id=work_order_id, order_status=order_status, target=target, shift=shift, sectors=sectors)


def finish(connection, *, actor_id, assignment_id, request_id=None, sectors) -> AssignmentView:
    """Finaliza una asignación activa. Si ya está finalizada no escribe nada (idempotente)."""
    assignment_id = _uuid(assignment_id, AssignmentNotFoundError)
    request_id = request_id or f"assignment:{uuid.uuid4()}"
    with connection.transaction():
        _context(connection, actor_id, request_id, "finish assignment")
        row = connection.execute(
            """SELECT a.machine_id FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id = a.machine_id
               JOIN vinto_master.sector s ON s.id = m.sector_id WHERE a.id = %s AND s.code = ANY(%s)""",
            (assignment_id, list(scoped_sector_codes(sectors)))).fetchone()
        if row is None:
            raise AssignmentNotFoundError()
        _machine_lock(connection, row[0])  # mismo orden que activate: máquina -> asignación
        state = connection.execute("SELECT status FROM vinto_txn.assignment WHERE id = %s FOR UPDATE", (assignment_id,)).fetchone()
        if state is None:
            raise AssignmentNotFoundError()
        if state[0] == "active":
            connection.execute("UPDATE vinto_txn.assignment SET status = 'finished', finished_at = clock_timestamp() WHERE id = %s", (assignment_id,))
    return get_assignment(connection, assignment_id, sectors=sectors)


# ---------------------------------------------------------------------------------------------------
# queries
# ---------------------------------------------------------------------------------------------------

def list_assignments(connection, *, machine_code=None, status=None, operating_date=None, work_order_id=None, limit=DEFAULT_LIST_LIMIT, sectors) -> list[AssignmentView]:
    if status is not None and status not in ASSIGNMENT_STATUSES:
        raise InvalidAssignmentFilterError(f"status debe ser uno de {', '.join(ASSIGNMENT_STATUSES)}")
    sql, params = _VIEW_SQL, [list(scoped_sector_codes(sectors))]
    for clause, value in ((" AND m.code = %s", machine_code), (" AND a.status = %s", status), (" AND a.operating_date = %s", operating_date),
                          (" AND wo.id = %s", None if work_order_id is None else _uuid(work_order_id, WorkOrderNotFoundError))):
        if value is not None:
            sql += clause
            params.append(value)
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    rows = connection.execute(sql + " ORDER BY a.created_at DESC, a.id DESC LIMIT %s", (*params, limit)).fetchall()
    return [_to_view(r) for r in rows]


def _active_items(connection, machine_code, sectors):
    """(items, turno actual o None) con TODAS las asignaciones activas de la máquina, antiguas primero."""
    machine_id, _, sector_id = _machine_info(connection, machine_code, sectors)
    rows = connection.execute(_VIEW_SQL + " AND m.code = %s AND a.status = 'active' ORDER BY a.created_at, a.id", (list(scoped_sector_codes(sectors)), machine_code.strip())).fetchall()
    views = [_to_view(row) for row in rows]
    try:
        shift = resolve_shift(connection, _now(connection), sector_id=sector_id)
    except ShiftResolutionError:
        return tuple(ActiveItem(v, None) for v in views), None
    contexts = {row[0]: (row[1], row[2]) for row in connection.execute(
        "SELECT id, shift_schedule_id, operating_date FROM vinto_txn.assignment WHERE id = ANY(%s)", ([v.id for v in views],)).fetchall()}
    return tuple(ActiveItem(v, contexts[v.id] != (shift.shift_schedule_id, shift.operating_date)) for v in views), shift


def get_active(connection, *, machine_code, sectors) -> ActiveAssignment:
    """¿Qué OT/línea/producto tengo activo en esta máquina ahora? Incluye el turno actual y si la asignación quedó vencida.

    Contrato HISTÓRICO de una sola asignación. Con 2+ activas (varias líneas de la misma OT, solo con la compuerta multimáquina) no se
    elige una al azar ni se devuelve `null` (se leería como 'sin asignación'): 409 MULTIPLE_ACTIVE_ASSIGNMENTS. Las pantallas que necesiten
    varias líneas leen `get_active_lines` (GET /api/assignments/active-lines).
    """
    items, shift = _active_items(connection, machine_code, sectors)
    if len(items) > 1:
        raise MultipleActiveAssignmentsError()
    item = items[0] if items else None
    return ActiveAssignment(item.assignment if item else None, shift.shift_code if shift else None, shift.shift_name if shift else None,
                            shift.operating_date if shift else None, item.stale if item else None)


def get_active_lines(connection, *, machine_code, sectors) -> ActiveLines:
    """Contrato multilínea (PR5/PR8): TODAS las activas de la máquina con su 'vencida' y el turno actual. Sin selección implícita."""
    items, shift = _active_items(connection, machine_code, sectors)
    return ActiveLines(shift.shift_code if shift else None, shift.shift_name if shift else None, shift.operating_date if shift else None, items)

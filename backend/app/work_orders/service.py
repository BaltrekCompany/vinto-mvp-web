"""Dominio de órdenes de trabajo BASE (Bobinas): crear, añadir líneas a un borrador, publicar y consultar.

Alcance de este bloque: solo la versión `baseline` (version_number = 1). No hay versiones operativas,
asignaciones, edición ni borrado: una línea base publicada es inmutable (y las tablas lo imponen además
con triggers). Todas las funciones esperan una conexión psycopg en autocommit y gestionan su transacción.

Decisiones:
- Máquina y artículos se resuelven siempre por código contra los maestros; el cliente nunca envía ids,
  descripciones ni unidades. El alcance se define por sector (`ALLOWED_SECTOR_CODES`), no por listas de máquinas.
- Cada línea congela el `article_version_id` MÁS RECIENTE (mayor version_number) del artículo en ese momento y
  toma la unidad de esa versión.
- El número `OT-AAAA-NNNN` y el `line_code` (L1, L2, ...) se generan en el servidor. Sin tablas nuevas, la
  numeración usa un advisory lock transaccional estable; UNIQUE(number) y UNIQUE(version, line_code) son la
  defensa final. El esquema de numeración puede reemplazarse cuando Expertus sea la autoridad de las OT.
- Auditoría: cada transacción fija vinto.actor_id (created_by/updated_by), vinto.request_id y vinto.reason.
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.work_orders.errors import (ArticleNotAllowedForMachineError, ArticleNotFoundError, InvalidWorkOrderLineError,
                                    MachineNotFoundError, MachineOutsideScopeError, WorkOrderAlreadyPublishedError,
                                    WorkOrderNotDraftError, WorkOrderNotFoundError, WorkOrderNotPublishableError)

ALLOWED_SECTOR_CODES = ("BOBINAS",)
MAX_PV_LENGTH = 100
MAX_ARTICLE_CODE_LENGTH = 64
MAX_QUANTITY_DIGITS = 15
MAX_QUANTITY_DECIMALS = 3
MAX_LINES_PER_ORDER = 200
DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 500
STATUSES = ("draft", "published", "in_progress", "closed")
_NUMBER_LOCK = int.from_bytes(hashlib.sha256(b"vinto-work-order-number").digest()[:8], "big", signed=True)


@dataclass(frozen=True)
class LineInput:
    pv_reference: str
    article_code: str
    quantity: Decimal | int | str
    due_date: date


@dataclass(frozen=True)
class LineView:
    id: uuid.UUID
    line_code: str
    pv_reference: str
    article_code: str
    article_description: str
    quantity: Decimal
    unit: str
    due_date: date


@dataclass(frozen=True)
class BaselineView:
    id: uuid.UUID
    version_number: int
    published_at: datetime | None
    lines: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class WorkOrderView:
    id: uuid.UUID
    number: str
    status: str
    machine_code: str
    machine_name: str
    baseline: BaselineView


# ---------------------------------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------------------------------

def clean_line(line: LineInput) -> tuple[str, str, Decimal, date]:
    """Valida y normaliza una línea de entrada (el dominio no confía en la capa HTTP)."""
    pv = line.pv_reference.strip() if isinstance(line.pv_reference, str) else ""
    if not pv or len(pv) > MAX_PV_LENGTH:
        raise InvalidWorkOrderLineError(f"pv_reference debe tener de 1 a {MAX_PV_LENGTH} caracteres")
    code = line.article_code.strip() if isinstance(line.article_code, str) else ""
    if not code or len(code) > MAX_ARTICLE_CODE_LENGTH:
        raise InvalidWorkOrderLineError("article_code es obligatorio")
    if isinstance(line.quantity, bool) or not isinstance(line.quantity, (Decimal, int, str)):
        raise InvalidWorkOrderLineError("quantity debe ser un número")
    try:
        quantity = Decimal(line.quantity) if not isinstance(line.quantity, Decimal) else line.quantity
    except InvalidOperation:
        raise InvalidWorkOrderLineError("quantity debe ser un número") from None
    if not quantity.is_finite() or quantity <= 0:
        raise InvalidWorkOrderLineError("quantity debe ser mayor que 0")
    _, digits, exponent = quantity.as_tuple()
    if exponent < -MAX_QUANTITY_DECIMALS or len(digits) + max(exponent, 0) > MAX_QUANTITY_DIGITS:
        raise InvalidWorkOrderLineError(f"quantity admite hasta {MAX_QUANTITY_DECIMALS} decimales y {MAX_QUANTITY_DIGITS} dígitos")
    if not isinstance(line.due_date, date) or isinstance(line.due_date, datetime):
        raise InvalidWorkOrderLineError("due_date debe ser una fecha válida")
    return pv, code, quantity, line.due_date


# ---------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------

def _context(connection, actor_id, request_id, reason):
    connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
    connection.execute("SELECT set_config('vinto.request_id', %s, true)", (request_id or f"work_order:{uuid.uuid4()}",))
    connection.execute("SELECT set_config('vinto.reason', %s, true)", (reason,))


def _machine(connection, machine_code):
    if not isinstance(machine_code, str) or not machine_code.strip():
        raise MachineNotFoundError("machine_code es obligatorio")
    row = connection.execute(
        """SELECT m.id, m.code, m.name, m.active, s.code FROM vinto_master.machine m
           JOIN vinto_master.sector s ON s.id = m.sector_id WHERE m.code = %s""", (machine_code.strip(),)).fetchone()
    if row is None:
        raise MachineNotFoundError()
    machine_id, _, _, active, sector_code = row
    if not active or sector_code not in ALLOWED_SECTOR_CODES:
        raise MachineOutsideScopeError()
    return machine_id


def _next_number(connection) -> str:
    """OT-AAAA-NNNN. Se llama con el advisory lock tomado: el siguiente correlativo del año del reloj de PostgreSQL."""
    year = connection.execute("SELECT extract(year FROM clock_timestamp())::int").fetchone()[0]
    highest = connection.execute(
        "SELECT coalesce(max(substring(number from '^OT-[0-9]{4}-([0-9]+)$')::int), 0) FROM vinto_txn.work_order WHERE number ~ %s",
        (f"^OT-{year}-[0-9]+$",)).fetchone()[0]
    return f"OT-{year}-{highest + 1:04d}"


def _resolve_article(connection, machine_id, article_code):
    """article -> versión más reciente -> unidad. Exige artículo activo, producto y permitido en la máquina."""
    row = connection.execute("SELECT id, is_product, active FROM vinto_master.article WHERE code = %s", (article_code,)).fetchone()
    if row is None:
        raise ArticleNotFoundError()
    article_id, is_product, active = row
    if not active or not is_product:
        raise InvalidWorkOrderLineError(f"El artículo {article_code} no está activo o no es un producto")
    allowed = connection.execute("SELECT 1 FROM vinto_master.article_machine WHERE article_id = %s AND machine_id = %s", (article_id, machine_id)).fetchone()
    if allowed is None:
        raise ArticleNotAllowedForMachineError(f"El artículo {article_code} no está permitido para esa máquina")
    version = connection.execute(
        "SELECT id, unit_id FROM vinto_master.article_version WHERE article_id = %s ORDER BY version_number DESC LIMIT 1", (article_id,)).fetchone()
    if version is None:
        raise InvalidWorkOrderLineError(f"El artículo {article_code} no tiene versión vigente")
    return version


def _insert_line(connection, version_id, machine_id, line: LineInput):
    pv, code, quantity, due_date = clean_line(line)
    article_version_id, unit_id = _resolve_article(connection, machine_id, code)
    next_number = connection.execute(
        "SELECT coalesce(max(substring(line_code from 2)::int), 0) + 1 FROM vinto_txn.work_order_line WHERE work_order_version_id = %s AND line_code ~ '^L[0-9]+$'",
        (version_id,)).fetchone()[0]
    connection.execute(
        """INSERT INTO vinto_txn.work_order_line (work_order_version_id,line_code,pv_reference,article_version_id,unit_id,quantity,due_date)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""", (version_id, f"L{next_number}", pv, article_version_id, unit_id, quantity, due_date))


def _lock_baseline(connection, work_order_id):
    """Bloquea la OT y su baseline v1 (FOR UPDATE) y devuelve (status, machine_id, version_id, published_at)."""
    row = connection.execute(
        """SELECT wo.status, wo.machine_id, v.id, v.published_at
           FROM vinto_txn.work_order wo
           JOIN vinto_txn.work_order_version v ON v.work_order_id = wo.id AND v.version_number = 1 AND v.kind = 'baseline'
           WHERE wo.id = %s FOR UPDATE OF wo, v""", (work_order_id,)).fetchone()
    if row is None:
        raise WorkOrderNotFoundError()
    return row


def _as_uuid(value):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise WorkOrderNotFoundError() from None


# ---------------------------------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------------------------------

def create_work_order(connection, *, actor_id, machine_code, lines, request_id=None) -> WorkOrderView:
    """OT en borrador + baseline v1 (sin publicar) + líneas L1..Ln, todo o nada."""
    lines = list(lines)
    if not lines:
        raise InvalidWorkOrderLineError("Se requiere al menos una línea")
    if len(lines) > MAX_LINES_PER_ORDER:
        raise InvalidWorkOrderLineError(f"Máximo {MAX_LINES_PER_ORDER} líneas por orden")
    with connection.transaction():
        _context(connection, actor_id, request_id, "work order create")
        machine_id = _machine(connection, machine_code)
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (_NUMBER_LOCK,))  # serializa la numeración hasta el commit
        number = _next_number(connection)
        work_order_id = connection.execute("INSERT INTO vinto_txn.work_order (number,machine_id) VALUES (%s,%s) RETURNING id", (number, machine_id)).fetchone()[0]
        version_id = connection.execute(
            "INSERT INTO vinto_txn.work_order_version (work_order_id,version_number,kind) VALUES (%s,1,'baseline') RETURNING id", (work_order_id,)).fetchone()[0]
        for line in lines:  # el orden del arreglo define L1, L2, ...; una línea inválida revierte todo
            _insert_line(connection, version_id, machine_id, line)
    return get_work_order(connection, work_order_id)


def add_line(connection, *, actor_id, work_order_id, line: LineInput, request_id=None) -> WorkOrderView:
    """Añade la siguiente línea a una baseline NO publicada. Después de publicar no se permite."""
    work_order_id = _as_uuid(work_order_id)
    with connection.transaction():
        _context(connection, actor_id, request_id, "work order add baseline line")
        status, machine_id, version_id, published_at = _lock_baseline(connection, work_order_id)
        if published_at is not None or status == "published":
            raise WorkOrderAlreadyPublishedError()
        if status != "draft":
            raise WorkOrderNotDraftError()
        count = connection.execute("SELECT count(*) FROM vinto_txn.work_order_line WHERE work_order_version_id = %s", (version_id,)).fetchone()[0]
        if count >= MAX_LINES_PER_ORDER:
            raise InvalidWorkOrderLineError(f"Máximo {MAX_LINES_PER_ORDER} líneas por orden")
        _insert_line(connection, version_id, machine_id, line)
    return get_work_order(connection, work_order_id)


def publish_work_order(connection, *, actor_id, work_order_id, request_id=None) -> WorkOrderView:
    """Publica la baseline. Idempotente: si ya está publicada devuelve el estado actual sin escribir nada."""
    work_order_id = _as_uuid(work_order_id)
    with connection.transaction():
        _context(connection, actor_id, request_id, "work order publish baseline")
        status, machine_id, version_id, published_at = _lock_baseline(connection, work_order_id)
        if status == "published" and published_at is not None:
            return get_work_order(connection, work_order_id)
        if status != "draft" or published_at is not None:
            raise WorkOrderNotPublishableError()
        lines = connection.execute("SELECT count(*) FROM vinto_txn.work_order_line WHERE work_order_version_id = %s", (version_id,)).fetchone()[0]
        if lines == 0:
            raise WorkOrderNotPublishableError("La orden no tiene líneas")
        incoherent = connection.execute(
            """SELECT l.line_code FROM vinto_txn.work_order_line l
               JOIN vinto_master.article_version av ON av.id = l.article_version_id
               JOIN vinto_master.article a ON a.id = av.article_id
               WHERE l.work_order_version_id = %s AND (NOT a.active OR NOT a.is_product OR NOT EXISTS
                     (SELECT 1 FROM vinto_master.article_machine am WHERE am.article_id = a.id AND am.machine_id = %s))
               ORDER BY l.line_code""", (version_id, machine_id)).fetchall()
        if incoherent:
            raise WorkOrderNotPublishableError("Las líneas ya no son coherentes con los maestros: " + ", ".join(r[0] for r in incoherent))
        connection.execute("UPDATE vinto_txn.work_order_version SET published_at = clock_timestamp() WHERE id = %s", (version_id,))
        connection.execute("UPDATE vinto_txn.work_order SET status = 'published' WHERE id = %s", (work_order_id,))
    return get_work_order(connection, work_order_id)


# ---------------------------------------------------------------------------------------------------
# queries
# ---------------------------------------------------------------------------------------------------

_HEADER_SQL = """SELECT wo.id, wo.number, wo.status, m.code, m.name, v.id, v.version_number, v.published_at
                 FROM vinto_txn.work_order wo
                 JOIN vinto_master.machine m ON m.id = wo.machine_id
                 JOIN vinto_master.sector s ON s.id = m.sector_id
                 JOIN vinto_txn.work_order_version v ON v.work_order_id = wo.id AND v.version_number = 1 AND v.kind = 'baseline'
                 WHERE s.code = ANY(%s)"""


def _hydrate(connection, headers) -> list[WorkOrderView]:
    version_ids = [row[5] for row in headers]
    lines: dict = {version_id: [] for version_id in version_ids}
    if version_ids:
        rows = connection.execute(
            """SELECT l.work_order_version_id, l.id, l.line_code, l.pv_reference, a.code, av.description, l.quantity, u.code, l.due_date
               FROM vinto_txn.work_order_line l
               JOIN vinto_master.article_version av ON av.id = l.article_version_id
               JOIN vinto_master.article a ON a.id = av.article_id
               JOIN vinto_master.unit u ON u.id = l.unit_id
               WHERE l.work_order_version_id = ANY(%s) ORDER BY l.work_order_version_id, length(l.line_code), l.line_code""", (version_ids,)).fetchall()
        for version_id, *rest in rows:
            lines[version_id].append(LineView(*rest))
    return [WorkOrderView(wo_id, number, status, machine_code, machine_name,
                          BaselineView(version_id, version_number, published_at, tuple(lines[version_id])))
            for wo_id, number, status, machine_code, machine_name, version_id, version_number, published_at in headers]


def get_work_order(connection, work_order_id) -> WorkOrderView:
    """Detalle (solo la baseline). OT inexistente o fuera del alcance: WorkOrderNotFoundError."""
    work_order_id = _as_uuid(work_order_id)
    headers = connection.execute(_HEADER_SQL + " AND wo.id = %s", (list(ALLOWED_SECTOR_CODES), work_order_id)).fetchall()
    if not headers:
        raise WorkOrderNotFoundError()
    return _hydrate(connection, headers)[0]


def list_work_orders(connection, *, machine_code=None, status=None, limit=DEFAULT_LIST_LIMIT) -> list[WorkOrderView]:
    """Más recientes primero (created_at y número descendentes, orden estable). Filtros opcionales: máquina y estado."""
    if status is not None and status not in STATUSES:
        raise InvalidWorkOrderLineError(f"status debe ser uno de {', '.join(STATUSES)}")
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    sql, params = _HEADER_SQL, [list(ALLOWED_SECTOR_CODES)]
    if machine_code is not None:
        sql += " AND m.code = %s"
        params.append(machine_code)
    if status is not None:
        sql += " AND wo.status = %s"
        params.append(status)
    headers = connection.execute(sql + " ORDER BY wo.created_at DESC, wo.number DESC LIMIT %s", (*params, limit)).fetchall()
    return _hydrate(connection, headers)

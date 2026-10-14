"""Captura productiva central multiformulario: formularios de producción manuales habilitados por política explícita (hoy solo F6, VINTO-P1-06),
con soporte opcional de GRUPOS REPETIBLES (M3-A, ver validate_form_values).

La asignación activa es la autoridad COMPLETA del contexto: máquina, turno, fecha operativa, OT, PV y producto salen de
ella; el cliente no decide nada de eso. Las definiciones de campos, tipos, obligatoriedad y opciones se leen de
vinto_config (form, form_version, field_definition, field_option); lo único fijo aquí es la POLÍTICA de qué códigos de formulario
habilita este endpoint (CENTRAL_FORM_CODES): un formulario publicado NO se acepta por el solo hecho de existir.

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
from app.sectors import scoped_sector_codes

FORM_CODE = "VINTO-P1-06"  # formulario histórico F6: respuesta por defecto de las lecturas
# POLÍTICA EXPLÍCITA de formularios de producción habilitados para captura central. Añadir un formulario aquí (p. ej. VINTO-P1-10) es una decisión
# deliberada de producto, nunca automática; además cada captura exige área production, versión publicada y relación formulario-máquina.
CENTRAL_FORM_CODES = frozenset({FORM_CODE})
PRODUCTION_AREA = "production"
GROUPS_KEY = "_groups"  # propiedad RESERVADA de `values` para los grupos repetibles; ningún campo de una definición puede llamarse así
TECHNICAL_MAX_GROUP_ROWS = 1000  # tope TÉCNICO (no funcional) por grupo cuando la definición no declara max_rows: evita cargas absurdas
REASON = "submit production capture"
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200
MAX_TEXT_LENGTH = 10_000  # límites técnicos, no funcionales
MAX_DECIMAL_CHARS = 40
INT_LIMIT = 9_223_372_036_854_775_807
DECIMAL_PATTERN = re.compile(r"-?[0-9]+(\.[0-9]+)?")
# Hora de un campo `time`: solo HH:MM o HH:MM:SS (00-23 / 00-59). `time.fromisoformat` aceptaría también «07», «0700», «T07:00», fracciones y zonas horarias (la zona se perdería al guardar en una columna `time`).
TIME_PATTERN = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?")
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
class GroupDef:
    id: uuid.UUID
    code: str
    display_order: int
    repeatable: bool
    min_rows: int
    max_rows: int | None


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


def is_central_form(form_code) -> bool:
    """¿Está `form_code` habilitado para captura central? Coincidencia exacta (sin mayúsculas/espacios implícitos); None o no-texto = no."""
    return isinstance(form_code, str) and form_code in CENTRAL_FORM_CODES


# ---------------------------------------------------------------------------------------------------
# definition and values
# ---------------------------------------------------------------------------------------------------

def load_fields(connection, form_version_id, *, allow_groups=False) -> list[FieldDef]:
    """Campos de la versión. Solo se soportan campos MANUALES; lo demás (automáticos, calculados) se rechaza en vez de aceptarse a medias.

    Los campos dentro de un grupo solo se aceptan con `allow_groups=True` (el motor central de producción); P1-03 y Calidad no los manejan y siguen
    rechazándolos. Un campo cuya clave es la propiedad reservada `_groups` hace inválida la definición."""
    rows = connection.execute(
        """SELECT f.id, f.key, f.value_type, f.source, f.required, f.field_group_id, u.code, f.display_order
           FROM vinto_config.field_definition f LEFT JOIN vinto_master.unit u ON u.id = f.unit_id
           WHERE f.form_version_id = %s ORDER BY f.display_order, f.key""", (form_version_id,)).fetchall()
    options: dict = {}
    for field_id, option_key in connection.execute(
            "SELECT field_definition_id, option_key FROM vinto_config.field_option WHERE form_version_id = %s", (form_version_id,)).fetchall():
        options.setdefault(field_id, []).append(option_key)
    fields = [FieldDef(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], tuple(options.get(r[0], ()))) for r in rows]
    unsupported = [f.key for f in fields if f.source != "manual" or (f.group_id is not None and not allow_groups)]
    if unsupported:
        raise UnsupportedFormDefinitionError(f"Campos no soportados: {', '.join(unsupported)}")
    if any(f.key == GROUPS_KEY for f in fields):
        raise UnsupportedFormDefinitionError(f"Un campo no puede llamarse {GROUPS_KEY} (propiedad reservada de los grupos)")
    return fields


def load_groups(connection, form_version_id) -> list[GroupDef]:
    """Grupos de la versión publicada, en orden determinista (display_order, code). Sin grupos = formulario sin filas repetibles."""
    rows = connection.execute(
        """SELECT id, code, display_order, repeatable, min_rows, max_rows FROM vinto_config.field_group
           WHERE form_version_id = %s ORDER BY display_order, code""", (form_version_id,)).fetchall()
    return [GroupDef(*r) for r in rows]


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
            if not isinstance(raw, str) or not TIME_PATTERN.fullmatch(raw):
                raise ValueError(raw)
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


def validate_form_values(fields: list[FieldDef], groups: list[GroupDef], values) -> dict:
    """Valida `values` de un formulario CON grupos: campos simples a nivel de captura y filas en `_groups` {código_de_grupo: [fila, ...]}.

    Resultado: {simples..., "_groups": {código: [ {clave: valor}, ... ]}} con TODOS los grupos declarados (lista vacía si no hay filas) y las filas en
    el orden recibido (el orden es contenido: row_number = posición + 1). Los grupos se resuelven SOLO por la definición publicada: un código no declarado,
    una clave que no pertenece a la fila, referencias internas (ids, row_number...) o metadatos son errores 422 que nombran la clave y nunca el valor."""
    if not isinstance(values, dict):
        raise CaptureValidationError("values debe ser un objeto")
    simple_fields = [f for f in fields if f.group_id is None]
    grouped_keys = {f.key: g for g in groups for f in fields if f.group_id == g.id}
    raw_groups = values.get(GROUPS_KEY, {})
    problems: list[str] = []
    simple = {k: v for k, v in values.items() if k != GROUPS_KEY}
    for key in sorted(k for k in simple if k in grouped_keys):
        problems.append(f"{key}: campo del grupo {grouped_keys[key].code}; se envía dentro de {GROUPS_KEY}")
        del simple[key]
    try:
        clean = validate_values(simple_fields, simple)
    except CaptureValidationError as error:
        problems.append(str(error))
        clean = {}
    by_code = {g.code: g for g in groups}
    out: dict = {g.code: [] for g in groups}
    if not isinstance(raw_groups, dict):
        problems.append(f"{GROUPS_KEY}: debe ser un objeto {{código_de_grupo: [filas]}}")
        raw_groups = {}
    for code in sorted(str(k) for k in raw_groups if k not in by_code):
        problems.append(f"{GROUPS_KEY}.{code}: grupo no declarado")
    for group in groups:
        rows = raw_groups.get(group.code, [])
        if not isinstance(rows, list):
            problems.append(f"{GROUPS_KEY}.{group.code}: debe ser una lista de filas")
            continue
        limit = group.max_rows if group.max_rows is not None else TECHNICAL_MAX_GROUP_ROWS
        if len(rows) < group.min_rows:
            problems.append(f"{GROUPS_KEY}.{group.code}: se requieren al menos {group.min_rows} filas")
        if len(rows) > limit:
            problems.append(f"{GROUPS_KEY}.{group.code}: máximo {limit} filas")
            continue
        if not group.repeatable and len(rows) > 1:
            problems.append(f"{GROUPS_KEY}.{group.code}: el grupo no es repetible (máximo 1 fila)")
            continue
        row_fields = [f for f in fields if f.group_id == group.id]
        by_key = {f.key: f for f in row_fields}
        for number, row in enumerate(rows, start=1):
            where = f"{GROUPS_KEY}.{group.code}[{number}]"
            if not isinstance(row, dict):
                problems.append(f"{where}: la fila debe ser un objeto")
                continue
            row_problems = [f"{where}.{key}: campo desconocido" for key in sorted(str(k) for k in row if k not in by_key)]
            clean_row = {}
            for definition in row_fields:
                value, problem = _normalize(definition, row.get(definition.key))
                if problem:
                    row_problems.append(f"{where}.{definition.key}: {problem}")
                elif value is None:
                    if definition.required:
                        row_problems.append(f"{where}.{definition.key}: obligatorio")
                else:
                    clean_row[definition.key] = value
            if not row_problems and not clean_row:
                row_problems.append(f"{where}: la fila no tiene valores")
            problems.extend(row_problems)
            out[group.code].append(clean_row)
    if problems:
        raise CaptureValidationError("; ".join(problems))
    return {**clean, GROUPS_KEY: out}


_COLUMNS = {"text": "value_text", "textarea": "value_text", "decimal": "value_decimal", "integer": "value_integer",
            "boolean": "value_boolean", "date": "value_date", "time": "value_time"}


def _insert_details(connection, capture_id, form_version_id, fields, clean):
    for definition in fields:  # una sola columna de valor por detalle, según el tipo del campo
        if definition.key in clean:
            connection.execute(
                f"""INSERT INTO vinto_txn.capture_detail (capture_id, form_version_id, field_definition_id, value_type, {_COLUMNS[definition.value_type]})
                    VALUES (%s,%s,%s,%s,%s)""", (capture_id, form_version_id, definition.id, definition.value_type, clean[definition.key]))


def _insert_groups(connection, capture_id, form_version_id, fields, groups, clean_groups):
    """capture_group_row + capture_detail de cada fila, en orden determinista (grupos por display_order, filas por posición -> row_number = posición + 1)."""
    for group in groups:
        row_fields = [f for f in fields if f.group_id == group.id]
        for number, row in enumerate(clean_groups.get(group.code, []), start=1):
            row_id = connection.execute(
                """INSERT INTO vinto_txn.capture_group_row (capture_id, form_version_id, field_group_id, row_number)
                   VALUES (%s,%s,%s,%s) RETURNING id""", (capture_id, form_version_id, group.id, number)).fetchone()[0]
            for definition in row_fields:
                if definition.key in row:
                    connection.execute(
                        f"""INSERT INTO vinto_txn.capture_detail (capture_id, form_version_id, field_definition_id, field_group_id, group_row_id, value_type, {_COLUMNS[definition.value_type]})
                            VALUES (%s,%s,%s,%s,%s,%s,%s)""", (capture_id, form_version_id, definition.id, group.id, row_id, definition.value_type, row[definition.key]))


def _prepare_content(connection, form_version_id, values):
    """Campos, grupos y contenido NORMALIZADO de `values` para una versión. Sin grupos declarados se comporta exactamente como antes
    (validate_values, sin `_groups`: un `_groups` enviado a un formulario sin grupos es un campo desconocido, como cualquier otro)."""
    fields = load_fields(connection, form_version_id, allow_groups=True)
    groups = load_groups(connection, form_version_id)
    if not groups:
        return fields, groups, validate_values(fields, values)
    return fields, groups, validate_form_values(fields, groups, values)


def _serialize_values(values: dict) -> dict:
    """Valores listos para JSON (decimales como texto); los grupos conservan la estructura {código: [fila, ...]}."""
    return {k: ({code: [{key: _serialize(v) for key, v in row.items()} for row in rows] for code, rows in v.items()} if k == GROUPS_KEY else _serialize(v))
            for k, v in values.items()}


def _serialize(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, time)):
        return value.isoformat()
    return value


# ---------------------------------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------------------------------

_VIEW_SELECT = """SELECT c.id, c.status, c.revision, c.captured_at, c.submitted_at, c.operating_date, f.code, fv.version_number, fv.name,
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
               JOIN vinto_master.article ar ON ar.id = av.article_id"""
# Un solo formulario (compatibilidad: P1-03 de bobinas la usa con (código, sectores)).
_VIEW_SQL = _VIEW_SELECT + " WHERE f.code = %s AND s.code = ANY(%s)"
# Producción central: cualquier formulario HABILITADO (código, área production) dentro de los sectores del usuario; nunca Calidad ni otros códigos.
_CENTRAL_VIEW_SQL = _VIEW_SELECT + " WHERE f.code = ANY(%s) AND fv.area = 'production' AND s.code = ANY(%s)"


def _stored_values(connection, capture_id) -> dict:
    """Valores guardados: campos simples y, si la versión declara grupos, `_groups` {código: [fila, ...]} con las filas en su orden original (row_number)."""
    rows = connection.execute(
        """SELECT f.key, f.display_order, f.value_type, d.value_text, d.value_decimal, d.value_integer, d.value_boolean, d.value_date, d.value_time, d.group_row_id
           FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id
           WHERE d.capture_id = %s ORDER BY f.display_order, f.key""", (capture_id,)).fetchall()
    values = {r[0]: next(v for v in r[3:9] if v is not None) for r in rows if r[9] is None}
    declared = connection.execute(
        """SELECT g.id, g.code FROM vinto_config.field_group g JOIN vinto_txn.capture c ON c.form_version_id = g.form_version_id
           WHERE c.id = %s ORDER BY g.display_order, g.code""", (capture_id,)).fetchall()
    if not declared:
        return values
    row_ids = connection.execute(
        "SELECT id, field_group_id FROM vinto_txn.capture_group_row WHERE capture_id = %s ORDER BY field_group_id, row_number", (capture_id,)).fetchall()
    cells: dict = {}
    for r in rows:
        if r[9] is not None:
            cells.setdefault(r[9], {})[r[0]] = next(v for v in r[3:9] if v is not None)
    values[GROUPS_KEY] = {code: [cells.get(row_id, {}) for row_id, group_id in row_ids if group_id == gid] for gid, code in declared}
    return values


def _to_view(connection, row) -> CaptureView:
    return CaptureView(*row, values=_serialize_values(_stored_values(connection, row[0])))


def get_capture(connection, capture_id, *, sectors) -> CaptureView:
    capture_id = _uuid(capture_id, CaptureNotFoundError)
    rows = connection.execute(_CENTRAL_VIEW_SQL + " AND c.id = %s", (sorted(CENTRAL_FORM_CODES), list(scoped_sector_codes(sectors)), capture_id)).fetchall()
    if not rows:
        raise CaptureNotFoundError()
    return _to_view(connection, rows[0])


def list_captures(connection, *, assignment_id=None, machine_code=None, operating_date=None, limit=DEFAULT_LIST_LIMIT, form_code=None,
                  sectors) -> list[CaptureView]:
    """Capturas centrales enviadas (submitted/closed), más recientes primero. Sin borradores.

    Sin `form_code` se conserva el comportamiento histórico (solo F6). Con `form_code` se filtra a ese formulario, que debe estar habilitado
    (CENTRAL_FORM_CODES); cualquier otro código es UnsupportedFormError (422) en vez de una lista vacía engañosa."""
    if form_code is not None and not is_central_form(form_code):
        raise UnsupportedFormError("Formulario no habilitado para captura central")
    sql = _VIEW_SQL + " AND fv.area = 'production' AND c.status IN ('submitted','closed')"
    params = [FORM_CODE if form_code is None else form_code, list(scoped_sector_codes(sectors))]
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
        incoming = _prepare_content(connection, form_version_id, values)[2]
    except (CaptureValidationError, UnsupportedFormDefinitionError):
        return False
    return incoming == _stored_values(connection, capture_id)  # incluye TODAS las filas de los grupos, en orden


@dataclass(frozen=True)
class ActiveContext:
    """Contexto que la asignación vigente impone a una captura (el cliente no decide nada de esto)."""
    machine_id: uuid.UUID
    shift_schedule_id: uuid.UUID
    operating_date: date
    article_version_id: uuid.UUID
    now: datetime


def lock_active_assignment(connection, assignment_id, sectors) -> ActiveContext:
    """Toma el lock de máquina y valida que la asignación siga activa y vigente para el turno/fecha actuales.

    Compartido por F6 y F3: AssignmentNotFoundError, AssignmentNotActiveError y AssignmentStaleError (más los errores de
    resolución de turno) mantienen exactamente su semántica. Debe llamarse dentro de la transacción de la captura.
    """
    head = connection.execute(
        """SELECT a.machine_id FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id = a.machine_id
           JOIN vinto_master.sector s ON s.id = m.sector_id WHERE a.id = %s AND s.code = ANY(%s)""", (assignment_id, list(scoped_sector_codes(sectors)))).fetchone()
    if head is None:
        raise AssignmentNotFoundError()
    _machine_lock(connection, head[0])  # serializa con activate/finish de la misma máquina
    now = _now(connection)  # tras obtener el lock: el instante refleja el estado que se valida
    row = connection.execute(
        """SELECT a.status, a.machine_id, a.shift_schedule_id, a.operating_date, m.active, s.id, v.kind, wo.status, l.article_version_id
           FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id = a.machine_id JOIN vinto_master.sector s ON s.id = m.sector_id
           JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
           JOIN vinto_txn.work_order wo ON wo.id = v.work_order_id WHERE a.id = %s FOR SHARE OF a""", (assignment_id,)).fetchone()
    status, machine_id, schedule_id, operating_date, machine_active, sector_id, version_kind, order_status, article_version_id = row
    if status != "active" or not machine_active or version_kind != "operational" or order_status == "closed":
        raise AssignmentNotActiveError()
    shift = resolve_shift(connection, now, sector_id=sector_id)  # SHIFT_NOT_CONFIGURED / SHIFT_AMBIGUOUS siguen su manejo seguro
    if (shift.shift_schedule_id, shift.operating_date) != (schedule_id, operating_date):
        raise AssignmentStaleError()
    return ActiveContext(machine_id, schedule_id, operating_date, article_version_id, now)


def published_form_version(connection, form_code: str, machine_id, *, area: str = "production") -> uuid.UUID:
    """Versión publicada más alta del formulario en `area` (production por defecto: F6/F3 no cambian; Calidad pasa 'quality') y
    habilitada para la máquina; si no, FormNotAvailableError."""
    version = connection.execute(
        """SELECT fv.id FROM vinto_config.form f JOIN vinto_config.form_version fv ON fv.form_id = f.id
           WHERE f.code = %s AND f.active AND fv.status = 'published' AND fv.area = %s ORDER BY fv.version_number DESC LIMIT 1""",
        (form_code, area)).fetchone()
    if version is None:
        raise FormNotAvailableError()
    allowed = connection.execute("SELECT 1 FROM vinto_config.form_version_machine WHERE form_version_id = %s AND machine_id = %s",
                                 (version[0], machine_id)).fetchone()
    if allowed is None:
        raise FormNotAvailableError()
    return version[0]


def submit_production_capture(connection, *, actor_id, capture_id, form_code, assignment_id, device_key, values, request_id=None, sectors) -> CaptureResult:
    """Crea y envía una captura de producción de forma atómica e idempotente (capture.id = capture_id del cliente).

    `form_code` debe estar en la política CENTRAL_FORM_CODES; el resto (área production, versión publicada, máquina de la asignación, sector
    operativo ∩ concedido) lo exige este mismo flujo para cualquier formulario."""
    if not is_central_form(form_code):
        raise UnsupportedFormError("Formulario no habilitado para captura central")
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
                return CaptureResult(get_capture(connection, capture_id, sectors=sectors), created=False, already_submitted=True)
            raise CaptureIdempotencyConflictError()

        context = lock_active_assignment(connection, assignment_id, sectors)
        machine_id, schedule_id, operating_date, now = context.machine_id, context.shift_schedule_id, context.operating_date, context.now

        device_id = _resolve_device(connection, device_key, machine_id)

        form_version_id = published_form_version(connection, form_code, machine_id)
        fields, groups, clean = _prepare_content(connection, form_version_id, values)

        connection.execute(
            """INSERT INTO vinto_txn.capture (id, form_version_id, machine_id, shift_schedule_id, device_id, assignment_id, operating_date, captured_at, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'draft')""",
            (capture_id, form_version_id, machine_id, schedule_id, device_id, assignment_id, operating_date, now))
        _insert_details(connection, capture_id, form_version_id, [f for f in fields if f.group_id is None], {k: v for k, v in clean.items() if k != GROUPS_KEY})
        if groups:
            _insert_groups(connection, capture_id, form_version_id, fields, groups, clean[GROUPS_KEY])
        connection.execute("UPDATE vinto_txn.capture SET status = 'submitted', submitted_at = clock_timestamp() WHERE id = %s", (capture_id,))
    return CaptureResult(get_capture(connection, capture_id, sectors=sectors), created=True, already_submitted=False)


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

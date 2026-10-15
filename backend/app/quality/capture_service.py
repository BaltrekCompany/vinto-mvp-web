"""Capturas de Calidad ligadas a una Bobina física (P1-19, P1-20 y, solo con política habilitada, los candidatos por bobina).

La autoridad del contexto es la BOBINA pedida: máquina, turno, fecha operativa, asignación, OT, línea, PV y artículo se derivan de
su captura F3 de origen (bobbin -> source_capture -> assignment -> work_order_line -> work_order_version -> work_order). NO se usa la
asignación activa, ni resolve_shift, ni lock_active_assignment, ni el turno/fecha actuales: una Bobina sigue siendo evaluable aunque
su asignación esté terminada. Solo captured_at es el instante real del ensayo (reloj de PostgreSQL).

Una captura es UNA transacción:
  lock(capture_id) -> contexto de auditoría -> idempotencia -> Bobina + contexto histórico -> dispositivo -> versión publicada del
  formulario (area quality, habilitada para la máquina de la Bobina) -> validación de valores -> INSERT capture (draft, bobbin_id)
  -> INSERT capture_detail tipados -> UPDATE draft->submitted (revision 1).

NUNCA toca quality_release: ni liberar, ni rechazar, ni decided_by/decided_at/decision_reason.

POLÍTICA POSITIVA DE LA RUTA POR BOBINA (INT-01A): esta ruta solo acepta (escritura, reintento idempotente, lectura por id, historial y historial filtrado) los formularios de `_allowed_codes()`:
`CENTRAL_BOBBIN_FORM_CODES` (P1-19 y P1-20) más los candidatos por bobina que `ENABLED_BOBBIN_CANDIDATE_FORM_CODES` habilite. Que un formulario de área `quality` esté publicado y vinculado a la máquina de la Bobina
NO basta: los exclusivos de Calidad por máquina (P1-18, P1-22, P1-26, P1-27) y cualquier formulario desconocido se rechazan (422 UNSUPPORTED_FORM) y sus capturas no se leen por esta ruta (404). Los entornos de prueba
amplían la política con patch.object sobre estas constantes; la configuración real no cambia.

FORMULARIOS CANDIDATOS POR BOBINA (DEV-Q2, DEV-Q3 y DEV-CLOSE, VINTO-P1-21 / P1-24 / P1-25 / P1-28; P1-28 es una ficha DOCUMENTAL: no rechaza ni toca quality_release): `BOBBIN_CANDIDATE_FORM_CODES` los conoce y `ENABLED_BOBBIN_CANDIDATE_FORM_CODES` (VACÍA en la configuración real) los habilita; solo los entornos de
prueba lo hacen con patch.object. Un candidato no habilitado se rechaza (422), no se lista y sus capturas no se leen. Todo formulario que NO figure en `_allowed_codes()` se trata igual,
sea candidato deshabilitado, exclusivo de Calidad por máquina o desconocido, aunque esté publicado y vinculado a la máquina de la Bobina (INT-01A); P1-19 y P1-20 siguen siendo los únicos formularios centrales admitidos.
Si el formulario declara un campo con el número de bobina (`BOBBIN_CODE_FIELDS`), debe coincidir con la Bobina de la ruta: un registro contradictorio se rechaza (422).
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from app import capture_service as cs
from app.bobbins.errors import BobbinNotFoundError
from app.capture_errors import CaptureIdempotencyConflictError, CaptureNotFoundError, CaptureValidationError, UnsupportedFormDefinitionError, UnsupportedFormError
from app.quality.form_availability import available_quality_forms
from app.sectors import scoped_sector_codes

REASON = "submit quality capture"
QUALITY_AREA = "quality"

# POLÍTICA (INT-01A): formularios CENTRALES de Calidad por Bobina permitidos por esta ruta. Los candidatos por Bobina se suman solo si ENABLED_BOBBIN_CANDIDATE_FORM_CODES los habilita.
CENTRAL_BOBBIN_FORM_CODES: frozenset = frozenset({"VINTO-P1-19", "VINTO-P1-20"})
# POLÍTICA: formularios candidatos por Bobina (sin homologar). Conocidos aquí; habilitados SOLO si figuran en ENABLED_… (vacío en producción).
BOBBIN_CANDIDATE_FORM_CODES: frozenset = frozenset({"VINTO-P1-21", "VINTO-P1-24", "VINTO-P1-25", "VINTO-P1-28"})
ENABLED_BOBBIN_CANDIDATE_FORM_CODES: frozenset = frozenset()
# Campo manual que declara el número de bobina: debe ser exactamente el código de la Bobina de la ruta (se compara el texto recortado, sin interpretarlo).
BOBBIN_CODE_FIELDS: dict = {"VINTO-P1-21": "numero_de_bobina", "VINTO-P1-24": "numero_de_bobina", "VINTO-P1-25": "numero_de_bobina", "VINTO-P1-28": "numero_de_bobina"}


@dataclass(frozen=True)
class QualityCaptureView:
    id: uuid.UUID
    status: str
    revision: int
    captured_at: datetime
    submitted_at: datetime | None
    operating_date: date
    form_code: str
    form_version_number: int
    form_name: str
    bobbin_id: uuid.UUID
    bobbin_code: str
    machine_code: str
    machine_name: str
    shift_code: str
    shift_name: str
    work_order_id: uuid.UUID
    work_order_number: str
    line_id: uuid.UUID
    line_code: str
    pv_reference: str
    article_code: str
    article_description: str
    values: dict = field(default_factory=dict)  # clave -> valor serializable (decimales como texto exacto)


@dataclass(frozen=True)
class QualityCaptureResult:
    capture: QualityCaptureView
    created: bool
    already_submitted: bool


@dataclass(frozen=True)
class _BobbinContext:
    bobbin_id: uuid.UUID
    machine_id: uuid.UUID
    shift_schedule_id: uuid.UUID
    operating_date: date
    assignment_id: uuid.UUID


# El artículo y la OT/línea/PV salen de la asignación HISTÓRICA de la captura (la misma que la F3 de origen; lo garantiza 0005).
_VIEW_SQL = """SELECT c.id, c.status, c.revision, c.captured_at, c.submitted_at, c.operating_date, f.code, fv.version_number, fv.name,
                      b.id, b.code, m.code, m.name, sh.code, sh.name, wo.id, wo.number, l.id, l.line_code, l.pv_reference, ar.code, av.description
               FROM vinto_txn.capture c
               JOIN vinto_config.form_version fv ON fv.id = c.form_version_id
               JOIN vinto_config.form f ON f.id = fv.form_id
               JOIN vinto_txn.bobbin b ON b.id = c.bobbin_id
               JOIN vinto_master.machine m ON m.id = c.machine_id
               JOIN vinto_master.sector s ON s.id = m.sector_id
               JOIN vinto_config.shift_schedule sc ON sc.id = c.shift_schedule_id
               JOIN vinto_config.shift sh ON sh.id = sc.shift_id
               JOIN vinto_txn.assignment a ON a.id = c.assignment_id
               JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
               JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
               JOIN vinto_txn.work_order wo ON wo.id = v.work_order_id
               JOIN vinto_master.article_version av ON av.id = b.article_version_id
               JOIN vinto_master.article ar ON ar.id = av.article_id
               WHERE fv.area = 'quality' AND c.bobbin_id IS NOT NULL AND s.code = ANY(%s) AND f.code = ANY(%s)"""


def _allowed(code) -> bool:
    return isinstance(code, str) and (code in CENTRAL_BOBBIN_FORM_CODES or (code in BOBBIN_CANDIDATE_FORM_CODES and code in ENABLED_BOBBIN_CANDIDATE_FORM_CODES))


def _allowed_codes() -> list[str]:
    """Formularios que esta ruta admite hoy (política positiva). Todo lo demás: no se acepta, no se lee y no se lista."""
    return sorted(CENTRAL_BOBBIN_FORM_CODES | (BOBBIN_CANDIDATE_FORM_CODES & ENABLED_BOBBIN_CANDIDATE_FORM_CODES))


def _to_view(connection, row) -> QualityCaptureView:
    return QualityCaptureView(*row, values={k: cs._serialize(v) for k, v in cs._stored_values(connection, row[0]).items()})


def get_quality_capture(connection, capture_id, *, sectors) -> QualityCaptureView:
    capture_id = cs._uuid(capture_id, CaptureNotFoundError)
    row = connection.execute(_VIEW_SQL + " AND c.id = %s", (list(scoped_sector_codes(sectors)), _allowed_codes(), capture_id)).fetchone()
    if row is None:
        raise CaptureNotFoundError()
    return _to_view(connection, row)


def _bobbin_context(connection, bobbin_id, sectors) -> _BobbinContext:
    """Bobina numerada F3 del alcance (Bobinas) y el contexto productivo de su captura F3 de origen. 404 si no existe."""
    row = connection.execute(
        """SELECT b.id, b.machine_id, c.shift_schedule_id, c.operating_date, c.assignment_id
           FROM vinto_txn.bobbin b JOIN vinto_txn.capture c ON c.id = b.source_capture_id
           JOIN vinto_master.machine m ON m.id = b.machine_id JOIN vinto_master.sector s ON s.id = m.sector_id
           WHERE b.id = %s AND b.sequence_number IS NOT NULL AND s.code = ANY(%s)""", (bobbin_id, list(scoped_sector_codes(sectors)))).fetchone()
    if row is None or row[4] is None:
        raise BobbinNotFoundError()
    return _BobbinContext(*row)


def available_bobbin_forms(connection, *, sectors) -> list[dict]:
    """Máquinas del alcance y candidatos por Bobina que el backend publica (política + versión publicada de área quality + vínculo). Vacío con la política real. Solo lectura."""
    return available_quality_forms(connection, sectors, BOBBIN_CANDIDATE_FORM_CODES & ENABLED_BOBBIN_CANDIDATE_FORM_CODES)


def _check_declared_bobbin(connection, form_code, bobbin_id, clean):
    """Un formulario que declara el número de bobina solo se acepta si coincide con la Bobina seleccionada (sin normalizar más que recortar espacios)."""
    key = BOBBIN_CODE_FIELDS.get(form_code)
    if key is None:
        return
    declared = clean.get(key)
    code = connection.execute("SELECT code FROM vinto_txn.bobbin WHERE id = %s", (bobbin_id,)).fetchone()[0]
    if not isinstance(declared, str) or declared.strip() != code:
        raise CaptureValidationError(f"{key} no coincide con la bobina seleccionada")


def list_bobbin_quality_captures(connection, bobbin_id, *, form_code=None, sectors) -> list[QualityCaptureView]:
    """Capturas de Calidad enviadas de una Bobina (más recientes primero; orden solo de presentación). Sin paginación. `form_code` opcional filtra por formulario (un candidato no habilitado: 422)."""
    bobbin_id = cs._uuid(bobbin_id, BobbinNotFoundError)
    _bobbin_context(connection, bobbin_id, sectors)
    if form_code is not None and not _allowed(form_code):
        raise UnsupportedFormError()  # un formulario que la política no admite (de máquina, candidato deshabilitado o desconocido) tampoco se consulta por esta ruta
    query, params = _VIEW_SQL + " AND c.bobbin_id = %s AND c.status IN ('submitted','closed')", [list(scoped_sector_codes(sectors)), _allowed_codes(), bobbin_id]
    if form_code is not None:
        query, params = query + " AND f.code = %s", params + [form_code]
    rows = connection.execute(query + " ORDER BY c.captured_at DESC, c.id DESC", params).fetchall()
    return [_to_view(connection, r) for r in rows]


def _context(connection, actor_id, request_id):
    connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
    connection.execute("SELECT set_config('vinto.request_id', %s, true)", (request_id,))
    connection.execute("SELECT set_config('vinto.reason', %s, true)", (REASON,))


def _existing_matches(connection, existing, *, actor_id, bobbin_id, form_code, device_key, values) -> bool:
    """¿El reintento coincide EXACTAMENTE (actor, Bobina, formulario, dispositivo y valores normalizados con la versión guardada)?"""
    capture_id, status, created_by, stored_bobbin, form_version_id, stored_form_code, stored_area, stored_device_key = existing
    if (status not in ("submitted", "closed") or created_by != actor_id or stored_bobbin != bobbin_id or stored_area != QUALITY_AREA
            or stored_form_code != form_code or stored_device_key != device_key):
        return False
    try:
        incoming = cs.validate_values(cs.load_fields(connection, form_version_id), values)
    except (CaptureValidationError, UnsupportedFormDefinitionError):
        return False
    return incoming == cs._stored_values(connection, capture_id)


def _insert_capture(connection, *, capture_id, form_version_id, context: _BobbinContext, device_id):
    # captured_at = instante real del ensayo; máquina/turno/fecha operativa/asignación = los de la Bobina (F3 histórica).
    connection.execute(
        """INSERT INTO vinto_txn.capture (id, form_version_id, machine_id, shift_schedule_id, device_id, assignment_id, operating_date, captured_at, status, bobbin_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,clock_timestamp(),'draft',%s)""",
        (capture_id, form_version_id, context.machine_id, context.shift_schedule_id, device_id, context.assignment_id, context.operating_date, context.bobbin_id))


def submit_quality_capture(connection, *, actor_id, bobbin_id, capture_id, form_code, device_key, values, request_id=None, sectors) -> QualityCaptureResult:
    """Crea y envía una captura de Calidad de una Bobina, de forma atómica e idempotente (capture.id = capture_id del cliente)."""
    bobbin_id = cs._uuid(bobbin_id, BobbinNotFoundError)
    capture_id = cs._uuid(capture_id, CaptureValidationError)
    device_key = str(cs._uuid(device_key, CaptureValidationError))
    if not isinstance(form_code, str) or not form_code.strip():
        raise CaptureValidationError("form_code es obligatorio")
    if not _allowed(form_code):
        raise UnsupportedFormError()  # política positiva (INT-01A): un formulario publicado NO se acepta por el solo hecho de existir; vale también para reintentos con un capture_id ya usado
    request_id = request_id or f"quality-capture:{uuid.uuid4()}"
    with connection.transaction():
        cs._lock(connection, f"vinto-capture-id:{capture_id}")  # misma clave que F6/F3: un capture_id es único entre todas las capturas
        _context(connection, actor_id, request_id)
        existing = connection.execute(
            """SELECT c.id, c.status, c.created_by, c.bobbin_id, c.form_version_id, f.code, fv.area, d.external_key
               FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id
               JOIN vinto_master.device d ON d.id = c.device_id WHERE c.id = %s""", (capture_id,)).fetchone()
        if existing is not None:
            if _existing_matches(connection, existing, actor_id=actor_id, bobbin_id=bobbin_id, form_code=form_code, device_key=device_key, values=values):
                return QualityCaptureResult(get_quality_capture(connection, capture_id, sectors=sectors), created=False, already_submitted=True)
            raise CaptureIdempotencyConflictError()

        context = _bobbin_context(connection, bobbin_id, sectors)
        device_id = cs._resolve_device(connection, device_key, context.machine_id)
        form_version_id = cs.published_form_version(connection, form_code, context.machine_id, area=QUALITY_AREA)
        fields = cs.load_fields(connection, form_version_id)  # solo campos manuales sin grupo; lo demás -> UNSUPPORTED_FORM_DEFINITION
        clean = cs.validate_values(fields, values)
        _check_declared_bobbin(connection, form_code, bobbin_id, clean)

        _insert_capture(connection, capture_id=capture_id, form_version_id=form_version_id, context=context, device_id=device_id)
        cs._insert_details(connection, capture_id, form_version_id, fields, clean)
        connection.execute("UPDATE vinto_txn.capture SET status = 'submitted', submitted_at = clock_timestamp() WHERE id = %s", (capture_id,))
    return QualityCaptureResult(get_quality_capture(connection, capture_id, sectors=sectors), created=True, already_submitted=False)

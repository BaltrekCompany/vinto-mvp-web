"""Resolvedor de turno y fecha operativa. El backend es la autoridad.

Dado un instante con zona horaria (`captured_at`) y un sector, devuelve el `shift_schedule` que
corresponde y la fecha operativa. Implementado desde cero con `datetime` aware y `zoneinfo`: no depende
de la zona horaria del sistema operativo (a diferencia de `ctx()` del frontend, que mezcla `getHours()`
local con `toISOString()` UTC).

Algoritmo, para cada schedule del sector:
1. Convertir `captured_at` a la zona del propio schedule (`shift_schedule.timezone`).
2. Intervalo semiabierto [starts_at, ends_at):
   - starts_at < ends_at: coincide si starts_at <= hora_local < ends_at; fecha operativa = fecha local.
   - starts_at > ends_at (cruza medianoche): coincide si hora_local >= starts_at (fecha operativa = fecha local)
     o si hora_local < ends_at (fecha operativa = fecha local - 1 día).
3. La vigencia se evalúa contra la FECHA OPERATIVA (no contra la fecha calendario de la captura):
   valid_from <= fecha_operativa y (valid_to IS NULL o fecha_operativa <= valid_to).
Solo participan turnos activos (vinto_config.shift.active = true): un turno inactivo no resuelve capturas
aunque su schedule coincida por hora y vigencia.
Debe quedar exactamente un schedule: 0 -> SHIFT_NOT_CONFIGURED, más de uno -> SHIFT_AMBIGUOUS.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SHIFT_NOT_CONFIGURED = "SHIFT_NOT_CONFIGURED"
SHIFT_AMBIGUOUS = "SHIFT_AMBIGUOUS"
SHIFT_INVALID_TIMEZONE = "SHIFT_INVALID_TIMEZONE"
SHIFT_INVALID_SCHEDULE = "SHIFT_INVALID_SCHEDULE"
SHIFT_INVALID_CAPTURED_AT = "SHIFT_INVALID_CAPTURED_AT"
SHIFT_SECTOR_NOT_FOUND = "SHIFT_SECTOR_NOT_FOUND"


class ShiftResolutionError(Exception):
    """Error de resolución con un código estable (`code`) que los endpoints futuros podrán mapear."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ScheduleRow:
    shift_schedule_id: object
    shift_id: object
    shift_code: str
    shift_name: str
    starts_at: time
    ends_at: time
    timezone: str
    valid_from: date
    valid_to: date | None


@dataclass(frozen=True)
class ResolvedShift:
    shift_schedule_id: object
    shift_id: object
    shift_code: str
    shift_name: str
    operating_date: date
    local_captured_at: datetime  # en la zona del schedule resuelto


def _require_aware(captured_at) -> None:
    if not isinstance(captured_at, datetime):
        raise ShiftResolutionError(SHIFT_INVALID_CAPTURED_AT, "captured_at debe ser un datetime")
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ShiftResolutionError(SHIFT_INVALID_CAPTURED_AT, "captured_at debe incluir zona horaria (datetime aware)")


def _zone(schedule: ScheduleRow) -> ZoneInfo:
    try:
        return ZoneInfo(schedule.timezone)
    except (ZoneInfoNotFoundError, ValueError, KeyError, OSError):
        raise ShiftResolutionError(
            SHIFT_INVALID_TIMEZONE,
            f"el schedule {schedule.shift_code} tiene una zona horaria inválida: {schedule.timezone!r}") from None


def _operating_date(schedule: ScheduleRow, local: datetime) -> date | None:
    """Fecha operativa si `local` cae dentro del intervalo [starts_at, ends_at); None si no."""
    start, end, moment = schedule.starts_at, schedule.ends_at, local.time()
    if start == end:
        raise ShiftResolutionError(SHIFT_INVALID_SCHEDULE, f"el schedule {schedule.shift_code} tiene inicio y fin iguales")
    if start < end:
        return local.date() if start <= moment < end else None
    if moment >= start:
        return local.date()
    if moment < end:
        return local.date() - timedelta(days=1)
    return None


def resolve_shift_from_schedules(schedules, captured_at: datetime) -> ResolvedShift:
    """Cálculo puro (sin base de datos) sobre los schedules de un sector."""
    _require_aware(captured_at)
    matches = []
    for schedule in schedules:
        local = captured_at.astimezone(_zone(schedule))
        operating = _operating_date(schedule, local)
        if operating is None:
            continue
        if operating < schedule.valid_from or (schedule.valid_to is not None and operating > schedule.valid_to):
            continue
        matches.append((schedule, operating, local))
    if not matches:
        raise ShiftResolutionError(SHIFT_NOT_CONFIGURED, f"ningún turno configurado cubre {captured_at.isoformat()}")
    if len(matches) > 1:
        codes = ", ".join(sorted(f"{s.shift_code}({s.shift_schedule_id})" for s, _, _ in matches))
        raise ShiftResolutionError(SHIFT_AMBIGUOUS, f"{len(matches)} turnos cubren {captured_at.isoformat()}: {codes}")
    schedule, operating, local = matches[0]
    return ResolvedShift(schedule.shift_schedule_id, schedule.shift_id, schedule.shift_code, schedule.shift_name, operating, local)


def load_schedules(connection, *, sector_id=None, sector_code: str | None = None) -> list[ScheduleRow]:
    """shift_schedule de turnos ACTIVOS del sector (sin filtrar por fecha: la vigencia depende de la fecha operativa)."""
    if (sector_id is None) == (sector_code is None):
        raise ValueError("Indicar exactamente uno: sector_id o sector_code")
    if sector_code is not None:
        row = connection.execute("SELECT id FROM vinto_master.sector WHERE code=%s", (sector_code,)).fetchone()
    else:
        row = connection.execute("SELECT id FROM vinto_master.sector WHERE id=%s", (sector_id,)).fetchone()
    if row is None:
        raise ShiftResolutionError(SHIFT_SECTOR_NOT_FOUND, f"el sector {sector_code or sector_id} no existe")
    rows = connection.execute(
        """SELECT sc.id, sc.shift_id, sh.code, sh.name, sc.starts_at, sc.ends_at, sc.timezone, sc.valid_from, sc.valid_to
           FROM vinto_config.shift_schedule sc JOIN vinto_config.shift sh ON sh.id = sc.shift_id
           WHERE sc.sector_id = %s AND sh.active ORDER BY sh.code, sc.valid_from""", (row[0],)).fetchall()
    return [ScheduleRow(*r) for r in rows]


def resolve_shift(connection, captured_at: datetime, *, sector_id=None, sector_code: str | None = None) -> ResolvedShift:
    """Resuelve turno y fecha operativa contra shift_schedule. Solo lee de la base de datos."""
    _require_aware(captured_at)  # falla antes de consultar
    return resolve_shift_from_schedules(load_schedules(connection, sector_id=sector_id, sector_code=sector_code), captured_at)

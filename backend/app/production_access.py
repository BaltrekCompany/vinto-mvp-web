"""Disponibilidad de producción (M4-A), SOLO LECTURA: qué máquinas y formularios centrales puede operar la sesión.

`GET /api/production/machines` responde únicamente con lo que el backend VERIFICA en PostgreSQL y con la configuración real:
  - sectores del alcance de la sesión = concedidos ∩ operativos (`scoped_sector_codes`): un sector concedido pero NO operativo no aparece (la concesión no habilita un sector);
  - máquinas activas de esos sectores;
  - por máquina, los formularios habilitados por la política central (`capture_service.CENTRAL_FORM_CODES`) cuya versión publicada más alta es de área `production`,
    está activa y está vinculada a esa máquina (la misma regla que aplica el POST de capturas), con su nombre y versión;
  - opcionalmente (`articles=true`) los artículos vinculados a cada máquina, para que la programación no dependa de listas estáticas.
No hay flags ni variables de entorno que habiliten sectores o formularios: la fuente de verdad sigue siendo app/sectors.py y la política de capture_service. No escribe nada.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import capture_service
from app.auth.dependencies import FORBIDDEN, current_user
from app.auth.permissions import ASSIGNMENT_READ, PRODUCTION_CAPTURE, WORK_ORDER_READ
from app.auth.service import AuthenticatedUser
from app.database import get_connection
from app.sectors import scoped_sector_codes

router = APIRouter(prefix="/api/production", tags=["Producción"])
VIEW_PERMISSIONS = (WORK_ORDER_READ, ASSIGNMENT_READ, PRODUCTION_CAPTURE)


class FormRef(BaseModel):
    code: str
    name: str
    version_number: int


class ArticleRef(BaseModel):
    code: str
    description: str


class MachineOut(BaseModel):
    code: str
    name: str
    forms: list[FormRef]
    articles: list[ArticleRef] | None = None


class SectorOut(BaseModel):
    code: str
    name: str
    machines: list[MachineOut]


class ProductionMachinesOut(BaseModel):
    sectors: list[SectorOut]


def any_view_permission(user: AuthenticatedUser = Depends(current_user)) -> AuthenticatedUser:
    """Sesión válida con al menos un permiso de consulta de producción (OT, asignaciones o captura); si no, 403."""
    if not any(user.can(permission) for permission in VIEW_PERMISSIONS):
        raise HTTPException(status_code=403, detail=FORBIDDEN)
    return user


def production_machines(connection, sectors, *, include_articles: bool = False) -> ProductionMachinesOut:
    scoped = list(scoped_sector_codes(sectors))
    with connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        machines = connection.execute(
            """SELECT s.code, s.name, m.id, m.code, m.name FROM vinto_master.machine m JOIN vinto_master.sector s ON s.id = m.sector_id
               WHERE m.active AND s.active AND s.code = ANY(%s) ORDER BY s.code, m.code""", (scoped,)).fetchall()
        ids = [row[2] for row in machines]
        forms: dict = {}
        if ids:
            # La versión publicada MÁS ALTA de cada formulario activo y habilitado (área production), y solo si está vinculada a la máquina: como published_form_version().
            for machine_id, code, name, version in connection.execute(
                    """WITH latest AS (SELECT DISTINCT ON (f.id) f.code, fv.id AS version_id, fv.name, fv.version_number
                                       FROM vinto_config.form f JOIN vinto_config.form_version fv ON fv.form_id = f.id
                                       WHERE f.active AND fv.status = 'published' AND fv.area = 'production' AND f.code = ANY(%s)
                                       ORDER BY f.id, fv.version_number DESC)
                       SELECT fvm.machine_id, l.code, l.name, l.version_number FROM latest l JOIN vinto_config.form_version_machine fvm ON fvm.form_version_id = l.version_id
                       WHERE fvm.machine_id = ANY(%s) ORDER BY fvm.machine_id, l.code""", (sorted(capture_service.CENTRAL_FORM_CODES), ids)).fetchall():
                forms.setdefault(machine_id, []).append(FormRef(code=code, name=name, version_number=version))
        articles: dict = {}
        if ids and include_articles:
            for machine_id, code, description in connection.execute(
                    """SELECT am.machine_id, ar.code, av.description FROM vinto_master.article_machine am JOIN vinto_master.article ar ON ar.id = am.article_id
                       JOIN LATERAL (SELECT description FROM vinto_master.article_version WHERE article_id = ar.id ORDER BY version_number DESC LIMIT 1) av ON true
                       WHERE am.machine_id = ANY(%s) ORDER BY am.machine_id, ar.code""", (ids,)).fetchall():
                articles.setdefault(machine_id, []).append(ArticleRef(code=code, description=description))
    out: dict = {}
    for sector_code, sector_name, machine_id, machine_code, machine_name in machines:
        sector = out.setdefault(sector_code, SectorOut(code=sector_code, name=sector_name, machines=[]))
        sector.machines.append(MachineOut(code=machine_code, name=machine_name, forms=forms.get(machine_id, []), articles=articles.get(machine_id, []) if include_articles else None))
    return ProductionMachinesOut(sectors=list(out.values()))


@router.get("/machines", response_model=ProductionMachinesOut, response_model_exclude_none=True,
            responses={401: {"description": "No autenticado"}, 403: {"description": "Sin permiso de consulta de producción"}, 503: {"description": "Consulta no disponible"}})
def machines(articles: bool = Query(default=False), user: AuthenticatedUser = Depends(any_view_permission), connection=Depends(get_connection)):
    """Máquinas y formularios centrales operables por la sesión (alcance verificado por el backend). Solo lectura."""
    return production_machines(connection, user.sectors, include_articles=articles)

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from app.auth.permissions import permissions_for_profiles
from app.authz import Operation, authorize

P107_FORM_CODE = "VINTO-P1-07"
REWINDING_SECTOR_CODE = "REBOBINADO"

SOURCE_MOTHERS_SQL = """
SELECT
  c.id AS mother_capture_id, mother.id AS mother_bobbin_id,
  c.revision AS source_capture_revision, c.form_version_id AS source_form_version_id,
  c.operating_date, c.created_by AS source_operator_user_id, u.display_name AS operator_display_name,
  wo.id AS work_order_id, wo.number AS work_order_number, wo.status AS work_order_status,
  wo.archived_at, wo.qa_retired, wol.id AS work_order_line_id, wol.machine_id AS line_machine_id,
  wol.pv_reference, wol.article_version_id, av.article_id, ar.code AS article_code,
  COALESCE(av.description,'') AS article_description, m.id AS machine_id, m.code AS machine_code,
  m.name AS machine_name, s.id AS sector_id, s.code AS sector_code,
  COALESCE((
    SELECT jsonb_object_agg(fd.key,jsonb_build_object(
      'type',fd.value_type,'text',d.value_text,'decimal',d.value_decimal::text,
      'integer',d.value_integer::text,'boolean',d.value_boolean,'date',d.value_date::text,
      'time',CASE WHEN d.value_time IS NULL THEN NULL ELSE to_char(d.value_time,'HH24:MI:SS') END
    ))
    FROM vinto_txn.capture_detail d
    JOIN vinto_config.field_definition fd ON fd.id=d.field_definition_id
    WHERE d.capture_id=c.id
  ),'{}'::jsonb) AS source_fields,
  cl.id AS source_work_order_classification_id
FROM vinto_txn.capture c
JOIN vinto_config.form_version fv ON fv.id=c.form_version_id
JOIN vinto_config.form f ON f.id=fv.form_id
JOIN vinto_txn.assignment a ON a.id=c.assignment_id
JOIN vinto_txn.work_order_line wol ON wol.id=a.work_order_line_id
JOIN vinto_txn.work_order_version wov ON wov.id=wol.work_order_version_id
JOIN vinto_txn.work_order wo ON wo.id=wov.work_order_id
JOIN vinto_master.machine m ON m.id=c.machine_id
JOIN vinto_master.sector s ON s.id=m.sector_id
JOIN vinto_master.article_version av ON av.id=wol.article_version_id
JOIN vinto_master.article ar ON ar.id=av.article_id
LEFT JOIN vinto_master."user" u ON u.id=c.created_by
LEFT JOIN vinto_txn.bobbin mother ON mother.rewind_mother_capture_id=c.id
JOIN LATERAL (
  SELECT x.id,x.classification FROM vinto_txn.rewinding_export_work_order_classification x
  WHERE x.work_order_id=wo.id ORDER BY x.sequence_no DESC LIMIT 1
) cl ON cl.classification='production_confirmed'
WHERE f.code='VINTO-P1-07' AND fv.version_number>=3
  AND c.status IN ('submitted','closed')
  AND wol.machine_id=c.machine_id AND a.machine_id=c.machine_id
  AND s.code='REBOBINADO' AND s.active AND m.active
  AND wo.status IN ('published','in_progress','closed')
  AND wo.archived_at IS NULL AND COALESCE(wo.qa_retired,false)=false
  AND EXISTS (
    SELECT 1 FROM vinto_txn.bobbin b
    JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id
    WHERE b.source_capture_id=c.id AND b.rewind_child_position BETWEEN 1 AND 22
      AND b.rewind_child_position<>12 AND b.weight_kg>0 AND q.status='released'
      AND NOT EXISTS (
        SELECT 1 FROM vinto_txn.rewinding_export_reservation r
        WHERE r.child_bobbin_id=b.id AND r.released_at IS NULL
      )
  )
ORDER BY wol.pv_reference,ar.code,c.operating_date,c.id
"""


def rows(connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor = connection.execute(sql, params)
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def one(connection, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    found = rows(connection, sql, params)
    return found[0] if found else None


def set_actor_context(connection, actor_id: UUID, request_id: str | None = None, reason: str | None = None) -> None:
    connection.execute(
        "SELECT set_config('vinto.actor_id',%s,true),set_config('vinto.request_id',%s,true),set_config('vinto.reason',%s,true)",
        (str(actor_id), (request_id or "")[:128], (reason or "")[:300]),
    )


def require_sector_permission(connection, user: Any, permission: str, *, lock: bool) -> UUID:
    actor_id = UUID(str(user.user_id))
    user_lock = " FOR SHARE" if lock else ""
    actor = one(connection, 'SELECT id,active FROM vinto_master."user" WHERE id=%s' + user_lock, (actor_id,))
    if not actor or not actor["active"]:
        raise HTTPException(status_code=403, detail={"code":"ACTOR_INACTIVE","message":"La cuenta no está activa."})
    profile_lock = " FOR SHARE OF up" if lock else ""
    profile_rows = rows(
        connection,
        """
        SELECT p.code FROM vinto_master.user_profile up
        JOIN vinto_master.profile p ON p.id=up.profile_id
        WHERE up.user_id=%s AND p.active ORDER BY p.code
        """ + profile_lock,
        (actor_id,),
    )
    granted = permissions_for_profiles([item["code"] for item in profile_rows])
    if permission not in granted:
        raise HTTPException(status_code=403, detail={"code":"PERMISSION_DENIED","message":"Tu usuario no tiene permiso para esta operación."})
    sector = one(connection,"SELECT id,active FROM vinto_master.sector WHERE code=%s",(REWINDING_SECTOR_CODE,))
    if not sector or not sector["active"]:
        raise HTTPException(status_code=403, detail={"code":"SECTOR_INACTIVE","message":"El sector REBOBINADO no está habilitado."})
    grant = one(connection,"SELECT 1 AS granted FROM vinto_master.user_sector WHERE user_id=%s AND sector_id=%s",(actor_id,sector["id"]))
    if not grant:
        raise HTTPException(status_code=403, detail={"code":"SECTOR_NOT_GRANTED","message":"Tu usuario no tiene concesión para REBOBINADO."})
    return sector["id"]


def _field(fields: dict[str, Any], key: str, kind: str) -> str | None:
    value = fields.get(key)
    if not isinstance(value, dict) or value.get(kind) is None:
        return None
    return str(value[kind])


def format_value(fields: dict[str, Any]) -> str | None:
    first = _field(fields,"formato_1","decimal")
    second = _field(fields,"formato_2","decimal")
    if first is None:
        return None
    return first if second is None else first + " + " + second


def mother_row_to_option(row: dict[str, Any]) -> dict[str, Any] | None:
    fields = row.get("source_fields") or {}
    label = _field(fields,"etiqueta_numero_de_bobina","text")
    destination = _field(fields,"destino","text")
    formato_1 = _field(fields,"formato_1","decimal")
    diametro = _field(fields,"diametro","decimal")
    tubete = _field(fields,"tubete","text")
    if not all((label,destination,formato_1,diametro,tubete)):
        return None
    operator_id=row.get("source_operator_user_id")
    operator_name=row.get("operator_display_name")
    return {
        "mother_capture_id":row["mother_capture_id"],"mother_bobbin_id":row.get("mother_bobbin_id"),
        "mother_label":label,"pv_reference":row["pv_reference"],"article_id":row["article_id"],
        "article_code":row["article_code"],"article_description":row.get("article_description") or "",
        "machine":{"code":row["machine_code"],"name":row["machine_name"]},
        "work_order":{"id":row["work_order_id"],"number":row["work_order_number"]},
        "operating_date":row["operating_date"],"destination":destination,
        "formato_1":formato_1,"formato_2":_field(fields,"formato_2","decimal"),
        "formato_3":_field(fields,"formato_3","decimal"),"diametro":diametro,"tubete":tubete,
        "ayudante":_field(fields,"auxiliar","text"),
        "operator":{"user_id":operator_id,"display_name":operator_name} if operator_id and operator_name else None,
    }


def source_fields_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    fields=dict(row.get("source_fields") or {})
    fields["__source"]={
        "operating_date":row["operating_date"].isoformat() if isinstance(row["operating_date"],date) else str(row["operating_date"]),
        "pv_reference":row["pv_reference"],"mother_capture_id":str(row["mother_capture_id"]),
        "mother_bobbin_id":str(row["mother_bobbin_id"]) if row.get("mother_bobbin_id") else None,
        "source_capture_revision":row["source_capture_revision"],"source_form_version_id":str(row["source_form_version_id"]),
        "work_order_id":str(row["work_order_id"]),"work_order_line_id":str(row["work_order_line_id"]),
        "article_version_id":str(row["article_version_id"]),"article_id":str(row["article_id"]),
        "article_code":row["article_code"],"article_description":row.get("article_description") or "",
        "machine_id":str(row["machine_id"]),"machine_code":row["machine_code"],"machine_name":row["machine_name"],
        "sector_id":str(row["sector_id"]),"work_order_number":row["work_order_number"],
        "source_operator_user_id":str(row["source_operator_user_id"]) if row.get("source_operator_user_id") else None,
        "operator_display_name":row.get("operator_display_name"),"mother_label":_field(fields,"etiqueta_numero_de_bobina","text"),
        "source_work_order_classification_id":str(row["source_work_order_classification_id"]),
    }
    return fields


def event(connection, report_id: UUID, event_type: str, actor_id: UUID, *, reason: str | None = None, metadata: dict[str, Any] | None = None) -> None:
    from psycopg.types.json import Jsonb
    connection.execute(
        "INSERT INTO vinto_txn.rewinding_export_report_event(report_id,event_type,actor_id,reason,metadata) VALUES (%s,%s,%s,%s,%s)",
        (report_id,event_type,actor_id,reason,Jsonb(metadata or {})),
    )


def visible_mother_rows(connection, user: Any, *, pv_reference: str | None = None, article_id: UUID | None = None) -> list[dict[str, Any]]:
    candidates=rows(connection,SOURCE_MOTHERS_SQL)
    visible=[]
    decisions={}
    for row in candidates:
        if pv_reference is not None and row["pv_reference"]!=pv_reference: continue
        if article_id is not None and row["article_id"]!=article_id: continue
        if mother_row_to_option(row) is None: continue
        code=row["machine_code"]
        if code not in decisions:
            decision=authorize(connection,user,Operation.REWINDING_EXPORT_CREATE,code,P107_FORM_CODE,lock=False)
            decisions[code]=bool(decision.allowed)
        if decisions[code]: visible.append(row)
    return visible


def load_draft(connection, actor_id: UUID, report_id: UUID) -> dict[str, Any]:
    from collections import defaultdict
    report=one(
        connection,
        """
        SELECT r.id,r.status,r.created_at,r.pv_reference,r.article_id,r.truck_number,r.order_number,r.observations,
               a.code AS article_code
        FROM vinto_txn.rewinding_export_report r JOIN vinto_master.article a ON a.id=r.article_id
        WHERE r.id=%s AND r.created_by=%s
        """,
        (report_id,actor_id),
    )
    if not report or report["status"]!="draft":
        raise HTTPException(status_code=404,detail={"code":"DRAFT_NOT_FOUND","message":"No se encontró el borrador solicitado."})
    package_rows=rows(connection,"SELECT p.* FROM vinto_txn.rewinding_export_package p WHERE p.report_id=%s AND p.removed_at IS NULL ORDER BY p.package_number,p.id",(report_id,))
    child_rows=rows(
        connection,
        """
        SELECT c.package_id,c.child_bobbin_id,c.package_slot,c.source_position,c.weight_kg_snapshot
        FROM vinto_txn.rewinding_export_package_child c
        JOIN vinto_txn.rewinding_export_package p ON p.id=c.package_id
        WHERE c.report_id=%s AND c.removed_at IS NULL AND p.removed_at IS NULL
        ORDER BY c.package_id,c.package_slot
        """,
        (report_id,),
    )
    grouped:dict[UUID,list[dict[str,Any]]]=defaultdict(list)
    for child in child_rows:
        grouped[child["package_id"]].append({"bobbin_id":child["child_bobbin_id"],"package_slot":child["package_slot"],"position":child["source_position"],"weight_kg":str(child["weight_kg_snapshot"])})
    packages=[]
    descriptions={p["article_description_snapshot"] for p in package_rows}
    for p in package_rows:
        fields=p["source_fields_snapshot"] or {}
        source=fields.get("__source") or {}
        def raw(key:str,kind:str)->str|None:
            value=fields.get(key)
            return str(value[kind]) if isinstance(value,dict) and value.get(kind) is not None else None
        operator_id=p.get("source_operator_user_id")
        operator_name=p.get("operator_display_name_snapshot")
        mother={
            "mother_capture_id":p["mother_capture_id"],"mother_bobbin_id":p["mother_bobbin_id"],
            "mother_label":p["mother_label_snapshot"],"pv_reference":source.get("pv_reference",report["pv_reference"]),
            "article_id":report["article_id"],"article_code":p["article_code_snapshot"],
            "article_description":p["article_description_snapshot"],
            "machine":{"code":p["machine_code_snapshot"],"name":p["machine_name_snapshot"]},
            "work_order":{"id":p["work_order_id"],"number":p["work_order_number_snapshot"]},
            "operating_date":date.fromisoformat(source["operating_date"]),
            "destination":raw("destino","text") or "","formato_1":raw("formato_1","decimal") or "",
            "formato_2":raw("formato_2","decimal"),"formato_3":raw("formato_3","decimal"),
            "diametro":raw("diametro","decimal") or "","tubete":raw("tubete","text") or "",
            "ayudante":raw("auxiliar","text"),
            "operator":{"user_id":operator_id,"display_name":operator_name} if operator_id and operator_name else None,
        }
        packages.append({"id":p["id"],"package_number":p["package_number"],"mother_capture_id":p["mother_capture_id"],
                         "mother_label_snapshot":p["mother_label_snapshot"],"mother":mother,"children":grouped.get(p["id"],[])})
    description=next(iter(descriptions)) if len(descriptions)==1 else ""
    if not package_rows:
        versions=rows(connection,"SELECT DISTINCT description FROM vinto_master.article_version WHERE article_id=%s",(report["article_id"],))
        values={item["description"] or "" for item in versions}
        description=next(iter(values)) if len(values)==1 else ""
    return {"id":report["id"],"status":"draft","created_at":report["created_at"],"pv_reference":report["pv_reference"],
            "article":{"id":report["article_id"],"code":report["article_code"],"description":description},
            "truck_number":report["truck_number"],"order_number":report["order_number"],"observations":report["observations"],"packages":packages}

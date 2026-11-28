from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from psycopg import errors
from psycopg.types.json import Jsonb

from app.auth.permissions import Permission
from app.authz import Operation, require

from .repository import (
    P107_FORM_CODE, SOURCE_MOTHERS_SQL, _field, event, format_value,
    load_draft, mother_row_to_option, one, require_sector_permission,
    rows, set_actor_context, source_fields_snapshot, visible_mother_rows,
)


def _actor(user: Any) -> UUID:
    return UUID(str(user.user_id))


def _http(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _require_create_sector(connection, user: Any, *, lock: bool) -> UUID:
    return require_sector_permission(connection, user, Permission.REWINDING_EXPORT_CREATE, lock=lock)


def _require_read_own(connection, user: Any) -> UUID:
    return require_sector_permission(connection, user, Permission.REWINDING_EXPORT_READ_OWN, lock=False)


def _mother_row(connection, user: Any, mother_capture_id: UUID) -> dict[str, Any]:
    candidates = visible_mother_rows(connection, user)
    row = next((item for item in candidates if item["mother_capture_id"] == mother_capture_id), None)
    if row is None:
        raise _http(404, "MOTHER_NOT_ELIGIBLE", "La bobina madre no está disponible para este reporte.")
    return row


def _require_machine(connection, user: Any, row: dict[str, Any], *, lock: bool) -> None:
    require(connection, user, Operation.REWINDING_EXPORT_CREATE, row["machine_code"], P107_FORM_CODE, lock=lock)


def list_pvs(connection, user: Any) -> list[dict[str, Any]]:
    counts: dict[str, set[UUID]] = defaultdict(set)
    for row in visible_mother_rows(connection, user):
        counts[row["pv_reference"]].add(row["mother_capture_id"])
    return [{"pv_reference": pv, "eligible_mothers": len(ids)} for pv, ids in sorted(counts.items())]


def list_products(connection, user: Any, pv_reference: str) -> list[dict[str, Any]]:
    grouped: dict[UUID, dict[str, Any]] = {}
    descriptions: dict[UUID, set[str]] = defaultdict(set)
    for row in visible_mother_rows(connection, user, pv_reference=pv_reference):
        article_id = row["article_id"]
        grouped[article_id] = {"article_id": article_id, "code": row["article_code"], "description": ""}
        descriptions[article_id].add(row.get("article_description") or "")
    for article_id, item in grouped.items():
        variants = descriptions[article_id]
        item["description"] = next(iter(variants)) if len(variants) == 1 else ""
    return sorted(grouped.values(), key=lambda item: item["code"])


def list_mothers(connection, user: Any, pv_reference: str, article_id: UUID) -> list[dict[str, Any]]:
    result = []
    for row in visible_mother_rows(connection, user, pv_reference=pv_reference, article_id=article_id):
        option = mother_row_to_option(row)
        if option is not None:
            result.append(option)
    return result


def list_children(connection, user: Any, mother_capture_id: UUID) -> list[dict[str, Any]]:
    mother = _mother_row(connection, user, mother_capture_id)
    _require_machine(connection, user, mother, lock=False)
    return rows(
        connection,
        """
        SELECT b.id AS bobbin_id,b.source_capture_id AS mother_capture_id,
               b.rewind_child_position AS position,b.weight_kg::text AS weight_kg,
               q.status AS quality_status
        FROM vinto_txn.bobbin b
        JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id
        WHERE b.source_capture_id=%s
          AND b.rewind_child_position BETWEEN 1 AND 22 AND b.rewind_child_position<>12
          AND b.weight_kg>0 AND q.status='released'
          AND NOT EXISTS (
            SELECT 1 FROM vinto_txn.rewinding_export_child_reservation r
            WHERE r.child_bobbin_id=b.id AND r.released_at IS NULL
          )
        ORDER BY b.rewind_child_position,b.id
        """,
        (mother_capture_id,),
    )


def list_drafts(connection, user: Any) -> list[dict[str, Any]]:
    actor = _require_read_own(connection, user)
    return rows(
        connection,
        """
        SELECT r.id,r.created_at,r.pv_reference,a.code AS article_code,
          (SELECT p.machine_code_snapshot FROM vinto_txn.rewinding_export_package p
           WHERE p.report_id=r.id AND p.removed_at IS NULL ORDER BY p.package_number LIMIT 1) AS machine_code,
          (SELECT count(*)::integer FROM vinto_txn.rewinding_export_package p
           WHERE p.report_id=r.id AND p.removed_at IS NULL) AS package_count
        FROM vinto_txn.rewinding_export_report r
        JOIN vinto_master.article a ON a.id=r.article_id
        WHERE r.created_by=%s AND r.status='draft'
        ORDER BY r.created_at DESC,r.id
        """,
        (actor,),
    )


def get_draft(connection, user: Any, report_id: UUID) -> dict[str, Any]:
    return load_draft(connection, _require_read_own(connection, user), report_id)


def create_draft(connection, user: Any, payload: Any, *, request_id: str | None = None) -> dict[str, Any]:
    actor = _require_create_sector(connection, user, lock=True)
    with connection.transaction():
        set_actor_context(connection, actor, request_id, "RBE draft created")
        if not visible_mother_rows(connection, user, pv_reference=payload.pv_reference, article_id=payload.article_id):
            raise _http(422, "NO_ELIGIBLE_MOTHER", "No hay madres elegibles para el PV y producto seleccionados.")
        report_id = connection.execute(
            """
            INSERT INTO vinto_txn.rewinding_export_report
              (pv_reference,article_id,truck_number,order_number,observations,created_by)
            VALUES (%s,%s,%s,%s,%s,%s) RETURNING id
            """,
            (payload.pv_reference,payload.article_id,payload.truck_number.strip(),
             payload.order_number.strip(),payload.observations,actor),
        ).fetchone()[0]
        event(connection, report_id, "draft_created", actor,
              metadata={"pv_reference":payload.pv_reference,"article_id":str(payload.article_id)})
    return load_draft(connection, actor, report_id)


def update_draft_header(connection, user: Any, report_id: UUID, payload: Any, *, request_id: str | None = None) -> dict[str, Any]:
    actor = _require_create_sector(connection, user, lock=True)
    with connection.transaction():
        set_actor_context(connection, actor, request_id, "RBE draft header updated")
        report = one(connection,"SELECT id,status,created_by FROM vinto_txn.rewinding_export_report WHERE id=%s FOR UPDATE",(report_id,))
        if not report or report["created_by"] != actor:
            raise _http(404,"DRAFT_NOT_FOUND","No se encontró el borrador solicitado.")
        if report["status"] != "draft":
            raise _http(409,"REPORT_NOT_DRAFT","Solo se puede editar un borrador.")
        connection.execute(
            """
            UPDATE vinto_txn.rewinding_export_report
            SET truck_number=%s,order_number=%s,observations=%s,updated_by=%s WHERE id=%s
            """,
            (payload.truck_number.strip(),payload.order_number.strip(),payload.observations,actor,report_id),
        )
        event(connection,report_id,"draft_header_updated",actor)
    return load_draft(connection,actor,report_id)


def _selected_children(connection, mother_capture_id: UUID, selections: list[Any]) -> list[dict[str, Any]]:
    ids=[item.child_bobbin_id for item in selections]
    if len(ids)!=len(set(ids)):
        raise _http(422,"DUPLICATE_CHILD","No puedes repetir una cría dentro del mismo paquete.")
    found=rows(
        connection,
        """
        SELECT b.id AS bobbin_id,b.source_capture_id AS mother_capture_id,
               b.rewind_child_position AS position,b.weight_kg,q.status AS quality_status,
               EXISTS (SELECT 1 FROM vinto_txn.rewinding_export_child_reservation r
                       WHERE r.child_bobbin_id=b.id AND r.released_at IS NULL) AS reserved
        FROM vinto_txn.bobbin b LEFT JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id
        WHERE b.id=ANY(%s::uuid[])
        """,
        (ids,),
    )
    by_id={item["bobbin_id"]:item for item in found}
    if len(by_id)!=len(ids):
        raise _http(409,"CHILD_UNAVAILABLE","Una o más crías ya no existen o no están disponibles.")
    ordered=[]
    for selection in selections:
        child=by_id[selection.child_bobbin_id]
        if child["mother_capture_id"]!=mother_capture_id:
            raise _http(422,"CHILD_WRONG_MOTHER","Una cría no pertenece a la bobina madre seleccionada.")
        if child["quality_status"]!="released" or child["reserved"]:
            raise _http(409,"CHILD_NOT_AVAILABLE","Una cría dejó de estar liberada o ya está reservada.")
        if child["position"] is None or child["position"]==12 or not 1<=child["position"]<=22:
            raise _http(422,"CHILD_POSITION_INVALID","La posición de una cría no es válida.")
        if child["weight_kg"] is None or child["weight_kg"]<=0:
            raise _http(422,"CHILD_WEIGHT_INVALID","El peso de una cría no es válido.")
        ordered.append({"bobbin_id":child["bobbin_id"],"package_slot":selection.package_slot,
                        "position":child["position"],"weight_kg":child["weight_kg"]})
    if not any(item["package_slot"]=="A" for item in ordered):
        raise _http(422,"CHILD_A_REQUIRED","La Cría A es obligatoria.")
    return ordered


def _insert_package(connection, report_id: UUID, actor: UUID, mother: dict[str, Any], selections: list[Any]) -> UUID:
    selected=_selected_children(connection,mother["mother_capture_id"],selections)
    fields=source_fields_snapshot(mother)
    label=mother_row_to_option(mother)["mother_label"]
    package_number=one(connection,"SELECT COALESCE(max(package_number),0)+1 AS next_number FROM vinto_txn.rewinding_export_package WHERE report_id=%s",(report_id,))["next_number"]
    package_id=connection.execute(
        """
        INSERT INTO vinto_txn.rewinding_export_package
          (report_id,package_number,mother_capture_id,mother_bobbin_id,mother_label_snapshot,
           source_capture_revision,source_form_version_id,work_order_id,work_order_line_id,
           source_work_order_classification_id,article_version_id,source_fields_snapshot,
           source_operator_user_id,operator_display_name_snapshot,machine_code_snapshot,machine_name_snapshot,
           work_order_number_snapshot,article_code_snapshot,article_description_snapshot,created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """,
        (report_id,package_number,mother["mother_capture_id"],mother.get("mother_bobbin_id"),label,
         mother["source_capture_revision"],mother["source_form_version_id"],mother["work_order_id"],
         mother["work_order_line_id"],mother["source_work_order_classification_id"],mother["article_version_id"],
         Jsonb(fields),mother.get("source_operator_user_id"),mother.get("operator_display_name"),
         mother["machine_code"],mother["machine_name"],mother["work_order_number"],mother["article_code"],
         mother.get("article_description") or "",actor),
    ).fetchone()[0]
    for child in selected:
        connection.execute(
            """
            INSERT INTO vinto_txn.rewinding_export_package_child
              (report_id,package_id,child_bobbin_id,package_slot,source_position,weight_kg_snapshot,created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            (report_id,package_id,child["bobbin_id"],child["package_slot"],child["position"],child["weight_kg"],actor),
        )
    return package_id


def add_package(connection,user:Any,report_id:UUID,payload:Any,*,request_id:str|None=None)->dict[str,Any]:
    actor=_actor(user)
    mother=_mother_row(connection,user,payload.mother_capture_id)
    with connection.transaction():
        set_actor_context(connection,actor,request_id,"RBE package added")
        _require_machine(connection,user,mother,lock=True)
        report=one(connection,"SELECT id,status,created_by,pv_reference,article_id,machine_id,sector_id,destination_snapshot,format_snapshot FROM vinto_txn.rewinding_export_report WHERE id=%s FOR UPDATE",(report_id,))
        if not report or report["created_by"]!=actor: raise _http(404,"DRAFT_NOT_FOUND","No se encontró el borrador solicitado.")
        if report["status"]!="draft": raise _http(409,"REPORT_NOT_DRAFT","Solo se pueden agregar paquetes a un borrador.")
        if report["pv_reference"]!=mother["pv_reference"] or report["article_id"]!=mother["article_id"]:
            raise _http(422,"REPORT_CONTEXT_MISMATCH","La madre no pertenece al PV y producto del reporte.")
        destination=mother_row_to_option(mother)["destination"]
        format_snapshot=format_value(mother["source_fields"])
        if report["machine_id"] is not None and report["machine_id"]!=mother["machine_id"]:
            raise _http(422,"REPORT_CONTEXT_MISMATCH","No se pueden mezclar máquinas en un mismo reporte.")
        if report["destination_snapshot"] is not None and report["destination_snapshot"].strip()!=destination.strip():
            raise _http(422,"REPORT_CONTEXT_MISMATCH","No se pueden mezclar destinos en un mismo reporte.")
        if report["format_snapshot"] is not None and report["format_snapshot"]!=format_snapshot:
            raise _http(422,"REPORT_CONTEXT_MISMATCH","No se pueden mezclar formatos en un mismo reporte.")
        existing=rows(connection,"SELECT id FROM vinto_txn.rewinding_export_package WHERE report_id=%s AND removed_at IS NULL ORDER BY package_number,id FOR UPDATE",(report_id,))
        if not existing:
            connection.execute(
                """
                UPDATE vinto_txn.rewinding_export_report
                SET machine_id=%s,sector_id=%s,destination_snapshot=%s,format_snapshot=%s,updated_by=%s
                WHERE id=%s
                """,
                (mother["machine_id"],mother["sector_id"],destination,format_snapshot,actor,report_id),
            )
        try:
            package_id=_insert_package(connection,report_id,actor,mother,payload.children)
        except errors.UniqueViolation as exc:
            raise _http(409,"CHILD_ALREADY_SELECTED","Una cría ya está seleccionada en otro paquete de este reporte.") from exc
        event(connection,report_id,"package_added",actor,metadata={"package_id":str(package_id),"mother_capture_id":str(payload.mother_capture_id)})
    return load_draft(connection,actor,report_id)


def update_package(connection,user:Any,report_id:UUID,package_id:UUID,payload:Any,*,request_id:str|None=None)->dict[str,Any]:
    actor=_actor(user)
    mother=_mother_row(connection,user,payload.mother_capture_id)
    with connection.transaction():
        set_actor_context(connection,actor,request_id,"RBE package updated")
        _require_machine(connection,user,mother,lock=True)
        report=one(connection,"SELECT id,status,created_by,pv_reference,article_id,machine_id,destination_snapshot,format_snapshot FROM vinto_txn.rewinding_export_report WHERE id=%s FOR UPDATE",(report_id,))
        if not report or report["created_by"]!=actor: raise _http(404,"DRAFT_NOT_FOUND","No se encontró el borrador solicitado.")
        if report["status"]!="draft": raise _http(409,"REPORT_NOT_DRAFT","Solo se pueden editar paquetes en Borrador.")
        package=one(connection,"SELECT id,mother_capture_id FROM vinto_txn.rewinding_export_package WHERE id=%s AND report_id=%s AND removed_at IS NULL FOR UPDATE",(package_id,report_id))
        if not package: raise _http(404,"PACKAGE_NOT_FOUND","No se encontró el paquete solicitado.")
        if package["mother_capture_id"]!=payload.mother_capture_id:
            raise _http(422,"PACKAGE_MOTHER_IMMUTABLE","Para cambiar la madre debes retirar el paquete y crear uno nuevo.")
        destination=mother_row_to_option(mother)["destination"]
        format_snapshot=format_value(mother["source_fields"])
        if report["pv_reference"]!=mother["pv_reference"] or report["article_id"]!=mother["article_id"] or report["machine_id"]!=mother["machine_id"] or report["destination_snapshot"].strip()!=destination.strip() or report["format_snapshot"]!=format_snapshot:
            raise _http(422,"REPORT_CONTEXT_MISMATCH","La madre no coincide con el PV, producto, máquina, destino o Formato del reporte.")
        connection.execute("UPDATE vinto_txn.rewinding_export_package_child SET removed_at=clock_timestamp(),removed_by=%s,updated_by=%s WHERE package_id=%s AND removed_at IS NULL",(actor,actor,package_id))
        try:
            for child in _selected_children(connection,mother["mother_capture_id"],payload.children):
                connection.execute(
                    """
                    INSERT INTO vinto_txn.rewinding_export_package_child
                      (report_id,package_id,child_bobbin_id,package_slot,source_position,weight_kg_snapshot,created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (report_id,package_id,child["bobbin_id"],child["package_slot"],child["position"],child["weight_kg"],actor),
                )
        except errors.UniqueViolation as exc:
            raise _http(409,"CHILD_ALREADY_SELECTED","Una cría ya está seleccionada en otro paquete de este reporte.") from exc
        event(connection,report_id,"package_updated",actor,metadata={"package_id":str(package_id)})
    return load_draft(connection,actor,report_id)


def remove_package(connection,user:Any,report_id:UUID,package_id:UUID,*,request_id:str|None=None)->dict[str,Any]:
    actor=_actor(user)
    source=one(connection,"SELECT mother_capture_id FROM vinto_txn.rewinding_export_package WHERE id=%s AND report_id=%s AND removed_at IS NULL",(package_id,report_id))
    if not source: raise _http(404,"PACKAGE_NOT_FOUND","No se encontró el paquete solicitado.")
    mother=_mother_row(connection,user,source["mother_capture_id"])
    with connection.transaction():
        set_actor_context(connection,actor,request_id,"RBE package removed")
        _require_machine(connection,user,mother,lock=True)
        report=one(connection,"SELECT status,created_by FROM vinto_txn.rewinding_export_report WHERE id=%s FOR UPDATE",(report_id,))
        if not report or report["created_by"]!=actor: raise _http(404,"DRAFT_NOT_FOUND","No se encontró el borrador solicitado.")
        if report["status"]!="draft": raise _http(409,"REPORT_NOT_DRAFT","Solo se pueden retirar paquetes en Borrador.")
        package=one(connection,"SELECT id FROM vinto_txn.rewinding_export_package WHERE id=%s AND report_id=%s AND removed_at IS NULL FOR UPDATE",(package_id,report_id))
        if not package: raise _http(404,"PACKAGE_NOT_FOUND","No se encontró el paquete solicitado.")
        connection.execute("UPDATE vinto_txn.rewinding_export_package_child SET removed_at=clock_timestamp(),removed_by=%s,updated_by=%s WHERE package_id=%s AND removed_at IS NULL",(actor,actor,package_id))
        connection.execute("UPDATE vinto_txn.rewinding_export_package SET removed_at=clock_timestamp(),removed_by=%s,updated_by=%s WHERE id=%s",(actor,actor,package_id))
        event(connection,report_id,"package_removed",actor,metadata={"package_id":str(package_id)})
    return load_draft(connection,actor,report_id)


def discard_draft(connection,user:Any,report_id:UUID,*,request_id:str|None=None)->dict[str,bool]:
    actor=_actor(user)
    with connection.transaction():
        set_actor_context(connection,actor,request_id,"RBE draft discarded")
        _require_create_sector(connection,user,lock=True)
        report=one(connection,"SELECT status,created_by FROM vinto_txn.rewinding_export_report WHERE id=%s FOR UPDATE",(report_id,))
        if not report or report["created_by"]!=actor: raise _http(404,"DRAFT_NOT_FOUND","No se encontró el borrador solicitado.")
        if report["status"]!="draft": raise _http(409,"REPORT_NOT_DRAFT","Solo se puede descartar un Borrador.")
        reason="Borrador descartado por su creador."
        connection.execute("UPDATE vinto_txn.rewinding_export_report SET status='discarded',discarded_by=%s,discarded_at=clock_timestamp(),discarded_reason=%s,updated_by=%s WHERE id=%s",(actor,reason,actor,report_id))
        event(connection,report_id,"draft_discarded",actor,reason=reason)
    return {"discarded":True}


def preview_draft(connection,user:Any,report_id:UUID)->dict[str,Any]:
    actor=_require_create_sector(connection,user,lock=False)
    draft=load_draft(connection,actor,report_id)
    report=one(connection,"SELECT * FROM vinto_txn.rewinding_export_report WHERE id=%s",(report_id,))
    warnings=[]; blockers=[]
    def block(code:str,message:str)->None:
        if not any(item["code"]==code and item["message"]==message for item in blockers): blockers.append({"code":code,"message":message})
    if not draft["truck_number"].strip() or not draft["order_number"].strip(): block("V02","Debes completar el número de camión y el número de orden.")
    if not draft["packages"]: block("V03","El reporte debe contener al menos un paquete.")
    all_sources={row["mother_capture_id"]:row for row in rows(connection,SOURCE_MOTHERS_SQL)}
    all_child_ids=[]
    base_context=None
    for package in draft["packages"]:
        mother=package["mother"]
        fields=one(connection,"SELECT source_fields_snapshot AS fields FROM vinto_txn.rewinding_export_package WHERE id=%s",(package["id"],))["fields"] or {}
        context=(mother["pv_reference"],mother["article_id"],mother["machine"]["code"],mother["destination"].strip(),format_value(fields))
        if base_context is None: base_context=context
        elif context!=base_context: block("V07","Las madres deben compartir PV, producto, máquina, destino y Formato; Cortes se conserva por paquete.")
        source=all_sources.get(package["mother_capture_id"])
        if source is None:
            block("V05",f"La OT o la madre del paquete {package['package_number']} dejó de ser elegible.")
            continue
        _require_machine(connection,user,source,lock=False)
        if not source.get("source_operator_user_id") or not source.get("operator_display_name"):
            block("V06",f"No se puede resolver el operador original del paquete {package['package_number']}.")
        if not package["children"] or not any(child["package_slot"]=="A" for child in package["children"]):
            block("V03",f"El paquete {package['package_number']} no tiene Cría A.")
        for child in package["children"]:
            all_child_ids.append(child["bobbin_id"])
            current=one(connection,
                """
                SELECT b.source_capture_id,b.rewind_child_position,b.weight_kg,q.status,
                  EXISTS (SELECT 1 FROM vinto_txn.rewinding_export_child_reservation r WHERE r.child_bobbin_id=b.id AND r.released_at IS NULL) AS reserved
                FROM vinto_txn.bobbin b LEFT JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id WHERE b.id=%s
                """,(child["bobbin_id"],))
            if not current or current["status"]!="released" or current["reserved"]:
                block("V05",f"La cría {child['position']} del paquete {package['package_number']} no está liberada o disponible.")
            elif current["source_capture_id"]!=package["mother_capture_id"]:
                block("V06",f"La cría {child['position']} no pertenece a su madre de origen.")
            elif current["rewind_child_position"]!=child["position"] or str(current["weight_kg"])!=str(child["weight_kg"]):
                block("V08",f"La posición o el peso de la cría {child['position']} cambió después de seleccionarla.")
        start=_field(fields,"hora_inicio","time"); end=_field(fields,"hora_fin","time")
        if start and end and end<start:
            warnings.append({"code":"SOURCE_TIME_INVERTED","message":f"El horario de origen de la madre {mother['mother_label']} está invertido."})
        mother_weight=_field(fields,"peso","decimal")
        if mother_weight:
            try:
                total=sum((Decimal(str(child["weight_kg"])) for child in package["children"]),Decimal(0))
                if total>Decimal(mother_weight):
                    warnings.append({"code":"CHILD_WEIGHT_SUM_EXCEEDS_MOTHER","message":f"El peso conjunto de las crías supera el peso de la madre {mother['mother_label']}."})
            except InvalidOperation: pass
        cuts=_field(fields,"formato_3","decimal")
        if cuts is not None:
            try:
                if Decimal(cuts)!=Decimal(len(package["children"])):
                    warnings.append({"code":"CUTS_CHILD_COUNT_MISMATCH","message":f"El valor Cortes de la madre {mother['mother_label']} difiere de la cantidad de crías."})
            except InvalidOperation: pass
        optional=("formato_2","formato_3","producto_refilado","auxiliar")
        if any(_field(fields,key,"decimal" if key.startswith("formato_") else "text") is None for key in optional):
            warnings.append({"code":"SOURCE_OPTIONAL_FIELD_MISSING","message":f"La captura de la madre {mother['mother_label']} no contiene todos los campos opcionales."})
    if len(all_child_ids)!=len(set(all_child_ids)): block("V04","Una cría está repetida en más de un paquete del reporte.")
    warnings=list({(item["code"],item["message"]):item for item in warnings}.values())
    return {"valid":not blockers,"package_count":len(draft["packages"]),"child_count":len(all_child_ids),"warnings":warnings,"blocking_errors":blockers}

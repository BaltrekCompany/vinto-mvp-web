from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Callable
from uuid import UUID

from fastapi import HTTPException
from app.auth.permissions import Permission
from app.authz import Operation, require

from .repository import (
    SOURCE_MOTHERS_SQL, event, one, require_sector_permission, rows,
    set_actor_context, visible_mother_rows, format_value,
)


def _actor(user: Any) -> UUID:
    return UUID(str(user.user_id))


def _http(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code":code,"message":message})


def list_work_orders_for_classification(connection,user:Any)->list[dict[str,Any]]:
    require_sector_permission(connection,user,Permission.REWINDING_EXPORT_CLASSIFY_SOURCE,lock=False)
    return rows(
        connection,
        """
        SELECT wo.id,wo.number,wo.status,m.code AS machine_code
        FROM vinto_txn.work_order wo
        JOIN vinto_master.machine m ON m.id=wo.machine_id
        JOIN vinto_master.sector s ON s.id=m.sector_id
        WHERE s.code='REBOBINADO' AND s.active
          AND wo.status IN ('published','in_progress','closed')
          AND wo.archived_at IS NULL AND COALESCE(wo.qa_retired,false)=false
        ORDER BY wo.number,wo.id
        """,
    )


def get_work_order_classification(connection,user:Any,work_order_id:UUID)->dict[str,Any]:
    require_sector_permission(connection,user,Permission.REWINDING_EXPORT_CLASSIFY_SOURCE,lock=False)
    wo=one(
        connection,
        """
        SELECT wo.id FROM vinto_txn.work_order wo
        JOIN vinto_master.machine m ON m.id=wo.machine_id
        JOIN vinto_master.sector s ON s.id=m.sector_id
        WHERE wo.id=%s AND s.code='REBOBINADO' AND s.active
        """,
        (work_order_id,),
    )
    if not wo: raise _http(404,"WORK_ORDER_NOT_FOUND","No se encontró la OT en REBOBINADO.")
    latest=one(
        connection,
        """
        SELECT c.work_order_id,c.classification,c.sequence_no,c.recorded_at,c.reason,c.recorded_by,u.display_name
        FROM vinto_txn.rewinding_export_work_order_classification c
        JOIN vinto_master."user" u ON u.id=c.recorded_by
        WHERE c.work_order_id=%s ORDER BY c.sequence_no DESC LIMIT 1
        """,
        (work_order_id,),
    )
    if not latest:
        return {"work_order_id":work_order_id,"classification":None,"sequence_no":None,"recorded_at":None,"reason":None,"recorded_by":None}
    return {
        "work_order_id":latest["work_order_id"],"classification":latest["classification"],
        "sequence_no":latest["sequence_no"],"recorded_at":latest["recorded_at"],"reason":latest["reason"],
        "recorded_by":{"id":latest["recorded_by"],"display_name":latest["display_name"]},
    }


def classify_work_order(connection,user:Any,work_order_id:UUID,payload:Any,*,request_id:str|None=None)->dict[str,Any]:
    actor=_actor(user)
    with connection.transaction():
        set_actor_context(connection,actor,request_id,payload.reason)
        require_sector_permission(connection,user,Permission.REWINDING_EXPORT_CLASSIFY_SOURCE,lock=True)
        wo=one(
            connection,
            """
            SELECT wo.id,wo.status,wo.archived_at,wo.qa_retired
            FROM vinto_txn.work_order wo
            JOIN vinto_master.machine m ON m.id=wo.machine_id
            JOIN vinto_master.sector s ON s.id=m.sector_id
            WHERE wo.id=%s AND s.code='REBOBINADO' AND s.active
            FOR UPDATE OF wo
            """,
            (work_order_id,),
        )
        if not wo or wo["status"] not in {"published","in_progress","closed"} or wo["archived_at"] is not None or wo["qa_retired"]:
            raise _http(409,"WORK_ORDER_NOT_CLASSIFIABLE","La OT está archivada, retirada como QA o fuera del alcance REBOBINADO.")
        latest=one(connection,"SELECT id,sequence_no,classification FROM vinto_txn.rewinding_export_work_order_classification WHERE work_order_id=%s ORDER BY sequence_no DESC LIMIT 1",(work_order_id,))
        if latest and latest["classification"]==payload.classification:
            raise _http(409,"CLASSIFICATION_UNCHANGED","La OT ya tiene esa clasificación; no se registró un duplicado.")
        if payload.classification=="qa" and one(
            connection,
            """
            SELECT 1 AS found FROM vinto_txn.rewinding_export_package p
            JOIN vinto_txn.rewinding_export_report r ON r.id=p.report_id
            WHERE p.work_order_id=%s AND p.removed_at IS NULL AND r.status IN ('generated','observed') LIMIT 1
            """,
            (work_order_id,),
        ):
            raise _http(409,"GENERATED_REPORT_EXISTS","Primero deben anularse los reportes RBE generados u observados para esta OT.")
        record=connection.execute(
            """
            INSERT INTO vinto_txn.rewinding_export_work_order_classification
              (work_order_id,sequence_no,classification,recorded_by,reason,supersedes_id)
            VALUES (%s,%s,%s,%s,%s,%s)
            RETURNING work_order_id,classification,sequence_no,recorded_at,reason,recorded_by
            """,
            (work_order_id,(latest["sequence_no"] if latest else 0)+1,payload.classification,actor,payload.reason.strip(),latest["id"] if latest else None),
        ).fetchone()
        display=one(connection,'SELECT display_name FROM vinto_master."user" WHERE id=%s',(actor,))
    return {
        "work_order_id":record[0],"classification":record[1],"sequence_no":record[2],
        "recorded_at":record[3],"reason":record[4],
        "recorded_by":{"id":record[5],"display_name":display["display_name"] if display else ""},
    }


def annul_report(connection,user:Any,report_id:UUID,reason:str,*,request_id:str|None=None)->dict[str,Any]:
    actor=_actor(user)
    preliminary=one(connection,"SELECT id,status FROM vinto_txn.rewinding_export_report WHERE id=%s",(report_id,))
    if not preliminary: raise _http(404,"REPORT_NOT_FOUND","No se encontró el reporte.")
    if preliminary["status"] not in {"generated","observed"}:
        raise _http(409,"REPORT_NOT_ANNULABLE","Solo se pueden anular reportes generados u observados.")
    work_orders=[x["work_order_id"] for x in rows(connection,"SELECT DISTINCT work_order_id FROM vinto_txn.rewinding_export_package WHERE report_id=%s ORDER BY work_order_id",(report_id,))]
    child_ids=[x["child_bobbin_id"] for x in rows(connection,"SELECT child_bobbin_id FROM vinto_txn.rewinding_export_package_child WHERE report_id=%s ORDER BY child_bobbin_id",(report_id,))]
    mothers=[x["mother_capture_id"] for x in rows(connection,"SELECT DISTINCT mother_capture_id FROM vinto_txn.rewinding_export_package WHERE report_id=%s ORDER BY mother_capture_id",(report_id,))]
    with connection.transaction():
        set_actor_context(connection,actor,request_id,reason)
        require_sector_permission(connection,user,Permission.REWINDING_EXPORT_ANNUL,lock=True)
        if work_orders:
            connection.execute("SELECT id FROM vinto_txn.work_order WHERE id=ANY(%s::uuid[]) ORDER BY id FOR SHARE",(work_orders,)).fetchall()
        if child_ids:
            connection.execute("SELECT bobbin_id FROM vinto_txn.quality_release WHERE bobbin_id=ANY(%s::uuid[]) ORDER BY bobbin_id FOR SHARE",(child_ids,)).fetchall()
            connection.execute("SELECT id FROM vinto_txn.bobbin WHERE id=ANY(%s::uuid[]) ORDER BY id FOR SHARE",(child_ids,)).fetchall()
        if mothers:
            connection.execute("SELECT id FROM vinto_txn.capture WHERE id=ANY(%s::uuid[]) ORDER BY id FOR SHARE",(mothers,)).fetchall()
        report=one(connection,"SELECT id,status FROM vinto_txn.rewinding_export_report WHERE id=%s FOR UPDATE",(report_id,))
        if not report or report["status"] not in {"generated","observed"}:
            raise _http(409,"REPORT_NOT_ANNULABLE","El estado del reporte cambió; vuelve a consultar.")
        connection.execute("SELECT id FROM vinto_txn.rewinding_export_package WHERE report_id=%s ORDER BY package_number,id FOR UPDATE",(report_id,)).fetchall()
        connection.execute("SELECT id FROM vinto_txn.rewinding_export_package_child WHERE report_id=%s ORDER BY child_bobbin_id,id FOR UPDATE",(report_id,)).fetchall()
        active=rows(connection,"SELECT id FROM vinto_txn.rewinding_export_child_reservation WHERE report_id=%s AND released_at IS NULL ORDER BY child_bobbin_id,id FOR UPDATE",(report_id,))
        connection.execute(
            "UPDATE vinto_txn.rewinding_export_report SET status='annulled',annulled_by=%s,annulled_at=clock_timestamp(),annulled_reason=%s,updated_by=%s WHERE id=%s",
            (actor,reason.strip(),actor,report_id),
        )
        connection.execute(
            "UPDATE vinto_txn.rewinding_export_child_reservation SET released_at=clock_timestamp(),released_by=%s,release_reason=%s,updated_by=%s WHERE report_id=%s AND released_at IS NULL",
            (actor,reason.strip(),actor,report_id),
        )
        event(connection,report_id,"report_annulled",actor,reason=reason.strip(),metadata={"released_reservations":len(active)})
        if active: event(connection,report_id,"reservation_released",actor,reason=reason.strip(),metadata={"count":len(active)})
    return {"report_id":report_id,"status":"annulled","released_reservations":len(active)}


def _request_fingerprint(report:dict[str,Any],packages:list[dict[str,Any]],children:list[dict[str,Any]])->str:
    payload={
        "report_id":str(report["id"]),"pv_reference":report["pv_reference"],"article_id":str(report["article_id"]),
        "machine_id":str(report["machine_id"]),"sector_id":str(report["sector_id"]),
        "destination":report["destination_snapshot"],"format":report["format_snapshot"],
        "truck_number":report["truck_number"],"order_number":report["order_number"],"observations":report["observations"],
        "snapshot_version":1,
        "packages":[
            {"id":str(p["id"]),"package_number":p["package_number"],"mother_capture_id":str(p["mother_capture_id"]),
             "children":[{"id":str(c["id"]),"bobbin_id":str(c["child_bobbin_id"]),"slot":c["package_slot"],
                          "position":c["source_position"],"weight_kg":str(c["weight_kg_snapshot"])}
                         for c in children if c["package_id"]==p["id"]]}
            for p in packages
        ],
    }
    return sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()


def generate_report(connection,user:Any,report_id:UUID,idempotency_key:UUID,render_pdf:Callable[[dict[str,Any]],tuple[bytes,int]],*,request_id:str|None=None)->dict[str,Any]:
    """RBE-05 supplies the renderer; RBE-04 owns the transactional reservation boundary."""
    from hashlib import sha256
    from psycopg.types.json import Jsonb
    actor=_actor(user)
    prelim=one(connection,"SELECT id,status,created_by FROM vinto_txn.rewinding_export_report WHERE id=%s",(report_id,))
    if not prelim or prelim["created_by"]!=actor: raise _http(404,"DRAFT_NOT_FOUND","No se encontró el borrador solicitado.")
    machine=one(connection,"SELECT machine_code_snapshot FROM vinto_txn.rewinding_export_package WHERE report_id=%s AND removed_at IS NULL ORDER BY package_number LIMIT 1",(report_id,))
    if not machine: raise _http(422,"NO_PACKAGES","El reporte no contiene paquetes.")
    with connection.transaction():
        set_actor_context(connection,actor,request_id,"RBE report generation")
        require(connection,user,Operation.REWINDING_EXPORT_CREATE,machine["machine_code_snapshot"],"VINTO-P1-07",lock=True)
        advisory=int.from_bytes(sha256((str(actor)+":"+str(idempotency_key)).encode()).digest()[:8],"big",signed=True)
        connection.execute("SELECT pg_advisory_xact_lock(%s)",(advisory,)).fetchone()
        replay=one(
            connection,
            """
            SELECT r.id,r.status,p.pdf_bytes,p.sha256,p.page_count,p.file_name
            FROM vinto_txn.rewinding_export_report r
            JOIN vinto_txn.rewinding_export_pdf p ON p.report_id=r.id
            WHERE r.generated_by=%s AND r.generation_idempotency_key=%s
            """,
            (actor,idempotency_key),
        )
        if replay:
            if replay["id"]!=report_id: raise _http(409,"IDEMPOTENCY_KEY_REUSED","La clave ya pertenece a otro reporte.")
            if sha256(replay["pdf_bytes"]).hexdigest()!=replay["sha256"]: raise _http(500,"PDF_HASH_MISMATCH","El PDF original no supera SHA-256.")
            return {"report_id":report_id,"status":replay["status"],"file_name":replay["file_name"],"sha256":replay["sha256"],"page_count":replay["page_count"],"pdf_bytes":replay["pdf_bytes"],"replayed":True}

        work_orders=[x["work_order_id"] for x in rows(connection,"SELECT DISTINCT work_order_id FROM vinto_txn.rewinding_export_package WHERE report_id=%s AND removed_at IS NULL ORDER BY work_order_id",(report_id,))]
        child_ids=[x["child_bobbin_id"] for x in rows(connection,"SELECT child_bobbin_id FROM vinto_txn.rewinding_export_package_child WHERE report_id=%s AND removed_at IS NULL ORDER BY child_bobbin_id",(report_id,))]
        mother_ids=[x["mother_capture_id"] for x in rows(connection,"SELECT DISTINCT mother_capture_id FROM vinto_txn.rewinding_export_package WHERE report_id=%s AND removed_at IS NULL ORDER BY mother_capture_id",(report_id,))]
        if work_orders:
            connection.execute("SELECT id FROM vinto_txn.work_order WHERE id=ANY(%s::uuid[]) ORDER BY id FOR SHARE",(work_orders,)).fetchall()
        if child_ids:
            connection.execute("SELECT bobbin_id FROM vinto_txn.quality_release WHERE bobbin_id=ANY(%s::uuid[]) ORDER BY bobbin_id FOR SHARE",(child_ids,)).fetchall()
            connection.execute("SELECT id FROM vinto_txn.bobbin WHERE id=ANY(%s::uuid[]) ORDER BY id FOR SHARE",(child_ids,)).fetchall()
        if mother_ids:
            connection.execute("SELECT id FROM vinto_txn.capture WHERE id=ANY(%s::uuid[]) ORDER BY id FOR SHARE",(mother_ids,)).fetchall()
        report=one(connection,"SELECT * FROM vinto_txn.rewinding_export_report WHERE id=%s FOR UPDATE",(report_id,))
        if not report or report["created_by"]!=actor: raise _http(404,"DRAFT_NOT_FOUND","No se encontró el borrador solicitado.")
        if report["status"]!="draft": raise _http(409,"REPORT_NOT_DRAFT","El reporte ya no está en Borrador.")
        packages=rows(connection,"SELECT * FROM vinto_txn.rewinding_export_package WHERE report_id=%s AND removed_at IS NULL ORDER BY package_number,id FOR UPDATE",(report_id,))
        children=rows(
            connection,
            """
            SELECT c.* FROM vinto_txn.rewinding_export_package_child c
            JOIN vinto_txn.rewinding_export_package p ON p.id=c.package_id
            WHERE c.report_id=%s AND c.removed_at IS NULL AND p.removed_at IS NULL
            ORDER BY c.child_bobbin_id,c.id FOR UPDATE OF c
            """,
            (report_id,),
        )
        connection.execute("SELECT id FROM vinto_txn.rewinding_export_child_reservation WHERE report_id=%s ORDER BY child_bobbin_id,id FOR UPDATE",(report_id,)).fetchall()
        if not packages or not children: raise _http(422,"NO_PACKAGES","El reporte debe contener paquetes y crías.")
        if not report["truck_number"].strip() or not report["order_number"].strip(): raise _http(422,"HEADER_REQUIRED","Camión y orden son obligatorios.")
        source_rows={x["mother_capture_id"]:x for x in visible_mother_rows(connection,user)}
        for package in packages:
            source=source_rows.get(package["mother_capture_id"])
            if source is None: raise _http(409,"SOURCE_NOT_ELIGIBLE","Una madre dejó de ser elegible.")
            require(connection,user,Operation.REWINDING_EXPORT_CREATE,source["machine_code"],"VINTO-P1-07",lock=False)
            if source["source_capture_revision"]!=package["source_capture_revision"] or source["source_form_version_id"]!=package["source_form_version_id"]:
                raise _http(409,"SOURCE_CAPTURE_CHANGED","La captura P1-07 cambió después de seleccionar la madre.")
            if source["work_order_id"]!=package["work_order_id"] or source["work_order_line_id"]!=package["work_order_line_id"] or source["article_version_id"]!=package["article_version_id"]:
                raise _http(409,"SOURCE_CHAIN_CHANGED","La cadena de origen de la madre cambió.")
            if source["machine_id"]!=report["machine_id"] or source["sector_id"]!=report["sector_id"] or source["pv_reference"]!=report["pv_reference"] or source["article_id"]!=report["article_id"]:
                raise _http(409,"REPORT_CONTEXT_CHANGED","El contexto de la madre ya no coincide con el reporte.")
            option=mother_row_to_option(source)
            if option["destination"].strip()!=report["destination_snapshot"].strip() or format_value(source["source_fields"])!=report["format_snapshot"]:
                raise _http(409,"REPORT_CONTEXT_CHANGED","El destino o Formato de la madre ya no coincide con el reporte.")
            latest=one(connection,"SELECT id,classification FROM vinto_txn.rewinding_export_work_order_classification WHERE work_order_id=%s ORDER BY sequence_no DESC LIMIT 1",(package["work_order_id"],))
            if not latest or latest["classification"]!="production_confirmed":
                raise _http(409,"WORK_ORDER_NOT_CONFIRMED","Una OT no tiene clasificación positiva vigente.")
            if latest["id"]!=package["source_work_order_classification_id"]:
                connection.execute("UPDATE vinto_txn.rewinding_export_package SET source_work_order_classification_id=%s,updated_by=%s WHERE id=%s",(latest["id"],actor,package["id"]))
                package["source_work_order_classification_id"]=latest["id"]
        for child in children:
            current=one(
                connection,
                """
                SELECT b.source_capture_id,b.rewind_child_position,b.weight_kg,q.status,
                  EXISTS (SELECT 1 FROM vinto_txn.rewinding_export_child_reservation r WHERE r.child_bobbin_id=b.id AND r.released_at IS NULL) AS reserved
                FROM vinto_txn.bobbin b LEFT JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id WHERE b.id=%s
                """,
                (child["child_bobbin_id"],),
            )
            package=next(p for p in packages if p["id"]==child["package_id"])
            if not current or current["source_capture_id"]!=package["mother_capture_id"]: raise _http(409,"CHILD_WRONG_MOTHER","Una cría ya no pertenece a su madre.")
            if current["status"]!="released" or current["reserved"]: raise _http(409,"CHILD_NOT_AVAILABLE","Una cría dejó de estar liberada o ya está reservada.")
            if current["rewind_child_position"]!=child["source_position"] or current["weight_kg"]!=child["weight_kg_snapshot"]:
                raise _http(409,"CHILD_SOURCE_CHANGED","Cambió la posición o el peso de una cría.")
        if any(not any(c["package_id"]==p["id"] and c["package_slot"]=="A" for c in children) for p in packages):
            raise _http(422,"CHILD_A_REQUIRED","Todos los paquetes deben contener Cría A.")
        if any(not p["source_operator_user_id"] or not p["operator_display_name_snapshot"] for p in packages):
            raise _http(422,"SOURCE_OPERATOR_MISSING","No se puede resolver el operador original.")
        request_hash=_request_fingerprint(report,packages,children)
        snapshot={
            "schema":"VINTO-RBE-SNAPSHOT-1","report_id":str(report_id),"pv_reference":report["pv_reference"],
            "article_id":str(report["article_id"]),"machine_id":str(report["machine_id"]),"sector_id":str(report["sector_id"]),
            "destination":report["destination_snapshot"],"format":report["format_snapshot"],
            "truck_number":report["truck_number"],"order_number":report["order_number"],"observations":report["observations"],
            "generated_by":str(actor),
            "packages":[
                {"package_number":p["package_number"],"mother_capture_id":str(p["mother_capture_id"]),
                 "mother_label":p["mother_label_snapshot"],"source_work_order_classification_id":str(p["source_work_order_classification_id"]),
                 "source_fields":p["source_fields_snapshot"],
                 "children":[{"package_slot":ch["package_slot"],"bobbin_id":str(ch["child_bobbin_id"]),
                              "position":ch["source_position"],"weight_kg":str(ch["weight_kg_snapshot"])}
                             for ch in children if ch["package_id"]==p["id"]]}
                for p in packages
            ],
        }
        pdf_bytes,page_count=render_pdf(snapshot)
        if not isinstance(pdf_bytes,bytes) or not pdf_bytes.startswith(b"%PDF-") or page_count<1:
            raise _http(500,"PDF_RENDER_INVALID","El renderer no devolvió un PDF válido.")
        if len(pdf_bytes)>25*1024*1024: raise _http(413,"PDF_TOO_LARGE","El PDF supera el límite técnico de 25 MiB.")
        pdf_hash=sha256(pdf_bytes).hexdigest()
        generated_at=one(connection,"SELECT clock_timestamp() AS generated_at")["generated_at"]
        snapshot["generated_at"]=generated_at.isoformat()
        connection.execute(
            """
            UPDATE vinto_txn.rewinding_export_report
            SET status='generated',report_snapshot=%s,snapshot_version=1,generation_idempotency_key=%s,
                generation_request_sha256=%s,generated_by=%s,generated_at=%s,updated_by=%s
            WHERE id=%s
            """,
            (Jsonb(snapshot),idempotency_key,request_hash,actor,generated_at,actor,report_id),
        )
        file_name=f"RBE-{report_id}.pdf"
        connection.execute(
            """
            INSERT INTO vinto_txn.rewinding_export_pdf
              (report_id,file_name,mime_type,pdf_bytes,sha256,size_bytes,page_count,generated_at,created_by)
            VALUES (%s,%s,'application/pdf',%s,%s,%s,%s,%s,%s)
            """,
            (report_id,file_name,pdf_bytes,pdf_hash,len(pdf_bytes),page_count,generated_at,actor),
        )
        for child in children:
            connection.execute(
                """
                INSERT INTO vinto_txn.rewinding_export_child_reservation
                  (report_id,package_id,package_child_id,child_bobbin_id,reserved_by,created_by)
                VALUES (%s,%s,%s,%s,%s,%s)
                """,
                (report_id,child["package_id"],child["id"],child["child_bobbin_id"],actor,actor),
            )
        event(connection,report_id,"report_generated",actor,metadata={"sha256":pdf_hash,"page_count":page_count,"size_bytes":len(pdf_bytes)})
        event(connection,report_id,"reservation_created",actor,metadata={"count":len(children)})
    return {"report_id":report_id,"status":"generated","file_name":file_name,"sha256":pdf_hash,"page_count":page_count,"pdf_bytes":pdf_bytes,"replayed":False}

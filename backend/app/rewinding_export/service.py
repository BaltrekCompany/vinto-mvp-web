"""Dominio RBE: borradores, clasificación positiva de OT, paquetes y reservas atómicas.

La reserva se crea exclusivamente dentro de la transacción que congela el reporte.
El renderizador PDF se inyecta desde RBE-05: este módulo recibe los bytes finales y
los conserva sin reconstruirlos en lecturas posteriores.
"""
import hashlib
import json
import uuid
from decimal import Decimal

import psycopg
from fastapi import HTTPException

from app.sectors import SECTOR_REBOBINADO, scoped_sector_codes


def _context(connection, actor_id, request_id, reason):
    connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
    connection.execute("SELECT set_config('vinto.request_id', %s, true)", (str(request_id),))
    connection.execute("SELECT set_config('vinto.reason', %s, true)", (reason,))


def _dict(cursor, row):
    return None if row is None else dict(zip((c.name for c in cursor.description), row))


def _scope(sectors):
    if SECTOR_REBOBINADO not in scoped_sector_codes(sectors):
        raise HTTPException(status_code=404, detail="Recurso no encontrado")
    return [SECTOR_REBOBINADO]


def _event(connection, report_id, actor_id, event_type, reason=None, metadata=None):
    connection.execute(
        """INSERT INTO vinto_txn.rewinding_export_report_event
           (report_id,event_type,actor_id,reason,metadata)
           VALUES (%s,%s,%s,%s,%s::jsonb)""",
        (report_id, event_type, actor_id, reason, json.dumps(metadata or {}, separators=(",", ":"), default=str)),
    )


def _source_mother(connection, capture_id):
    cursor = connection.execute(
        """SELECT c.id AS mother_capture_id, c.revision, c.form_version_id, c.created_by AS operator_id,
                  c.machine_id, c.operating_date, c.status AS capture_status,
                  f.code AS form_code, fv.version_number,
                  m.code AS machine_code, m.name AS machine_name, m.active AS machine_active,
                  s.id AS sector_id, s.code AS sector_code, s.active AS sector_active,
                  wo.id AS work_order_id, wo.number AS work_order_number, wo.status AS work_order_status,
                  wo.archived_at, wo.qa_retired,
                  wol.id AS work_order_line_id, wol.machine_id AS line_machine_id,
                  wol.pv_reference, wol.article_version_id,
                  av.article_id, ar.code AS article_code, av.description AS article_description,
                  mother.id AS mother_bobbin_id, u.display_name AS operator_display_name,
                  label.value_text AS mother_label, destination.value_text AS destination
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
           LEFT JOIN LATERAL (
             SELECT d.value_text FROM vinto_txn.capture_detail d
             JOIN vinto_config.field_definition fd ON fd.id=d.field_definition_id
             WHERE d.capture_id=c.id AND fd.key='etiqueta_numero_de_bobina' LIMIT 1
           ) label ON true
           LEFT JOIN LATERAL (
             SELECT d.value_text FROM vinto_txn.capture_detail d
             JOIN vinto_config.field_definition fd ON fd.id=d.field_definition_id
             WHERE d.capture_id=c.id AND fd.key='destino' LIMIT 1
           ) destination ON true
           WHERE c.id=%s""",
        (capture_id,),
    )
    row = _dict(cursor, cursor.fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="Madre no encontrada")
    if (row["form_code"] != "VINTO-P1-07" or row["version_number"] < 3
            or row["capture_status"] not in ("submitted", "closed")
            or row["sector_code"] != SECTOR_REBOBINADO or not row["sector_active"]
            or not row["machine_active"] or row["work_order_status"] not in ("published", "in_progress", "closed")
            or row["archived_at"] is not None or row["qa_retired"]
            or row["line_machine_id"] != row["machine_id"]
            or not row["mother_label"] or not row["destination"]):
        raise HTTPException(status_code=409, detail="La madre no cumple las condiciones de elegibilidad RBE")
    classification = connection.execute(
        """SELECT id, classification FROM vinto_txn.rewinding_export_work_order_classification
           WHERE work_order_id=%s ORDER BY sequence_no DESC LIMIT 1""",
        (row["work_order_id"],),
    ).fetchone()
    if classification is None or classification[1] != "production_confirmed":
        raise HTTPException(status_code=409, detail="La OT no tiene clasificación positiva vigente para RBE")
    row["classification_id"] = classification[0]
    fields = connection.execute(
        """SELECT fd.key, d.value_type, d.value_text, d.value_decimal, d.value_integer,
                  d.value_boolean, d.value_date, d.value_time
           FROM vinto_txn.capture_detail d
           JOIN vinto_config.field_definition fd ON fd.id=d.field_definition_id
           WHERE d.capture_id=%s ORDER BY fd.display_order, fd.key""",
        (capture_id,),
    ).fetchall()
    row["source_fields"] = {
        key: {
            "type": value_type, "text": text,
            "decimal": str(decimal) if decimal is not None else None,
            "integer": str(integer) if integer is not None else None,
            "boolean": boolean,
            "date": date.isoformat() if date is not None else None,
            "time": time.isoformat() if time is not None else None,
        }
        for key, value_type, text, decimal, integer, boolean, date, time in fields
    }
    row["source_fields"]["__source"] = {
        "operating_date": row["operating_date"].isoformat(),
        "pv_reference": row["pv_reference"],
        "mother_capture_id": str(row["mother_capture_id"]),
        "article_id": str(row["article_id"]),
        "article_code": row["article_code"],
        "machine_id": str(row["machine_id"]),
        "work_order_id": str(row["work_order_id"]),
        "source_operator_user_id": str(row["operator_id"]) if row["operator_id"] else None,
    }
    return row


def create_draft(connection, *, actor_id, request_id, pv_reference, article_code, sectors):
    _scope(sectors)
    pv = pv_reference.strip() if isinstance(pv_reference, str) else ""
    code = article_code.strip() if isinstance(article_code, str) else ""
    if not pv or len(pv) > 100 or not code or len(code) > 64:
        raise HTTPException(status_code=422, detail="PV y código de producto son obligatorios")
    with connection.transaction():
        _context(connection, actor_id, request_id, "RBE draft created")
        article = connection.execute(
            """SELECT id, code FROM vinto_master.article
               WHERE code=%s AND active AND is_product""", (code,),
        ).fetchone()
        if article is None:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        sector = connection.execute(
            "SELECT id FROM vinto_master.sector WHERE code=%s AND active", (SECTOR_REBOBINADO,),
        ).fetchone()
        if sector is None:
            raise HTTPException(status_code=503, detail="El sector REBOBINADO no está disponible")
        report_id = connection.execute(
            """INSERT INTO vinto_txn.rewinding_export_report
               (pv_reference,article_id,article_code_snapshot,sector_id,created_by)
               VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (pv, article[0], article[1], sector[0], actor_id),
        ).fetchone()[0]
        _event(connection, report_id, actor_id, "draft_created")
    return report_id


def _get_draft(connection, report_id, actor_id, *, lock=False):
    suffix = " FOR UPDATE" if lock else ""
    cursor = connection.execute(
        """SELECT id,status,pv_reference,article_id,article_code_snapshot,machine_id,sector_id,
                  destination_snapshot,truck_number,order_number,observations,created_by,created_at
           FROM vinto_txn.rewinding_export_report WHERE id=%s""" + suffix,
        (report_id,),
    )
    row = _dict(cursor, cursor.fetchone())
    if row is None or row["created_by"] != actor_id:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    if row["status"] != "draft":
        raise HTTPException(status_code=409, detail="El reporte ya no es un borrador editable")
    return row


def update_draft(connection, *, actor_id, request_id, report_id, truck_number, order_number, observations):
    with connection.transaction():
        _context(connection, actor_id, request_id, "RBE draft header updated")
        report = _get_draft(connection, report_id, actor_id, lock=True)
        connection.execute(
            """UPDATE vinto_txn.rewinding_export_report
               SET truck_number=%s,order_number=%s,observations=%s,updated_by=%s
               WHERE id=%s""",
            (truck_number.strip(), order_number.strip(), observations.strip(), actor_id, report_id),
        )
    return report_id


def add_package(connection, *, actor_id, request_id, report_id, mother_capture_id, sectors):
    _scope(sectors)
    with connection.transaction():
        _context(connection, actor_id, request_id, "RBE package added")
        report = _get_draft(connection, report_id, actor_id, lock=True)
        source = _source_mother(connection, mother_capture_id)
        if source["pv_reference"] != report["pv_reference"] or source["article_id"] != report["article_id"]:
            raise HTTPException(status_code=409, detail="La madre no corresponde a la PV y producto del reporte")
        if report["machine_id"] is not None and (
            report["machine_id"] != source["machine_id"] or report["sector_id"] != source["sector_id"]
            or report["destination_snapshot"] != source["destination"]
        ):
            raise HTTPException(status_code=409, detail="El paquete no coincide con máquina y destino del reporte")
        number = connection.execute(
            """SELECT coalesce(max(package_number),0)+1
               FROM vinto_txn.rewinding_export_package
               WHERE report_id=%s AND removed_at IS NULL""", (report_id,),
        ).fetchone()[0]
        if report["machine_id"] is None:
            connection.execute(
                """UPDATE vinto_txn.rewinding_export_report
                   SET machine_id=%s,sector_id=%s,destination_snapshot=%s,updated_by=%s WHERE id=%s""",
                (source["machine_id"], source["sector_id"], source["destination"], actor_id, report_id),
            )
        package_id = connection.execute(
            """INSERT INTO vinto_txn.rewinding_export_package
               (report_id,package_number,mother_capture_id,mother_bobbin_id,mother_label_snapshot,
                source_capture_revision,source_form_version_id,work_order_id,work_order_line_id,
                source_work_order_classification_id,article_version_id,source_fields_snapshot,
                source_operator_user_id,operator_display_name_snapshot,machine_code_snapshot,
                machine_name_snapshot,work_order_number_snapshot,article_code_snapshot,
                article_description_snapshot,created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (report_id, number, mother_capture_id, source["mother_bobbin_id"], source["mother_label"],
             source["revision"], source["form_version_id"], source["work_order_id"], source["work_order_line_id"],
             source["classification_id"], source["article_version_id"],
             json.dumps(source["source_fields"], default=str, separators=(",", ":")),
             source["operator_id"], source["operator_display_name"], source["machine_code"], source["machine_name"],
             source["work_order_number"], source["article_code"], source["article_description"], actor_id),
        ).fetchone()[0]
        _event(connection, report_id, actor_id, "package_added", metadata={"package_id": str(package_id), "package_number": number})
    return package_id


def add_child(connection, *, actor_id, request_id, report_id, package_id, child_bobbin_id, package_slot):
    slot = package_slot.upper() if isinstance(package_slot, str) else ""
    if slot not in ("A", "B", "C", "D", "E"):
        raise HTTPException(status_code=422, detail="La posición del paquete debe ser A–E")
    with connection.transaction():
        _context(connection, actor_id, request_id, "RBE child selected")
        _get_draft(connection, report_id, actor_id, lock=True)
        package = connection.execute(
            """SELECT mother_capture_id FROM vinto_txn.rewinding_export_package
               WHERE id=%s AND report_id=%s AND removed_at IS NULL""", (package_id, report_id),
        ).fetchone()
        if package is None:
            raise HTTPException(status_code=404, detail="Paquete no encontrado")
        bobbin = connection.execute(
            """SELECT b.rewind_child_position,b.weight_kg,q.status
               FROM vinto_txn.bobbin b JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id
               WHERE b.id=%s AND b.source_capture_id=%s""",
            (child_bobbin_id, package[0]),
        ).fetchone()
        if bobbin is None or bobbin[2] != "released" or bobbin[0] is None or bobbin[0] == 12 or bobbin[1] is None or bobbin[1] <= 0:
            raise HTTPException(status_code=409, detail="La cría no pertenece a la madre o no está liberada por Calidad")
        child_id = connection.execute(
            """INSERT INTO vinto_txn.rewinding_export_package_child
               (report_id,package_id,child_bobbin_id,package_slot,source_position,weight_kg_snapshot,created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (report_id, package_id, child_bobbin_id, slot, bobbin[0], bobbin[1], actor_id),
        ).fetchone()[0]
        _event(connection, report_id, actor_id, "child_added", metadata={"package_id": str(package_id), "child_id": str(child_id), "slot": slot})
    return child_id


def remove_package(connection, *, actor_id, request_id, report_id, package_id, reason):
    with connection.transaction():
        _context(connection, actor_id, request_id, reason)
        _get_draft(connection, report_id, actor_id, lock=True)
        row = connection.execute(
            """UPDATE vinto_txn.rewinding_export_package
               SET removed_at=clock_timestamp(),removed_by=%s,updated_by=%s
               WHERE id=%s AND report_id=%s AND removed_at IS NULL RETURNING id""",
            (actor_id, actor_id, package_id, report_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Paquete no encontrado")
        connection.execute(
            """UPDATE vinto_txn.rewinding_export_package_child
               SET removed_at=clock_timestamp(),removed_by=%s,updated_by=%s
               WHERE package_id=%s AND report_id=%s AND removed_at IS NULL""",
            (actor_id, actor_id, package_id, report_id),
        )
        _event(connection, report_id, actor_id, "package_removed", reason, {"package_id": str(package_id)})


def remove_child(connection, *, actor_id, request_id, report_id, child_id, reason):
    with connection.transaction():
        _context(connection, actor_id, request_id, reason)
        _get_draft(connection, report_id, actor_id, lock=True)
        row = connection.execute(
            """UPDATE vinto_txn.rewinding_export_package_child
               SET removed_at=clock_timestamp(),removed_by=%s,updated_by=%s
               WHERE id=%s AND report_id=%s AND removed_at IS NULL RETURNING package_id""",
            (actor_id, actor_id, child_id, report_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Cría no encontrada en el reporte")
        _event(connection, report_id, actor_id, "child_removed", reason, {"package_id": str(row[0]), "child_id": str(child_id)})


def classify_work_order(connection, *, actor_id, request_id, work_order_id, classification, reason, sectors):
    _scope(sectors)
    with connection.transaction():
        _context(connection, actor_id, request_id, reason)
        order = connection.execute(
            """SELECT wo.id,wo.status,wo.archived_at,wo.qa_retired,s.code,s.active,m.active
               FROM vinto_txn.work_order wo
               JOIN vinto_master.machine m ON m.id=wo.machine_id
               JOIN vinto_master.sector s ON s.id=m.sector_id
               WHERE wo.id=%s FOR UPDATE OF wo""", (work_order_id,),
        ).fetchone()
        if order is None or order[4] != SECTOR_REBOBINADO or not order[5] or not order[6]:
            raise HTTPException(status_code=404, detail="OT no encontrada")
        if order[1] not in ("published", "in_progress", "closed") or order[2] is not None or order[3]:
            raise HTTPException(status_code=409, detail="La OT no es clasificable para RBE")
        latest = connection.execute(
            """SELECT id,sequence_no,classification
               FROM vinto_txn.rewinding_export_work_order_classification
               WHERE work_order_id=%s ORDER BY sequence_no DESC LIMIT 1""", (work_order_id,),
        ).fetchone()
        if latest and latest[2] == classification:
            raise HTTPException(status_code=409, detail="La OT ya tiene esa clasificación vigente")
        if classification == "qa" and connection.execute(
            """SELECT 1 FROM vinto_txn.rewinding_export_package p
               JOIN vinto_txn.rewinding_export_report r ON r.id=p.report_id
               WHERE p.work_order_id=%s AND p.removed_at IS NULL AND r.status IN ('generated','observed')
               LIMIT 1""", (work_order_id,),
        ).fetchone():
            raise HTTPException(status_code=409, detail="Anule primero los reportes RBE generados u observados de esta OT")
        seq = 1 if latest is None else latest[1] + 1
        previous = None if latest is None else latest[0]
        classification_id = connection.execute(
            """INSERT INTO vinto_txn.rewinding_export_work_order_classification
               (work_order_id,sequence_no,classification,recorded_by,reason,supersedes_id,created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (work_order_id, seq, classification, actor_id, reason.strip(), previous, actor_id),
        ).fetchone()[0]
    return classification_id


def list_classifiable_work_orders(connection, *, sectors):
    _scope(sectors)
    cursor = connection.execute(
        """SELECT wo.id,wo.number,wo.status,m.code AS machine_code,m.name AS machine_name,
                  latest.classification,latest.sequence_no,latest.recorded_at
           FROM vinto_txn.work_order wo
           JOIN vinto_master.machine m ON m.id=wo.machine_id
           JOIN vinto_master.sector s ON s.id=m.sector_id
           LEFT JOIN LATERAL (
             SELECT classification,sequence_no,recorded_at
             FROM vinto_txn.rewinding_export_work_order_classification
             WHERE work_order_id=wo.id ORDER BY sequence_no DESC LIMIT 1
           ) latest ON true
           WHERE s.code='REBOBINADO' AND s.active AND m.active
             AND wo.status IN ('published','in_progress','closed')
             AND wo.archived_at IS NULL AND NOT wo.qa_retired
           ORDER BY wo.number DESC"""
    )
    return [_dict(cursor, row) for row in cursor.fetchall()]


def get_report(connection, *, report_id, actor_id, sectors, sector_wide=False):
    allowed = _scope(sectors)
    cursor = connection.execute(
        """SELECT r.id,r.status,r.pv_reference,r.article_code_snapshot,r.machine_id,m.code AS machine_code,
                  r.destination_snapshot,r.truck_number,r.order_number,r.observations,r.report_snapshot,
                  r.created_by,r.created_at,r.generated_at,r.annulled_at,r.annulled_reason
           FROM vinto_txn.rewinding_export_report r
           LEFT JOIN vinto_master.machine m ON m.id=r.machine_id
           WHERE r.id=%s AND (r.created_by=%s OR (%s AND r.sector_id IN
             (SELECT id FROM vinto_master.sector WHERE code=ANY(%s))))""",
        (report_id, actor_id, sector_wide, allowed),
    )
    row = _dict(cursor, cursor.fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    package_cursor = connection.execute(
        """SELECT p.id,p.package_number,p.mother_label_snapshot,p.work_order_number_snapshot,
                  p.article_code_snapshot,p.article_description_snapshot,p.machine_code_snapshot,
                  p.machine_name_snapshot,p.source_fields_snapshot,p.operator_display_name_snapshot,
                  c.id AS child_id,c.child_bobbin_id,c.package_slot,c.source_position,c.weight_kg_snapshot
           FROM vinto_txn.rewinding_export_package p
           LEFT JOIN vinto_txn.rewinding_export_package_child c ON c.package_id=p.id AND c.removed_at IS NULL
           WHERE p.report_id=%s AND p.removed_at IS NULL
           ORDER BY p.package_number,c.package_slot""", (report_id,),
    )
    packages = [_dict(package_cursor, item) for item in package_cursor.fetchall()]
    return {"report": row, "packages": packages}


def list_history(connection, *, actor_id, sectors, sector_wide=False, limit=50, offset=0):
    allowed = _scope(sectors)
    cursor = connection.execute(
        """SELECT r.id,r.status,r.pv_reference,r.article_code_snapshot,r.truck_number,r.order_number,
                  r.created_at,r.generated_at,r.annulled_at,m.code AS machine_code
           FROM vinto_txn.rewinding_export_report r
           LEFT JOIN vinto_master.machine m ON m.id=r.machine_id
           WHERE (r.created_by=%s OR (%s AND r.sector_id IN
             (SELECT id FROM vinto_master.sector WHERE code=ANY(%s))))
           ORDER BY r.created_at DESC,r.id DESC LIMIT %s OFFSET %s""",
        (actor_id, sector_wide, allowed, limit, offset),
    )
    return [_dict(cursor, row) for row in cursor.fetchall()]


def generate_report(connection, *, actor_id, request_id, report_id, idempotency_key, pdf_bytes, file_name, page_count):
    """Commit report snapshot, original PDF and every reservation atomically. PDF bytes come from RBE-05."""
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes or len(pdf_bytes) > 26214400:
        raise HTTPException(status_code=413, detail="El PDF supera el límite técnico de 25 MiB o está vacío")
    if page_count < 1:
        raise HTTPException(status_code=422, detail="El PDF debe contener al menos una página")
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    request_seed = json.dumps({"report_id": str(report_id), "idempotency_key": str(idempotency_key),
                               "pdf_sha256": pdf_hash, "file_name": file_name, "page_count": page_count}, sort_keys=True)
    request_hash = hashlib.sha256(request_seed.encode()).hexdigest()
    with connection.transaction():
        _context(connection, actor_id, request_id, "RBE report generated")
        report = connection.execute(
            """SELECT status,created_by,pv_reference,article_id,article_code_snapshot,machine_id,sector_id,
                      destination_snapshot,truck_number,order_number,observations,generation_idempotency_key,
                      generation_request_sha256
               FROM vinto_txn.rewinding_export_report WHERE id=%s FOR UPDATE""", (report_id,),
        ).fetchone()
        if report is None or report[1] != actor_id:
            raise HTTPException(status_code=404, detail="Reporte no encontrado")
        if report[0] in ("generated", "observed"):
            if report[11] == idempotency_key and report[12] == request_hash:
                return {"report_id": report_id, "already_generated": True}
            raise HTTPException(status_code=409, detail="El reporte ya fue generado con otra solicitud")
        if report[0] != "draft":
            raise HTTPException(status_code=409, detail="El reporte no está en estado Borrador")
        if not report[7] or not report[8].strip() or not report[9].strip():
            raise HTTPException(status_code=422, detail="Destino, camión y orden son obligatorios para generar")
        packages = connection.execute(
            """SELECT p.id,p.work_order_id,p.work_order_line_id,p.article_version_id,p.source_work_order_classification_id,
                      p.package_number,p.mother_label_snapshot,p.source_fields_snapshot,p.machine_code_snapshot,
                      p.machine_name_snapshot,p.work_order_number_snapshot,p.article_code_snapshot,p.article_description_snapshot,
                      p.operator_display_name_snapshot,p.mother_capture_id
               FROM vinto_txn.rewinding_export_package p
               WHERE p.report_id=%s AND p.removed_at IS NULL ORDER BY p.package_number FOR UPDATE""",
            (report_id,),
        ).fetchall()
        if not packages:
            raise HTTPException(status_code=422, detail="El reporte debe contener al menos un paquete")
        # Lock OT rows in stable order: classification changes use FOR UPDATE on the same rows.
        work_order_ids = sorted({row[1] for row in packages}, key=str)
        locked = connection.execute(
            "SELECT id FROM vinto_txn.work_order WHERE id = ANY(%s) ORDER BY id FOR SHARE",
            (work_order_ids,),
        ).fetchall()
        if len(locked) != len(work_order_ids):
            raise HTTPException(status_code=409, detail="Una OT de origen ya no está disponible")
        snapshot_packages = []
        for p in packages:
            latest = connection.execute(
                """SELECT id,classification FROM vinto_txn.rewinding_export_work_order_classification
                   WHERE work_order_id=%s ORDER BY sequence_no DESC LIMIT 1""", (p[1],),
            ).fetchone()
            if latest is None or latest[1] != "production_confirmed":
                raise HTTPException(status_code=409, detail="La OT dejó de estar clasificada como producción")
            if latest[0] != p[4]:
                connection.execute(
                    """UPDATE vinto_txn.rewinding_export_package
                       SET source_work_order_classification_id=%s,updated_by=%s WHERE id=%s""",
                    (latest[0], actor_id, p[0]),
                )
            children = connection.execute(
                """SELECT c.id,c.child_bobbin_id,c.package_slot,c.source_position,c.weight_kg_snapshot,
                          b.rewind_child_position,b.weight_kg,q.status
                   FROM vinto_txn.rewinding_export_package_child c
                   JOIN vinto_txn.bobbin b ON b.id=c.child_bobbin_id
                   JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id
                   WHERE c.package_id=%s AND c.report_id=%s AND c.removed_at IS NULL
                   ORDER BY c.package_slot FOR UPDATE OF b,q,c""", (p[0], report_id),
            ).fetchall()
            if not 1 <= len(children) <= 5 or not any(ch[2] == "A" for ch in children):
                raise HTTPException(status_code=422, detail="Cada paquete necesita entre una y cinco crías y debe incluir la cría A")
            for ch in children:
                if ch[5] != ch[3] or ch[6] != ch[4] or ch[7] != "released":
                    raise HTTPException(status_code=409, detail="Una cría cambió de posición, peso o estado de Calidad")
            snapshot_packages.append({
                "package_number": p[5], "mother_label": p[6], "work_order_number": p[10],
                "article_code": p[11], "article_description": p[12], "machine_code": p[8],
                "machine_name": p[9], "operator": p[13], "source_fields": p[7],
                "children": [{"slot": ch[2], "position": ch[3], "weight_kg": str(ch[4]), "bobbin_id": str(ch[1])} for ch in children],
            })
        snapshot = {
            "version": 1, "pv_reference": report[2], "article_code": report[4],
            "destination": report[7], "truck_number": report[8], "order_number": report[9],
            "observations": report[10], "packages": snapshot_packages,
        }
        generated_at = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        connection.execute(
            """UPDATE vinto_txn.rewinding_export_report
               SET status='generated',generated_by=%s,generated_at=%s,
                   generation_idempotency_key=%s,generation_request_sha256=%s,
                   report_snapshot=%s::jsonb,snapshot_version=1,updated_by=%s
               WHERE id=%s""",
            (actor_id, generated_at, idempotency_key, request_hash,
             json.dumps(snapshot, default=str, separators=(",", ":")), actor_id, report_id),
        )
        connection.execute(
            """INSERT INTO vinto_txn.rewinding_export_pdf
               (report_id,file_name,mime_type,pdf_bytes,sha256,size_bytes,page_count,generated_at)
               VALUES (%s,%s,'application/pdf',%s,%s,%s,%s,%s)""",
            (report_id, file_name, pdf_bytes, pdf_hash, len(pdf_bytes), page_count, generated_at),
        )
        for package in packages:
            child_rows = connection.execute(
                """SELECT c.id,c.child_bobbin_id FROM vinto_txn.rewinding_export_package_child c
                   WHERE c.package_id=%s AND c.report_id=%s AND c.removed_at IS NULL""",
                (package[0], report_id),
            ).fetchall()
            for child_id, bobbin_id in child_rows:
                reservation = connection.execute(
                    """INSERT INTO vinto_txn.rewinding_export_reservation
                       (report_id,package_id,package_child_id,child_bobbin_id,reserved_by)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT DO NOTHING
                       RETURNING id""",
                    (report_id, package[0], child_id, bobbin_id, actor_id),
                ).fetchone()
                if reservation is None:
                    raise HTTPException(status_code=409, detail="Una de las crías ya está reservada en otro reporte")
                _event(connection, report_id, actor_id, "reservation_created", metadata={"child_id": str(child_id), "bobbin_id": str(bobbin_id)})
        _event(connection, report_id, actor_id, "report_generated", metadata={"pdf_sha256": pdf_hash, "size_bytes": len(pdf_bytes), "page_count": page_count})
    return {"report_id": report_id, "already_generated": False, "pdf_sha256": pdf_hash}


def annul_report(connection, *, actor_id, request_id, report_id, reason, sectors):
    _scope(sectors)
    clean = reason.strip() if isinstance(reason, str) else ""
    if not 10 <= len(clean) <= 300:
        raise HTTPException(status_code=422, detail="El motivo de anulación debe tener entre 10 y 300 caracteres")
    with connection.transaction():
        _context(connection, actor_id, request_id, clean)
        report = connection.execute(
            """SELECT status,created_by FROM vinto_txn.rewinding_export_report WHERE id=%s FOR UPDATE""",
            (report_id,),
        ).fetchone()
        if report is None:
            raise HTTPException(status_code=404, detail="Reporte no encontrado")
        if report[0] not in ("generated", "observed"):
            raise HTTPException(status_code=409, detail="Solo se pueden anular reportes Generados u Observados")
        connection.execute(
            """UPDATE vinto_txn.rewinding_export_report
               SET status='annulled',annulled_by=%s,annulled_at=clock_timestamp(),
                   annulled_reason=%s,updated_by=%s WHERE id=%s""",
            (actor_id, clean, actor_id, report_id),
        )
        released = connection.execute(
            """UPDATE vinto_txn.rewinding_export_reservation r
               SET released_at=clock_timestamp(),released_by=%s,release_reason=%s
               FROM vinto_txn.rewinding_export_package_child c
               WHERE c.id=r.package_child_id AND c.report_id=%s AND r.released_at IS NULL
               RETURNING r.child_bobbin_id""",
            (actor_id, clean, report_id),
        ).fetchall()
        for (bobbin_id,) in released:
            _event(connection, report_id, actor_id, "reservation_released", clean, {"bobbin_id": str(bobbin_id)})
        _event(connection, report_id, actor_id, "report_annulled", clean, {"released_reservations": len(released)})
    return {"report_id": report_id, "released_reservations": len(released)}


def download_original_pdf(connection, *, report_id, actor_id, sectors, sector_wide=False):
    report = get_report(connection, report_id=report_id, actor_id=actor_id, sectors=sectors, sector_wide=sector_wide)
    if report["report"]["status"] not in ("generated", "observed", "annulled"):
        raise HTTPException(status_code=404, detail="PDF no encontrado")
    pdf = connection.execute(
        """SELECT file_name,pdf_bytes,sha256,size_bytes,page_count
           FROM vinto_txn.rewinding_export_pdf WHERE report_id=%s""", (report_id,),
    ).fetchone()
    if pdf is None:
        raise HTTPException(status_code=503, detail="PDF original no disponible")
    file_name, content, expected, size, pages = pdf
    if len(content) != size or hashlib.sha256(content).hexdigest() != expected:
        raise HTTPException(status_code=503, detail="No se pudo verificar la integridad del PDF original")
    return file_name, content, expected, pages


def list_eligible_mothers(connection, *, sectors, pv_reference=None, article_code=None):
    _scope(sectors)
    params = [pv_reference, article_code]
    cursor = connection.execute(
        """SELECT c.id AS mother_capture_id,label.value_text AS mother_label,
                  wo.number AS work_order_number,wol.pv_reference,ar.code AS article_code,
                  av.description AS article_description,m.code AS machine_code,m.name AS machine_name,
                  destination.value_text AS destination,u.display_name AS operator_display_name,
                  count(DISTINCT b.id) AS available_children
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
           JOIN LATERAL (
             SELECT d.value_text FROM vinto_txn.capture_detail d
             JOIN vinto_config.field_definition fd ON fd.id=d.field_definition_id
             WHERE d.capture_id=c.id AND fd.key='etiqueta_numero_de_bobina' LIMIT 1
           ) label ON true
           JOIN LATERAL (
             SELECT d.value_text FROM vinto_txn.capture_detail d
             JOIN vinto_config.field_definition fd ON fd.id=d.field_definition_id
             WHERE d.capture_id=c.id AND fd.key='destino' LIMIT 1
           ) destination ON true
           JOIN vinto_txn.rewinding_export_work_order_classification wc
             ON wc.id=(SELECT c2.id FROM vinto_txn.rewinding_export_work_order_classification c2
                       WHERE c2.work_order_id=wo.id ORDER BY c2.sequence_no DESC LIMIT 1)
           JOIN vinto_txn.bobbin b ON b.source_capture_id=c.id AND b.rewind_child_position IS NOT NULL
           JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id AND q.status='released'
           LEFT JOIN vinto_txn.rewinding_export_reservation r
             ON r.child_bobbin_id=b.id AND r.released_at IS NULL
           WHERE f.code='VINTO-P1-07' AND fv.version_number>=3
             AND c.status IN ('submitted','closed')
             AND s.code='REBOBINADO' AND s.active AND m.active
             AND wo.status IN ('published','in_progress','closed')
             AND wo.archived_at IS NULL AND NOT wo.qa_retired
             AND wc.classification='production_confirmed' AND ar.active AND ar.is_product
             AND b.rewind_child_position BETWEEN 1 AND 22 AND b.rewind_child_position<>12
             AND b.weight_kg>0 AND r.id IS NULL
             AND (%s::text IS NULL OR wol.pv_reference=%s)
             AND (%s::text IS NULL OR ar.code=%s)
           GROUP BY c.id,label.value_text,wo.number,wol.pv_reference,ar.code,av.description,
                    m.code,m.name,destination.value_text,u.display_name
           ORDER BY wol.pv_reference,wo.number,label.value_text""",
        (pv_reference, pv_reference, article_code, article_code),
    )
    return [_dict(cursor, row) for row in cursor.fetchall()]


def get_work_order_classification(connection, *, work_order_id, sectors):
    _scope(sectors)
    row = connection.execute(
        """SELECT c.id,c.work_order_id,c.sequence_no,c.classification,c.recorded_by,
                  c.recorded_at,c.reason,c.supersedes_id
           FROM vinto_txn.rewinding_export_work_order_classification c
           JOIN vinto_txn.work_order wo ON wo.id=c.work_order_id
           JOIN vinto_master.machine m ON m.id=wo.machine_id
           JOIN vinto_master.sector s ON s.id=m.sector_id
           WHERE c.work_order_id=%s AND s.code='REBOBINADO'
           ORDER BY c.sequence_no DESC LIMIT 1""",
        (work_order_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Clasificación no encontrada")
    return {
        "id": row[0], "work_order_id": row[1], "sequence_no": row[2],
        "classification": row[3], "recorded_by": row[4], "recorded_at": row[5],
        "reason": row[6], "supersedes_id": row[7],
    }

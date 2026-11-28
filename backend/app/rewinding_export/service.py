"""Dominio RBE: borradores, clasificación positiva de OT, paquetes y reservas atómicas.

La reserva se crea exclusivamente dentro de la transacción que congela el reporte.
El PDF se renderiza desde el snapshot definitivo y se conserva para lecturas posteriores.
"""
import hashlib
import json
import logging
import uuid
from collections import defaultdict
from decimal import Decimal

import psycopg
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from app.auth.permissions import REWINDING_EXPORT_CREATE
from app.authz import Operation, require
from app.rewinding_export import repository
from app.rewinding_export.pdf_renderer import PDFLayoutError, PDFTooLarge, render_pdf
from app.rewinding_export.repository import require_sector_permission

from app.sectors import SECTOR_REBOBINADO, scoped_sector_codes


SNAPSHOT_VERSION = 1
logger = logging.getLogger(__name__)


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
                  ar.active AND ar.is_product AS article_eligible,
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
            or not row["machine_active"] or not row["article_eligible"] or row["work_order_status"] not in ("published", "in_progress", "closed")
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
           WHERE d.capture_id=%s AND d.group_row_id IS NULL ORDER BY fd.display_order, fd.key""",
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
            (truck_number.strip(), order_number.strip(), observations, actor_id, report_id),
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
               WHERE b.id=%s AND b.source_capture_id=%s AND NOT EXISTS (
                   SELECT 1 FROM vinto_txn.rewinding_export_reservation r
                   WHERE r.child_bobbin_id=b.id AND r.released_at IS NULL
               )""",
            (child_bobbin_id, package[0]),
        ).fetchone()
        if bobbin is None or bobbin[2] != "released" or bobbin[0] is None or bobbin[0] == 12 or bobbin[1] is None or bobbin[1] <= 0:
            raise HTTPException(status_code=409, detail="La cría no pertenece a la madre o no está liberada por Calidad")
        if connection.execute("""
            SELECT 1 FROM vinto_txn.rewinding_export_package_child
            WHERE report_id=%s AND removed_at IS NULL
              AND (child_bobbin_id=%s OR (package_id=%s AND package_slot=%s))
        """, (report_id, child_bobbin_id, package_id, slot)).fetchone():
            raise HTTPException(status_code=422, detail="La cría o la posición del paquete ya está seleccionada")
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
           WHERE s.code=%s AND s.active AND m.active
             AND wo.status IN ('published','in_progress','closed')
             AND wo.archived_at IS NULL AND NOT wo.qa_retired
           ORDER BY wo.number DESC""",
        (SECTOR_REBOBINADO,),
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
           WHERE r.id=%s AND (r.created_by=%s OR %s)
             AND r.status IN ('generated','observed','annulled')
             AND r.sector_id IN (SELECT id FROM vinto_master.sector WHERE code=ANY(%s))""",
        (report_id, actor_id, sector_wide, allowed),
    )
    row = _dict(cursor, cursor.fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    package_cursor = connection.execute(
        """SELECT p.id,p.package_number,p.mother_label_snapshot,p.work_order_number_snapshot,
                  p.article_code_snapshot,p.article_description_snapshot,p.machine_code_snapshot,
                  p.machine_name_snapshot,p.source_fields_snapshot,p.operator_display_name_snapshot,
                  c.id AS child_id,c.child_bobbin_id,c.package_slot,c.source_position,c.weight_kg_snapshot::text AS weight_kg_snapshot
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
           WHERE (r.created_by=%s OR %s)
             AND r.sector_id IN (SELECT id FROM vinto_master.sector WHERE code=ANY(%s))
             AND r.status IN ('generated','observed','annulled')
           ORDER BY r.created_at DESC,r.id DESC LIMIT %s OFFSET %s""",
        (actor_id, sector_wide, allowed, limit, offset),
    )
    return [_dict(cursor, row) for row in cursor.fetchall()]


def _report_header(connection, report_id, actor_id, sector_id, *, lock=False):
    suffix = " FOR UPDATE OF r" if lock else ""
    report = repository.one(connection, """
        SELECT r.*, m.code AS machine_code FROM vinto_txn.rewinding_export_report r
        LEFT JOIN vinto_master.machine m ON m.id=r.machine_id
        WHERE r.id=%s AND r.created_by=%s AND r.sector_id=%s
    """ + suffix, (report_id, actor_id, sector_id))
    if report is None:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    return report


def _selection(connection, report_id, *, lock=False):
    suffix = " FOR UPDATE" if lock else ""
    packages = repository.rows(connection, """
        SELECT * FROM vinto_txn.rewinding_export_package WHERE report_id=%s
        ORDER BY package_number,id
    """ + suffix, (report_id,))
    children = repository.rows(connection, """
        SELECT * FROM vinto_txn.rewinding_export_package_child WHERE report_id=%s
        ORDER BY child_bobbin_id,id
    """ + suffix, (report_id,))
    grouped = defaultdict(list)
    for child in children:
        if child["removed_at"] is None:
            grouped[child["package_id"]].append(child)
    for package in packages:
        package["children"] = sorted(grouped[package["id"]], key=lambda child: child["package_slot"])
    return [package for package in packages if package["removed_at"] is None]


def _source_ids(packages):
    return (
        sorted({p["work_order_id"] for p in packages}),
        sorted({ch["child_bobbin_id"] for p in packages for ch in p["children"]}),
        sorted({p["mother_capture_id"] for p in packages}),
    )


def _lock_sources(connection, orders, bobbins, mothers):
    # RBE-02 global order. Explicit queries also order locks within each table.
    connection.execute("SELECT id FROM vinto_txn.work_order WHERE id=ANY(%s) ORDER BY id FOR SHARE", (orders,))
    connection.execute("SELECT bobbin_id FROM vinto_txn.quality_release WHERE bobbin_id=ANY(%s) ORDER BY bobbin_id FOR SHARE", (bobbins,))
    connection.execute("SELECT id FROM vinto_txn.bobbin WHERE id=ANY(%s) ORDER BY id FOR SHARE", (bobbins,))
    connection.execute("SELECT id FROM vinto_txn.capture WHERE id=ANY(%s) ORDER BY id FOR SHARE", (mothers,))


def _lock_reservations(connection, bobbins):
    connection.execute("""
        SELECT id FROM vinto_txn.rewinding_export_reservation
        WHERE child_bobbin_id=ANY(%s) AND released_at IS NULL ORDER BY child_bobbin_id,id FOR UPDATE
    """, (bobbins,))


def _fingerprint(report, packages):
    header = {key: report[key] for key in (
        "pv_reference", "article_id", "article_code_snapshot", "machine_id", "sector_id",
        "destination_snapshot", "truck_number", "order_number", "observations",
    )}
    canonical = {
        "report_id": report["id"], "header": header, "version": report["snapshot_version"] or SNAPSHOT_VERSION,
        "packages": [
            [p["package_number"], p["mother_capture_id"],
             [[ch["package_slot"], ch["child_bobbin_id"]] for ch in p["children"]]]
            for p in packages
        ],
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class ReportValidation(HTTPException):
    def __init__(self, code, message, status=422):
        super().__init__(status_code=status, detail={"code": code, "message": message})


def _source_warnings(fields, package, *, child_count, child_weight):
    value = repository._field
    start, end = value(fields, "hora_inicio", "time"), value(fields, "hora_fin", "time")
    weight, cuts = value(fields, "peso", "decimal"), package["cuts"]
    checks = [
        (start and end and end < start, "SOURCE_TIME_INVERTED", "La hora de fin precede a la hora de inicio."),
        (weight is not None and child_weight > Decimal(weight),
         "CHILD_WEIGHT_SUM_EXCEEDS_MOTHER", "El peso de las crías supera el peso declarado de la madre."),
        (cuts is not None and Decimal(cuts) != child_count,
         "SOURCE_CUTS_DO_NOT_MATCH_CHILD_COUNT", "Cortes difiere de la cantidad de crías de origen."),
        (not package["helper"] or not value(fields, "producto_refilado", "text"),
         "OPTIONAL_SOURCE_FIELD_MISSING", "Falta ayudante o producto refilado en la captura fuente."),
    ]
    return [{"code": code, "message": message, "package_number": package["package_number"]}
            for condition, code, message in checks if condition]


def _validated_snapshot(connection, report, packages):
    if not report["pv_reference"].strip() or not report["article_id"] or not packages:
        raise ReportValidation("V01", "Se requieren PV, producto y al menos un paquete.")
    if not report["truck_number"].strip() or not report["order_number"].strip():
        raise ReportValidation("V02", "Camión y orden son obligatorios.")
    if any(not p["mother_capture_id"] or not 1 <= len(p["children"]) <= 5
           or p["children"][0]["package_slot"] != "A" for p in packages):
        raise ReportValidation("V03", "Cada paquete requiere madre y de una a cinco crías, incluida A.")
    _, bobbins, mothers = _source_ids(packages)
    if len(bobbins) != sum(len(p["children"]) for p in packages):
        raise ReportValidation("V04", "Una cría se repite en el reporte.")
    live_children = {row["id"]: row for row in repository.rows(connection, """
        SELECT b.id,b.source_capture_id,b.rewind_child_position,b.weight_kg,q.status,
               r.id IS NOT NULL AS reserved
        FROM vinto_txn.bobbin b LEFT JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id
        LEFT JOIN vinto_txn.rewinding_export_reservation r ON r.child_bobbin_id=b.id AND r.released_at IS NULL
        WHERE b.id=ANY(%s)
    """, (bobbins,))}
    aggregates = {row["source_capture_id"]: row for row in repository.rows(connection, """
        SELECT source_capture_id,count(*) AS child_count,coalesce(sum(weight_kg),0) AS child_weight
        FROM vinto_txn.bobbin WHERE source_capture_id=ANY(%s) AND rewind_child_position IS NOT NULL
        GROUP BY source_capture_id
    """, (mothers,))}
    source_by_id = {}
    snapshot_packages = []
    warnings = []
    report_format = None
    for package in packages:
        mother_id = package["mother_capture_id"]
        if mother_id not in source_by_id:
            try:
                source_by_id[mother_id] = _source_mother(connection, mother_id)
            except HTTPException as error:
                raise ReportValidation("V08", error.detail, 409) from error
        source = source_by_id[mother_id]
        fields = source["source_fields"]
        format_value = repository.format_value(fields)
        if (not format_value or (report_format is not None and report_format != format_value)
                or any(source[key] != report[key] for key in ("pv_reference", "article_id", "machine_id", "sector_id"))
                or source["article_code"] != report["article_code_snapshot"]
                or source["destination"].strip() != (report["destination_snapshot"] or "").strip()):
            raise ReportValidation("V07", "Los paquetes deben compartir PV, producto, formato, destino y máquina.")
        report_format = format_value
        if (source["revision"] != package["source_capture_revision"]
                or source["form_version_id"] != package["source_form_version_id"]
                or source["mother_label"] != package["mother_label_snapshot"]
                or source["operator_id"] != package["source_operator_user_id"]
                or any(source[key] != package[key] for key in
                       ("work_order_id", "work_order_line_id", "article_version_id", "mother_bobbin_id"))):
            raise ReportValidation("V08", "Cambió la captura de origen. Vuelva a seleccionar el paquete.", 409)
        diameter = repository._field(fields, "diametro", "decimal")
        tubete = repository._field(fields, "tubete", "text")
        if not diameter or not tubete or not (source["operator_display_name"] or "").strip():
            raise ReportValidation("V08", "La captura requiere diámetro, tubete y operador original.")
        children = []
        for child in package["children"]:
            live = live_children.get(child["child_bobbin_id"])
            if live and live["source_capture_id"] != mother_id:
                raise ReportValidation("V06", "Una cría no pertenece a la madre del paquete.")
            if not live or live["status"] != "released" or live["reserved"]:
                raise ReportValidation("V05", "Una cría ya no está liberada o disponible.", 409)
            position, weight = live["rewind_child_position"], live["weight_kg"]
            if (position not in range(1, 23) or position == 12 or weight is None or weight <= 0
                    or position != child["source_position"] or weight != child["weight_kg_snapshot"]):
                raise ReportValidation("V08", "Cambió la posición o el peso de una cría.", 409)
            children.append({"slot": child["package_slot"], "position": position, "weight_kg": str(weight),
                             "bobbin_id": str(child["child_bobbin_id"])})
        output = {
            "package_number": package["package_number"], "mother_label": source["mother_label"],
            "mother_capture_id": str(mother_id), "source_capture_revision": source["revision"],
            "source_form_version_id": str(source["form_version_id"]),
            "work_order_id": str(source["work_order_id"]), "work_order_number": source["work_order_number"],
            "work_order_line_id": str(source["work_order_line_id"]), "classification": "production_confirmed",
            "source_work_order_classification_id": str(source["classification_id"]),
            "article_version_id": str(source["article_version_id"]), "article_code": source["article_code"],
            "article_description": source["article_description"],
            "machine_name": source["machine_name"], "machine_code": source["machine_code"],
            "operator": source["operator_display_name"], "operator_id": str(source["operator_id"]),
            "diameter": diameter, "tubete": tubete, "cuts": repository._field(fields, "formato_3", "decimal"),
            "helper": repository._field(fields, "auxiliar", "text"), "children": children, "source_fields": fields,
        }
        snapshot_packages.append(output)
        aggregate = aggregates[mother_id]
        warnings.extend(_source_warnings(fields, output, child_count=aggregate["child_count"],
                                         child_weight=aggregate["child_weight"]))
    descriptions = {p["article_description"] for p in snapshot_packages}
    return {
        "version": SNAPSHOT_VERSION, "report_id": str(report["id"]), "pv_reference": report["pv_reference"],
        "article_code": report["article_code_snapshot"],
        "article_description": next(iter(descriptions)) if len(descriptions) == 1 else None,
        "machine_name": snapshot_packages[0]["machine_name"], "machine_code": report["machine_code"],
        "format": report_format, "destination": report["destination_snapshot"],
        "truck_number": report["truck_number"], "order_number": report["order_number"],
        "observations": report["observations"], "packages": snapshot_packages, "warnings": warnings,
    }


def preview_report(connection, *, user, report_id):
    sector_id = require_sector_permission(connection, user, REWINDING_EXPORT_CREATE, lock=False)
    report = _report_header(connection, report_id, user.user_id, sector_id)
    if report["status"] != "draft":
        raise HTTPException(status_code=409, detail="El reporte ya no es un borrador editable")
    if report["machine_code"]:
        require(connection, user, Operation.REWINDING_EXPORT_CREATE, report["machine_code"], "VINTO-P1-07", lock=False)
    packages = _selection(connection, report_id)
    errors, warnings = [], []
    try:
        warnings = _validated_snapshot(connection, report, packages)["warnings"]
    except ReportValidation as error:
        errors.append(error.detail)
    return {"valid": not errors, "package_count": len(packages),
            "child_count": sum(len(p["children"]) for p in packages),
            "warnings": warnings, "blocking_errors": errors}


def generate_report(connection, *, user, request_id, report_id, idempotency_key):
    actor_id = user.user_id
    with connection.transaction():
        sector_id = require_sector_permission(connection, user, REWINDING_EXPORT_CREATE, lock=True)
        initial = _report_header(connection, report_id, actor_id, sector_id)
        if initial["machine_code"]:
            require(connection, user, Operation.REWINDING_EXPORT_CREATE, initial["machine_code"], "VINTO-P1-07", lock=True)
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                           (f"rbe:{actor_id}:{idempotency_key}",))
        # After waiting on the key, another request may already have committed.
        preliminary = _selection(connection, report_id)
        initial_sources = _source_ids(preliminary)
        _lock_sources(connection, *initial_sources)
        report = _report_header(connection, report_id, actor_id, sector_id, lock=True)
        packages = _selection(connection, report_id, lock=True)
        if initial_sources != _source_ids(packages) or initial["machine_id"] != report["machine_id"]:
            raise ReportValidation("V08", "El borrador cambió durante la validación. Actualice la vista previa.", 409)
        request_hash = _fingerprint(report, packages)
        existing = repository.one(connection, """
            SELECT id,generation_request_sha256 FROM vinto_txn.rewinding_export_report
            WHERE generated_by=%s AND generation_idempotency_key=%s
        """, (actor_id, idempotency_key))
        if existing:
            if existing["id"] != report_id or existing["generation_request_sha256"] != request_hash:
                raise HTTPException(status_code=409, detail="La clave de generación ya se utilizó con otra solicitud")
            return report["status"], _original_pdf(connection, report_id)
        if report["status"] != "draft":
            raise HTTPException(status_code=409, detail="El reporte no está en estado Borrador")
        if _fingerprint(initial, preliminary) != request_hash:
            raise ReportValidation("V08", "El borrador cambió durante la validación. Actualice la vista previa.", 409)
        _lock_reservations(connection, initial_sources[1])
        snapshot = _validated_snapshot(connection, report, packages)
        generated_at = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        snapshot.update(generated_at=generated_at.isoformat(), generated_by=str(actor_id))
        try:
            pdf_bytes, page_count = render_pdf(snapshot)
        except PDFTooLarge as error:
            raise HTTPException(status_code=413, detail=str(error)) from error
        except PDFLayoutError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
        file_name = f"rbe-{report_id}.pdf"
        _context(connection, actor_id, request_id, "RBE report generated")
        for package, output in zip(packages, snapshot["packages"], strict=True):
            classification_id = uuid.UUID(output["source_work_order_classification_id"])
            if package["source_work_order_classification_id"] != classification_id:
                connection.execute("""
                    UPDATE vinto_txn.rewinding_export_package
                    SET source_work_order_classification_id=%s,updated_by=%s WHERE id=%s
                """, (classification_id, actor_id, package["id"]))
        connection.execute("""
            UPDATE vinto_txn.rewinding_export_report
            SET status='generated',generated_by=%s,generated_at=%s,generation_idempotency_key=%s,
                generation_request_sha256=%s,report_snapshot=%s,snapshot_version=%s,updated_by=%s
            WHERE id=%s
        """, (actor_id, generated_at, idempotency_key, request_hash, Jsonb(snapshot),
              SNAPSHOT_VERSION, actor_id, report_id))
        connection.execute("""
            INSERT INTO vinto_txn.rewinding_export_pdf
                (report_id,file_name,mime_type,pdf_bytes,sha256,size_bytes,page_count,generated_at)
            VALUES (%s,%s,'application/pdf',%s,%s,%s,%s,%s)
        """, (report_id, file_name, pdf_bytes, pdf_hash, len(pdf_bytes), page_count, generated_at))
        children = sorted((ch for p in packages for ch in p["children"]), key=lambda ch: ch["child_bobbin_id"])
        for child in children:
            reservation = connection.execute("""
                INSERT INTO vinto_txn.rewinding_export_reservation
                    (report_id,package_id,package_child_id,child_bobbin_id,reserved_by)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING RETURNING id
            """, (report_id, child["package_id"], child["id"], child["child_bobbin_id"], actor_id)).fetchone()
            if reservation is None:
                raise ReportValidation("V05", "Una cría ya está reservada en otro reporte.", 409)
            _event(connection, report_id, actor_id, "reservation_created",
                   metadata={"child_id": str(child["id"]), "bobbin_id": str(child["child_bobbin_id"])})
        _event(connection, report_id, actor_id, "report_generated",
               metadata={"pdf_sha256": pdf_hash, "size_bytes": len(pdf_bytes), "page_count": page_count})
    return "generated", (file_name, pdf_bytes, pdf_hash, page_count)


def annul_report(connection, *, user, actor_id, request_id, report_id, reason, sectors):
    _scope(sectors)
    clean = reason.strip() if isinstance(reason, str) else ""
    if not 10 <= len(clean) <= 300:
        raise HTTPException(status_code=422, detail="El motivo de anulación debe tener entre 10 y 300 caracteres")
    with connection.transaction():
        _context(connection, actor_id, request_id, clean)
        from app.auth.permissions import REWINDING_EXPORT_ANNUL
        from app.rewinding_export.repository import require_sector_permission
        sector_id = require_sector_permission(connection, user, REWINDING_EXPORT_ANNUL, lock=True)
        sources = _source_ids(_selection(connection, report_id))
        _lock_sources(connection, *sources)
        report = connection.execute(
            """SELECT status,created_by FROM vinto_txn.rewinding_export_report WHERE id=%s AND sector_id=%s FOR UPDATE""",
            (report_id, sector_id),
        ).fetchone()
        if report is None:
            raise HTTPException(status_code=404, detail="Reporte no encontrado")
        if report[0] not in ("generated", "observed"):
            raise HTTPException(status_code=409, detail="Solo se pueden anular reportes Generados u Observados")
        if sources != _source_ids(_selection(connection, report_id, lock=True)):
            raise HTTPException(status_code=409, detail="El reporte cambió durante la validación")
        _lock_reservations(connection, sources[1])
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
    return _original_pdf(connection, report_id)


def _original_pdf(connection, report_id):
    pdf = connection.execute(
        """SELECT file_name,pdf_bytes,sha256,size_bytes,page_count
           FROM vinto_txn.rewinding_export_pdf WHERE report_id=%s""", (report_id,),
    ).fetchone()
    if pdf is None:
        logger.error("RBE: PDF original ausente para reporte %s", report_id)
        raise HTTPException(status_code=503, detail="PDF original no disponible")
    file_name, content, expected, size, pages = pdf
    if len(content) != size or hashlib.sha256(content).hexdigest() != expected:
        logger.error("RBE: PDF original corrupto para reporte %s", report_id)
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
             AND s.code=%s AND s.active AND m.active
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
        (SECTOR_REBOBINADO, pv_reference, pv_reference, article_code, article_code),
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
           WHERE c.work_order_id=%s AND s.code=%s
           ORDER BY c.sequence_no DESC LIMIT 1""",
        (work_order_id, SECTOR_REBOBINADO),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Clasificación no encontrada")
    return {
        "id": row[0], "work_order_id": row[1], "sequence_no": row[2],
        "classification": row[3], "recorded_by": row[4], "recorded_at": row[5],
        "reason": row[6], "supersedes_id": row[7],
    }

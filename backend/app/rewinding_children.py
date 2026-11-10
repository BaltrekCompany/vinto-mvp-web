"""RB-CRIA-01: crear N crías auditables para UNA captura P1-07 versión 3+.

La madre es una etiqueta DECLARADA (opción A), no una FK a bobina F3.
Cada cría se crea con su UUID y una fila quality_release pending en la MISMA
transacción de captura; sin numeración industrial inventada ni bobbin_relation.
El lock/idempotencia de capture_id lo impone capture_service antes de entrar.
"""
from decimal import Decimal

from app.capture_errors import CaptureValidationError

P107 = "VINTO-P1-07"
POSITIONS = (*range(1, 12), *range(13, 23))


def create_children(connection, *, capture_id, form_version_id, machine_id, assignment_id, clean):
    version = connection.execute(
        "SELECT version_number FROM vinto_config.form_version WHERE id=%s",
        (form_version_id,),
    ).fetchone()
    # No reinterpretar ni migrar silenciosamente las capturas históricas v1/v2.
    if version is None or version[0] < 3:
        return

    mother = clean.get("etiqueta_numero_de_bobina")
    if not isinstance(mother, str) or not mother.strip():
        raise CaptureValidationError("etiqueta_numero_de_bobina: obligatoria")
    mother = mother.strip()

    article = connection.execute(
        """SELECT l.article_version_id FROM vinto_txn.assignment a
           JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
           WHERE a.id=%s AND a.machine_id=%s""",
        (assignment_id, machine_id),
    ).fetchone()
    if article is None or article[0] is None:
        raise CaptureValidationError("La línea de OT no tiene artículo")

    entries = []
    for position in POSITIONS:
        key = f"peso_cria_{position}"
        weight = clean.get(key)
        if weight is None:
            continue
        if not isinstance(weight, Decimal) or not weight.is_finite() or weight <= 0:
            raise CaptureValidationError(f"{key}: debe ser un peso mayor que cero")
        entries.append((position, weight))

    if not entries or entries[0][0] != 1:
        raise CaptureValidationError("peso_cria_1: obligatorio")

    for position, weight in entries:
        # Código exclusivamente técnico estable; el UI muestra "Cría N", nunca
        # este UUID como supuesto correlativo comercial. No consume bobbin_sequence.
        code = f"CRIA-{capture_id.hex}-{position}"
        child = connection.execute(
            """INSERT INTO vinto_txn.bobbin
               (code, source_capture_id, article_version_id, machine_id,
                weight_kg, start_time, end_time, diameter_mm,
                rewind_child_position, rewind_mother_label)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (code, capture_id, article[0], machine_id, weight,
             clean["hora_inicio"], clean["hora_fin"], clean["diametro"],
             position, mother),
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO vinto_txn.quality_release (bobbin_id, status)
               VALUES (%s, 'pending')""",
            (child,),
        )

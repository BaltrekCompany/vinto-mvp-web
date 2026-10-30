"""Unicidad de un campo manual dentro de una OT y una máquina (MF-12B): VINTO-P1-16 v3+, «numero_correlativo».

Regla funcional (VINTO): el correlativo sigue siendo manual y obligatorio; dos capturas distintas de P1-16 v3 de la MISMA OT y la MISMA máquina no pueden compartirlo. Entre OT o máquinas distintas se
permite repetirlo. No entran la fecha ni el turno. La OT y la máquina salen de la ASIGNACIÓN central (nunca de lo que envía el cliente). Las versiones anteriores (v1 y v2) no se evalúan ni se reinterpretan.

Garantía bajo concurrencia, con lo que ya existe (sin migraciones, índices, triggers ni privilegios nuevos): `capture_service.submit_production_capture` toma, dentro de la transacción de la captura y ANTES de
validar, el lock consultivo de transacción de la MÁQUINA de la asignación (`pg_advisory_xact_lock`, el mismo que usan activate/finish). Dos capturas de la misma máquina —y por tanto del mismo ámbito
OT + máquina— nunca ejecutan este control a la vez: la segunda espera al COMMIT de la primera y, en READ COMMITTED, su consulta ya ve la fila confirmada. El control y el INSERT ocurren en esa misma transacción.
No es una restricción declarativa de la base: solo cubre a quien crea capturas de producción por `submit_production_capture` (el único camino que crea P1-16); una inserción directa por SQL no queda cubierta.

El reintento idempotente (mismo capture_id) se resuelve ANTES de llegar aquí y no se ve afectado.
"""

# código de formulario -> (primera versión a la que aplica, clave del campo único)
RULES = {"VINTO-P1-16": (3, "numero_correlativo")}

_TAKEN_SQL = """
    SELECT 1
    FROM vinto_txn.capture c
    JOIN vinto_config.form_version fv ON fv.id = c.form_version_id
    JOIN vinto_config.form f ON f.id = fv.form_id
    JOIN vinto_txn.assignment a ON a.id = c.assignment_id
    JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
    JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
    JOIN vinto_txn.capture_detail d ON d.capture_id = c.id
    JOIN vinto_config.field_definition fd ON fd.id = d.field_definition_id
    WHERE f.code = %s AND fv.version_number >= %s AND c.machine_id = %s AND v.work_order_id = %s
      AND c.status IN ('submitted', 'closed') AND fd.key = %s AND d.value_text = %s
    LIMIT 1"""


def work_order_of(connection, assignment_id):
    """Id de la OT de la asignación (a través de su línea y versión de OT)."""
    row = connection.execute(
        """SELECT v.work_order_id FROM vinto_txn.assignment a JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
           JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id WHERE a.id = %s""", (assignment_id,)).fetchone()
    return None if row is None else row[0]


def is_taken(connection, form_code, machine_id, work_order_id, value) -> bool:
    """¿Existe ya una captura confirmada de v3+ de ese formulario con ese valor en esa OT y esa máquina? Debe llamarse con el lock de la máquina tomado."""
    rule = RULES[form_code]
    return connection.execute(_TAKEN_SQL, (form_code, rule[0], machine_id, work_order_id, rule[1], value)).fetchone() is not None


def applies(form_code, version_number) -> bool:
    rule = RULES.get(form_code)
    return rule is not None and version_number >= rule[0]

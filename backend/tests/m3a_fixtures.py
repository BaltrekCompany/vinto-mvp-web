"""M3-A test-only fixtures: a SYNTHETIC production form with simple fields and repeatable groups, installed ONLY in ephemeral *_test databases.

It is not a real VINTO form, it is not part of backend/seed_data and its code is never added to the real policy (capture_service.CENTRAL_FORM_CODES): tests enable it
per test with patch.object. The limits (min_rows/max_rows/repeatable) are the ones declared in the definition below; no industrial limit is invented anywhere.
"""

import hashlib

GROUPED_CODE = "VINTO-TEST-GRP-1"

# Simple fields: key, label, type, required, options
SIMPLE_FIELDS = (
    ("lote", "Lote", "text", True, ()),
    ("nota", "Nota", "textarea", False, ()),
)
# Groups: code, label, repeatable, min_rows, max_rows, fields (key, label, type, required, options)
GROUPS = (
    ("detalle", "Detalle", True, 1, 3, (
        ("item", "Ítem", "text", True, ()),
        ("cantidad", "Cantidad", "integer", True, ()),
        ("peso", "Peso", "decimal", False, ()),
        ("tipo", "Tipo", "text", False, ("a", "b")),
    )),
    ("extras", "Extras", True, 0, None, (  # minimum zero, no declared maximum (only the technical cap applies)
        ("etiqueta", "Etiqueta", "text", True, ()),
        ("valor", "Valor", "decimal", False, ()),
    )),
    ("unico", "Único", False, 0, 1, (  # NOT repeatable
        ("ref", "Referencia", "text", True, ()),
    )),
)
VALID = {
    "lote": "L-001", "nota": "sintético",
    "_groups": {
        "detalle": [{"item": "A", "cantidad": 2, "peso": "1.50", "tipo": "a"}, {"item": "B", "cantidad": 5}],
        "extras": [{"etiqueta": "x", "valor": "0.10"}],
    },
}


def install_grouped_form(connection, code=GROUPED_CODE, *, machine_codes=("MP1", "MP3"), simple_fields=SIMPLE_FIELDS, groups=GROUPS, publish=True):
    """Create form + version + simple fields + groups with their fields + machine links; returns the form_version id."""
    workflow = connection.execute("SELECT workflow_id FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = 'VINTO-P1-06' LIMIT 1").fetchone()[0]
    form_id = connection.execute("INSERT INTO vinto_config.form (legacy_key, code) VALUES (%s, %s) RETURNING id", (f"synthetic_{code}", code)).fetchone()[0]
    version = connection.execute(
        """INSERT INTO vinto_config.form_version (form_id, version_number, name, area, workflow_id, definition_checksum)
           VALUES (%s, 1, %s, 'production', %s, %s) RETURNING id""", (form_id, f"Formulario sintético agrupado {code}", workflow, hashlib.sha256(code.encode()).hexdigest())).fetchone()[0]
    order = 0

    def add_field(key, label, kind, required, options, group_id=None):
        nonlocal order
        order += 1
        field_id = connection.execute(
            """INSERT INTO vinto_config.field_definition (form_version_id, field_group_id, key, label, value_type, source, required, display_order)
               VALUES (%s, %s, %s, %s, %s, 'manual', %s, %s) RETURNING id""", (version, group_id, key, label, kind, required, order)).fetchone()[0]
        for position, option in enumerate(options, start=1):
            connection.execute("INSERT INTO vinto_config.field_option (form_version_id, field_definition_id, option_key, label, display_order) VALUES (%s,%s,%s,%s,%s)",
                               (version, field_id, option, option.title(), position))

    for key, label, kind, required, options in simple_fields:
        add_field(key, label, kind, required, options)
    for position, (group_code, group_label, repeatable, min_rows, max_rows, fields) in enumerate(groups, start=1):
        group_id = connection.execute(
            """INSERT INTO vinto_config.field_group (form_version_id, code, label, display_order, repeatable, min_rows, max_rows)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""", (version, group_code, group_label, position, repeatable, min_rows, max_rows)).fetchone()[0]
        for key, label, kind, required, options in fields:
            add_field(key, label, kind, required, options, group_id)
    for machine in machine_codes:
        connection.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT %s, id FROM vinto_master.machine WHERE code = %s", (version, machine))
    if publish:
        connection.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (version,))
    return version

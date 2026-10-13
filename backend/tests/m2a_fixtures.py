"""Synthetic production-form fixtures for M2-A (multiform capture engine). TEST ONLY.

These helpers install a minimal form definition into an EPHEMERAL *_test database (copied from the migrated reference template). They are never
part of backend/seed_data, never installed in vinto, and the synthetic codes are never added to the real policy (capture_service.CENTRAL_FORM_CODES):
tests that need the second form enable it with `patch.object(capture_service, "CENTRAL_FORM_CODES", ...)` for the duration of the test only.
"""

import hashlib

SYNTHETIC_CODE = "VINTO-TEST-PROD-X1"        # production area, enabled by the tests that exercise the second form
SYNTHETIC_QUALITY_CODE = "VINTO-TEST-QUAL-X1"  # quality area: must NEVER be reachable through the production API
SYNTHETIC_VALUES = {"codigo_lote": "LOTE-001", "unidades": 12, "peso_kg": "34.250", "tipo": "alfa", "observaciones": "sintetico"}

# key, label, value_type, required, options
_FIELDS = (
    ("codigo_lote", "Código de lote", "text", True, ()),
    ("unidades", "Unidades", "integer", True, ()),
    ("peso_kg", "Peso", "decimal", True, ()),
    ("tipo", "Tipo", "text", True, ("alfa", "beta")),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
_QUALITY_FIELDS = (("nota", "Nota", "text", False, ()),)  # all optional: the test inserts a bare capture row


def install_production_form(connection, code=SYNTHETIC_CODE, *, machine_codes=("MP1", "MP3"), area="production", publish=True, fields=None):
    """Create form + version + fields (+options) + machine links in the ephemeral database; returns the form_version id."""
    fields = fields if fields is not None else (_FIELDS if area == "production" else _QUALITY_FIELDS)
    workflow = connection.execute("SELECT workflow_id FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = 'VINTO-P1-06' LIMIT 1").fetchone()[0]
    form_id = connection.execute("INSERT INTO vinto_config.form (legacy_key, code) VALUES (%s, %s) RETURNING id", (f"synthetic_{code}", code)).fetchone()[0]
    version = connection.execute(
        """INSERT INTO vinto_config.form_version (form_id, version_number, name, area, workflow_id, definition_checksum)
           VALUES (%s, 1, %s, %s, %s, %s) RETURNING id""",
        (form_id, f"Formulario sintético {code}", area, workflow, hashlib.sha256(code.encode()).hexdigest())).fetchone()[0]
    for order, (key, label, kind, required, options) in enumerate(fields, start=1):
        field_id = connection.execute(
            """INSERT INTO vinto_config.field_definition (form_version_id, key, label, value_type, source, required, display_order)
               VALUES (%s, %s, %s, %s, 'manual', %s, %s) RETURNING id""", (version, key, label, kind, required, order)).fetchone()[0]
        for position, option in enumerate(options, start=1):
            connection.execute("INSERT INTO vinto_config.field_option (form_version_id, field_definition_id, option_key, label, display_order) VALUES (%s,%s,%s,%s,%s)",
                               (version, field_id, option, option.title(), position))
    for machine in machine_codes:
        connection.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT %s, id FROM vinto_master.machine WHERE code = %s", (version, machine))
    if publish:
        connection.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (version,))
    return version

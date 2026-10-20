"""M2-B2 test-only fixtures: a FICTITIOUS Rebobinado context and a CANDIDATE technical definition of VINTO-P1-10, installed ONLY in ephemeral *_test databases.

Nothing here is approved by VINTO and nothing here is part of backend/seed_data or of the real configuration:
- the REBOBINADO sector, the COPASA machine and the two shifts below are invented for tests (the shifts and hours are NOT the real ones, which are unconfirmed);
- the P1-10 definition keeps ONLY the four manual fields of the legacy definition, all as text/textarea exactly as declared (no ranges, formats or uniqueness);
- the contextual fields (fecha, maquina, responsable, firma) are NOT stored: the date and machine come from the assignment, and responsable/firma stay pending decisions;
- enabling the sector and the form is done per test with patch.object (sectors._OPERATIONAL, capture_service.CENTRAL_FORM_CODES), never in the shipped configuration.
"""

try:
    from m2a_fixtures import install_production_form
except ModuleNotFoundError:
    from tests.m2a_fixtures import install_production_form

# CLOUD-DEP G.12-C4-COMPLETE: VINTO-P1-10/REBOBINADO/COPASA son ahora códigos REALES (formulario, sector
# y máquina genuinamente publicados en backend/seed_data); esta fixture usa códigos sintéticos ZZFIX* para
# no chocar con ellos (UNIQUE(form.code) / UNIQUE(sector.code) / UNIQUE(machine.code)).
P110_CODE = "ZZFIX-P1-10"
REB_SECTOR = "ZZFIX_REBOBINADO"
REB_MACHINE = "ZZFIX_COPASA"  # the only machine of the legacy definition (allowedMachineIds: copasa); the real machine list is a pending decision
ENABLED_SECTORS = ("BOBINAS", REB_SECTOR)  # test-only operational scope

# key, label, value_type, required, options  (labels as in the legacy definition)
P110_FIELDS = (
    ("codigo_numero_de_producto", "Código / número de producto", "text", True, ()),
    ("numero_de_fardo", "Número de fardo", "text", True, ()),
    ("peso_fardo", "Peso fardo", "text", True, ()),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
P110_VALUES = {"codigo_numero_de_producto": "EJEMPLO-PRODUCTO", "numero_de_fardo": "EJEMPLO-000", "peso_fardo": "12,5 (texto de ejemplo)", "observaciones": "Dato de prueba"}


def install_rebobinado_fixture(connection, article_codes):
    """Fictitious sector/machine/shifts for Rebobinado and the article-machine relation for `article_codes` (existing bundle articles)."""
    sector_id = connection.execute("INSERT INTO vinto_master.sector (code, name) VALUES (%s, %s) RETURNING id", (REB_SECTOR, "Rebobinado (prueba)")).fetchone()[0]
    machine_id = connection.execute("INSERT INTO vinto_master.machine (sector_id, code, name) VALUES (%s, %s, %s) RETURNING id", (sector_id, REB_MACHINE, "Copasa (prueba)")).fetchone()[0]
    for code, name, starts, ends in (("FICT_DIA", "Día (ficticio, prueba)", "06:00", "18:00"), ("FICT_NOCHE", "Noche (ficticio, prueba)", "18:00", "06:00")):
        shift_id = connection.execute("INSERT INTO vinto_config.shift (code, name) VALUES (%s, %s) RETURNING id", (code, name)).fetchone()[0]
        connection.execute(
            """INSERT INTO vinto_config.shift_schedule (shift_id, sector_id, starts_at, ends_at, timezone, valid_from)
               VALUES (%s, %s, %s, %s, 'America/La_Paz', DATE '2026-01-01')""", (shift_id, sector_id, starts, ends))
    for article in article_codes:
        connection.execute("INSERT INTO vinto_master.article_machine (article_id, machine_id) SELECT id, %s FROM vinto_master.article WHERE code = %s", (machine_id, article))
    return machine_id


def install_p110(connection):
    """Publish the CANDIDATE P1-10 definition (production area) for the fictitious Rebobinado machine, in this ephemeral database only."""
    return install_production_form(connection, P110_CODE, machine_codes=(REB_MACHINE,), fields=P110_FIELDS)

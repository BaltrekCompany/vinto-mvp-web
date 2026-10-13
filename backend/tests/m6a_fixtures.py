"""M6-A test-only fixtures: a FICTITIOUS Conversión context and a CANDIDATE technical definition of VINTO-P1-16, installed ONLY in ephemeral *_test databases.

Nothing here is approved by VINTO and nothing here is part of backend/seed_data or of the real configuration:
- the CONVERSION sector, the GAMBINI / WALLY machines and the three shifts below are invented for tests; the hours (06-14 / 14-22 / 22-06) are the ones the legacy frontend uses and
  they are TEST HYPOTHESES, not confirmed shifts;
- the P1-16 definition is the interpretation of `WasteCapture` (app/page.tsx): ONE weighing per capture with tipo_merma, origen_merma and peso_merma_kg. It is NOT the legacy P1-16
  definition (kg columns per waste type, correlative, total) and it is NOT an approved contract;
- no correlative, signature, group or total is stored or computed: those are pending VINTO decisions;
- the option keys are technical keys of the candidate (the labels are those of the legacy screen);
- enabling the sector and the form is done per test / per process (patch.object, e2e server), never in the shipped configuration.
"""

try:
    from m2a_fixtures import install_production_form
except ModuleNotFoundError:
    from tests.m2a_fixtures import install_production_form

P116_CODE = "VINTO-P1-16"
CONV_SECTOR = "CONVERSION"
CONV_MACHINE = "GAMBINI"  # representative machine WITH the candidate form
CONV_MACHINE_NO_FORM = "WALLY"  # second machine WITHOUT the form relation (negative scope tests)
ENABLED_CONVERSION_SECTORS = ("BOBINAS", "CONVERSION")  # test-only operational scope

# Hypothesis shifts (as used by the legacy frontend ctx()); fictitious codes so they never collide with other fixtures.
CONV_SHIFTS = (
    ("FICT_CONV_MANANA", "Mañana (ficticio, prueba)", "06:00", "14:00"),
    ("FICT_CONV_TARDE", "Tarde (ficticio, prueba)", "14:00", "22:00"),
    ("FICT_CONV_NOCHE", "Noche (ficticio, prueba)", "22:00", "06:00"),
)

TIPO_OPTIONS = (("hoja_doble", "Hoja doble"), ("hoja_simple", "Hoja simple"), ("servilleta", "Servilleta"), ("toalla", "Toalla"), ("carton", "Cartón"), ("plastico", "Plástico"))
ORIGEN_OPTIONS = (("logs", "Logs"), ("cola", "Cola"), ("maquina", "Máquina"))

# key, label, value_type, required, option keys  (the labels of the options are set by install_p116)
P116_FIELDS = (
    ("tipo_merma", "Tipo de merma", "text", True, tuple(key for key, _ in TIPO_OPTIONS)),
    ("origen_merma", "Origen de la merma", "text", True, tuple(key for key, _ in ORIGEN_OPTIONS)),
    ("peso_merma_kg", "Peso real (kg)", "decimal", True, ()),
)
P116_VALUES = {"tipo_merma": "hoja_doble", "origen_merma": "logs", "peso_merma_kg": "12.500"}  # FICTITIOUS demonstration weighing


def install_conversion_fixture(connection, article_codes):
    """Fictitious sector/machines/shifts for Conversión and the article-machine relation for `article_codes` (existing bundle articles) on BOTH machines."""
    sector_id = connection.execute("INSERT INTO vinto_master.sector (code, name) VALUES (%s, %s) RETURNING id", (CONV_SECTOR, "Conversión (prueba)")).fetchone()[0]
    machine_ids = []
    for code, name in ((CONV_MACHINE, "Gambini (prueba)"), (CONV_MACHINE_NO_FORM, "Wally (prueba)")):
        machine_id = connection.execute("INSERT INTO vinto_master.machine (sector_id, code, name) VALUES (%s, %s, %s) RETURNING id", (sector_id, code, name)).fetchone()[0]
        machine_ids.append(machine_id)
        for article in article_codes:
            connection.execute("INSERT INTO vinto_master.article_machine (article_id, machine_id) SELECT id, %s FROM vinto_master.article WHERE code = %s", (machine_id, article))
    for code, name, starts, ends in CONV_SHIFTS:
        shift_id = connection.execute("INSERT INTO vinto_config.shift (code, name) VALUES (%s, %s) RETURNING id", (code, name)).fetchone()[0]
        connection.execute(
            """INSERT INTO vinto_config.shift_schedule (shift_id, sector_id, starts_at, ends_at, timezone, valid_from)
               VALUES (%s, %s, %s, %s, 'America/La_Paz', DATE '2026-01-01')""", (shift_id, sector_id, starts, ends))
    return machine_ids


def install_p116(connection, *, publish=True):
    """Publish the CANDIDATE P1-16 definition (production area) for the fictitious GAMBINI machine only, in this ephemeral database only."""
    version = install_production_form(connection, P116_CODE, machine_codes=(CONV_MACHINE,), fields=P116_FIELDS, publish=False)  # published AFTER the labels (published versions are immutable)
    connection.execute("UPDATE vinto_config.form_version SET name = 'Registro de control de merma (candidato M6-A)' WHERE id = %s", (version,))
    for field_key, options in (("tipo_merma", TIPO_OPTIONS), ("origen_merma", ORIGEN_OPTIONS)):
        for key, label in options:
            connection.execute(
                """UPDATE vinto_config.field_option o SET label = %s FROM vinto_config.field_definition f
                   WHERE o.field_definition_id = f.id AND f.form_version_id = %s AND f.key = %s AND o.option_key = %s""", (label, version, field_key, key))
    if publish:
        connection.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (version,))
    return version

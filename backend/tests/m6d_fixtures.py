"""M6-D test-only fixtures: a CANDIDATE technical definition of VINTO-P1-11 (one repeatable group of DECLARED coils), installed ONLY in ephemeral *_test databases.

It reuses the FICTITIOUS Conversión context of M6-A (tests/m6a_fixtures.py: sector, GAMBINI / WALLY, three hypothesis shifts) and links P1-11 to GAMBINI only. Nothing here is approved by VINTO and
nothing is part of backend/seed_data or of the real configuration:
- the P1-11 definition is a TEST HYPOTHESIS: ONE repeatable group `bobinas` (declared coil number, declared position superior/inferior and three declared balances) plus optional observaciones.
  It is NOT the legacy definition (61 fields, 22 calculated) and it is NOT the three fixed rows of the legacy screen;
- `min_rows = 1`, `max_rows = NULL` and the two positions are decisions of this candidate contract only (not industrial rules); the only upper bound is the engine's TECHNICAL cap (1000 rows);
- the coil numbers and the balances are declarations: no consumption, balance, merma, inventory movement or relation with a real bobbin is stored or computed;
- enabling the sector and the form is done per test / per process (patch.object, e2e server with E2E_P111=on), never in the shipped configuration.
"""

try:
    from m2a_fixtures import install_production_form
    from m3a_fixtures import install_grouped_form
    from m6a_fixtures import CONV_MACHINE
except ModuleNotFoundError:
    from tests.m2a_fixtures import install_production_form
    from tests.m3a_fixtures import install_grouped_form
    from tests.m6a_fixtures import CONV_MACHINE

P111_CODE = "VINTO-P1-11"
P111_DRAFT_CODE = "VINTO-TEST-P111-DRAFT"  # linked to GAMBINI but NEVER published: it must not be offered or accepted
P111_MACHINE = CONV_MACHINE  # GAMBINI

P111_SIMPLE_FIELDS = (("observaciones", "Observaciones", "textarea", False, ()),)
# Groups: code, label, repeatable, min_rows, max_rows, fields (key, label, type, required, options)
P111_GROUPS = (
    ("bobinas", "Bobinas declaradas", True, 1, None, (
        ("numero_bobina", "N.º de bobina (declarado)", "text", True, ()),
        ("posicion", "Posición (declarada)", "text", True, ("superior", "inferior")),
        ("saldo_inicial_kg", "Saldo inicial declarado", "decimal", True, ()),
        ("ingreso_kg", "Ingreso declarado", "decimal", True, ()),
        ("saldo_final_kg", "Saldo final declarado", "decimal", True, ()),
    )),
)
# FICTITIOUS demonstration capture. Row 2 repeats the position of row 1 and declares a final balance GREATER than the initial one: no industrial rule forbids either, and nothing is calculated.
P111_ROWS = (
    {"numero_bobina": "BOBINA-FICTICIA-001", "posicion": "superior", "saldo_inicial_kg": "100.5", "ingreso_kg": "20", "saldo_final_kg": "60.25"},
    {"numero_bobina": "BOBINA-FICTICIA-002", "posicion": "superior", "saldo_inicial_kg": "10", "ingreso_kg": "0", "saldo_final_kg": "150.125"},
    {"numero_bobina": "BOBINA-FICTICIA-003", "posicion": "inferior", "saldo_inicial_kg": "0", "ingreso_kg": "5.5", "saldo_final_kg": "3"},
)
P111_VALUES = {"observaciones": "Dato de prueba", "_groups": {"bobinas": [dict(row) for row in P111_ROWS]}}


def _publish_renamed(connection, version, name):
    connection.execute("UPDATE vinto_config.form_version SET name = %s WHERE id = %s", (name, version))
    connection.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (version,))


def install_p111(connection, *, publish=True):
    """Publish the CANDIDATE P1-11 definition (production area, one repeatable group) for the fictitious GAMBINI machine only, in this ephemeral database only."""
    version = install_grouped_form(connection, P111_CODE, machine_codes=(P111_MACHINE,), simple_fields=P111_SIMPLE_FIELDS, groups=P111_GROUPS, publish=False)  # published after the rename (published versions are immutable)
    if publish:
        _publish_renamed(connection, version, "Consumo de bobinas (candidato M6-D)")
    return version


def install_p111_draft(connection):
    """A form linked to GAMBINI whose only version is a DRAFT: negative fixture for 'formulario no publicado'."""
    return install_grouped_form(connection, P111_DRAFT_CODE, machine_codes=(P111_MACHINE,), simple_fields=P111_SIMPLE_FIELDS, groups=P111_GROUPS, publish=False)

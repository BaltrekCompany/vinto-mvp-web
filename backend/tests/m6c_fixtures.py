"""M6-C test-only fixtures: a CANDIDATE technical definition of VINTO-P1-13 (declared coil + one pallet), installed ONLY in ephemeral *_test databases.

It reuses the FICTITIOUS Conversión context of M6-A (tests/m6a_fixtures.py: sector, GAMBINI / WALLY, three hypothesis shifts) and links P1-13 to WALLY only. Nothing here is approved by VINTO and
nothing is part of backend/seed_data or of the real configuration:
- the P1-13 definition is the interpretation of `NapkinSheet` (app/page.tsx): a DECLARED coil number, three DECLARED balances, one pallet (jabas, start and end hour) and optional observations.
  It is NOT the legacy definition (31 fields) and it is NOT an approved contract;
- the balances and the coil number are declarations: no consumption, balance, inventory movement or relation with a real bobbin is stored or computed;
- no pallet number, nominal weight, total weight, recipe, correlative, signature or group is stored or computed (docs/M6-C-conversion-p113.md);
- enabling the sector and the form is done per test / per process (patch.object, e2e server with E2E_P113=on), never in the shipped configuration.
"""

try:
    from m2a_fixtures import install_production_form
    from m6a_fixtures import CONV_MACHINE_NO_FORM
except ModuleNotFoundError:
    from tests.m2a_fixtures import install_production_form
    from tests.m6a_fixtures import CONV_MACHINE_NO_FORM

P113_CODE = "ZZFIX-P1-13"  # CLOUD-DEP G.12-C4-FINAL25: VINTO-P1-13 ya es real
P113_DRAFT_CODE = "VINTO-TEST-P113-DRAFT"  # linked to WALLY but NEVER published: it must not be offered or accepted
P113_MACHINE = CONV_MACHINE_NO_FORM  # WALLY: in M6-A/M6-B it is the machine WITHOUT forms; only with P1-13 installed (E2E_P113=on / this module) does it offer P1-13

# key, label, value_type, required, options
P113_FIELDS = (
    ("numero_bobina", "N.º de bobina (declarado)", "text", True, ()),
    ("saldo_inicial_kg", "Saldo inicial declarado", "decimal", True, ()),
    ("ingreso_kg", "Ingreso declarado", "decimal", True, ()),
    ("saldo_final_kg", "Saldo final declarado", "decimal", True, ()),
    ("cantidad_jabas", "Cantidad de jabas", "integer", True, ()),
    ("hora_inicio", "Hora inicio del pallet", "time", True, ()),
    ("hora_fin", "Hora fin del pallet", "time", True, ()),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
# FICTITIOUS demonstration capture. The final balance is deliberately GREATER than the initial one: no industrial rule forbids it and nothing is calculated.
P113_VALUES = {"numero_bobina": "BOBINA-FICTICIA-001", "saldo_inicial_kg": "100.5", "ingreso_kg": "20", "saldo_final_kg": "150.25",
               "cantidad_jabas": 40, "hora_inicio": "08:15", "hora_fin": "09:05", "observaciones": "Dato de prueba"}


def install_p113(connection, *, publish=True):
    """Publish the CANDIDATE P1-13 definition (production area) for the fictitious WALLY machine only, in this ephemeral database only."""
    version = install_production_form(connection, P113_CODE, machine_codes=(P113_MACHINE,), fields=P113_FIELDS, publish=False)  # published after the rename (published versions are immutable)
    connection.execute("UPDATE vinto_config.form_version SET name = 'Producción diaria de servilletas y especiales (candidato M6-C)' WHERE id = %s", (version,))
    if publish:
        connection.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (version,))
    return version


def install_p113_draft(connection):
    """A form linked to WALLY whose only version is a DRAFT: negative fixture for 'formulario no publicado'."""
    return install_production_form(connection, P113_DRAFT_CODE, machine_codes=(P113_MACHINE,), fields=P113_FIELDS, publish=False)

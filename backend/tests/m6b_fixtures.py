"""M6-B test-only fixtures: a CANDIDATE technical definition of VINTO-P1-12 (one pallet per capture), installed ONLY in ephemeral *_test databases.

It reuses the FICTITIOUS Conversión context of M6-A (tests/m6a_fixtures.py: sector, GAMBINI / WALLY, three hypothesis shifts) and keeps P1-16 installed beside it. Nothing here is approved by VINTO
and nothing is part of backend/seed_data or of the real configuration:
- the P1-12 definition is the interpretation of `PalletProduction` (app/page.tsx): ONE pallet per capture with cantidad_jabas, hora_inicio and hora_fin. It is NOT the legacy definition
  (37 fields: balances of empaque / subempaque / bolsa / segundas / asas, mermas and total) and it is NOT an approved contract;
- no pallet number, nominal weight, total weight, correlative, signature or group is stored or computed: those are pending VINTO decisions (docs/M6-B-conversion-p112.md);
- enabling the sector and the forms is done per test / per process (patch.object, e2e server), never in the shipped configuration.
"""

try:
    from m2a_fixtures import install_production_form
    from m6a_fixtures import CONV_MACHINE
except ModuleNotFoundError:
    from tests.m2a_fixtures import install_production_form
    from tests.m6a_fixtures import CONV_MACHINE

P112_CODE = "VINTO-P1-12"
P112_DRAFT_CODE = "VINTO-TEST-P112-DRAFT"  # linked to GAMBINI but NEVER published: it must not be offered or accepted

# key, label, value_type, required, options
P112_FIELDS = (
    ("cantidad_jabas", "Cantidad de jabas", "integer", True, ()),
    ("hora_inicio", "Hora inicio del pallet", "time", True, ()),
    ("hora_fin", "Hora fin del pallet", "time", True, ()),
)
P112_VALUES = {"cantidad_jabas": 40, "hora_inicio": "08:15", "hora_fin": "09:05"}  # FICTITIOUS demonstration pallet


def install_p112(connection, *, publish=True):
    """Publish the CANDIDATE P1-12 definition (production area) for the fictitious GAMBINI machine only, in this ephemeral database only."""
    version = install_production_form(connection, P112_CODE, machine_codes=(CONV_MACHINE,), fields=P112_FIELDS, publish=False)  # published after the rename (published versions are immutable)
    connection.execute("UPDATE vinto_config.form_version SET name = 'Producción diaria de papel higiénico (candidato M6-B)' WHERE id = %s", (version,))
    if publish:
        connection.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (version,))
    return version


def install_p112_draft(connection):
    """A form linked to GAMBINI whose only version is a DRAFT: negative fixture for 'formulario no publicado'."""
    return install_production_form(connection, P112_DRAFT_CODE, machine_codes=(CONV_MACHINE,), fields=P112_FIELDS, publish=False)

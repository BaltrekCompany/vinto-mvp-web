"""DEV-Q1 test-only fixtures: CANDIDATE technical definitions of VINTO-P1-22 (Grado de refinación Schopper) and VINTO-P1-26 (Medición de secos), AREA QUALITY, for the Bobinas machines MP1 / MP3,
installed ONLY in ephemeral *_test databases.

Only the MANUAL fields of the legacy definitions are installed, with their keys, order, types and requirement: P1-22 (10 fields = 6 manual + 4 automatic: fecha, hora, maquina, responsable) and
P1-26 (9 fields = 4 manual + 4 automatic + 1 calculated: porcentaje_de_secos). The automatic fields are resolved by the backend (machine, shift, operating date, registering user) and the calculated
one is NOT stored: no formula is approved. No range, limit, catalog, unit or approval criterion is defined: pending VINTO decisions.
Enabling the forms is done per test / per process (patch.object on machine_capture_service.MACHINE_QUALITY_FORM_CODES), never in the shipped configuration.
"""

try:
    from m2a_fixtures import install_production_form
except ModuleNotFoundError:
    from tests.m2a_fixtures import install_production_form

P122_CODE = "VINTO-P1-22"
P126_CODE = "VINTO-P1-26"
BOBINAS_MACHINES = ("MP1", "MP3")

# key, label, value_type, required, option keys
P122_FIELDS = (
    ("numero_de_cuba", "Número de cuba", "text", True, ()),
    ("masa_humeda", "Masa húmeda", "decimal", True, ()),
    ("volumen_desplazado", "Volumen desplazado", "decimal", True, ()),
    ("grado_de_refinacion_sr", "Grado de refinación °SR", "decimal", True, ()),
    ("amperaje", "Amperaje", "decimal", True, ()),
    ("observacion", "Observación", "textarea", False, ()),
)
P126_FIELDS = (
    ("punto_de_muestreo", "Punto de muestreo", "text", True, ()),
    ("masa_humeda", "Masa húmeda", "decimal", True, ()),
    ("masa_seca", "Masa seca", "decimal", True, ()),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
# FICTITIOUS demonstration values (nothing here is a limit, a catalog entry or a rule)
P122_VALUES = {"numero_de_cuba": "CUBA-EJEMPLO-1", "masa_humeda": "20.5", "volumen_desplazado": "630", "grado_de_refinacion_sr": "28.5", "amperaje": "45.25", "observacion": "dato ficticio DEV-Q1"}
P126_VALUES = {"punto_de_muestreo": "punto ficticio", "masa_humeda": "100.50", "masa_seca": "3.25", "observaciones": "dato ficticio DEV-Q1"}


def _install(connection, code, fields, name, machine_codes, publish):
    version = install_production_form(connection, code, machine_codes=machine_codes, fields=fields, area="quality", publish=False)  # published AFTER the name (published versions are immutable)
    connection.execute("UPDATE vinto_config.form_version SET name = %s WHERE id = %s", (name, version))
    if publish:
        connection.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (version,))
    return version


def install_p122(connection, *, machine_codes=BOBINAS_MACHINES, publish=True):
    """Publish the CANDIDATE P1-22 definition (quality area) for the given Bobinas machines, in this ephemeral database only."""
    return _install(connection, P122_CODE, P122_FIELDS, "Grado de refinación Schopper (candidato DEV-Q1)", machine_codes, publish)


def install_p126(connection, *, machine_codes=BOBINAS_MACHINES, publish=True):
    """Publish the CANDIDATE P1-26 definition (quality area) for the given Bobinas machines, in this ephemeral database only."""
    return _install(connection, P126_CODE, P126_FIELDS, "Medición de secos (candidato DEV-Q1)", machine_codes, publish)

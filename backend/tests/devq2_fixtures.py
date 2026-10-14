"""DEV-Q2 test-only fixtures: CANDIDATE technical definitions of VINTO-P1-18 (Porcentaje de consistencia, machine-level) and VINTO-P1-21 (Perfil de gramaje y humedad, bound to a physical bobbin), AREA QUALITY,
for the Bobinas machines MP1 / MP3, installed ONLY in ephemeral *_test databases.

Only the MANUAL fields of the legacy definitions are installed, with their keys, labels, order, types and requirement: P1-18 (14 fields = 9 manual + 4 automatic + 1 calculated: consistencia) and P1-21
(12 fields = 5 manual + 4 automatic + 3 calculated: humedad, promedio_gramaje, promedio_humedad). The automatic fields are resolved by the backend and the calculated ones are NOT stored: no formula is
approved. No range, limit, catalog, unit or approval criterion is defined: pending VINTO decisions. Enabling the forms is done per test / per process (patch.object on
machine_capture_service.MACHINE_QUALITY_FORM_CODES and capture_service.ENABLED_BOBBIN_CANDIDATE_FORM_CODES), never in the shipped configuration.
"""

try:
    from m2a_fixtures import install_production_form
except ModuleNotFoundError:
    from tests.m2a_fixtures import install_production_form

P118_CODE = "VINTO-P1-18"
P121_CODE = "VINTO-P1-21"
BOBINAS_MACHINES = ("MP1", "MP3")

# key, label, value_type, required, option keys
P118_FIELDS = (
    ("producto", "Producto", "text", True, ()),
    ("numero_de_cuba", "Número de cuba", "text", True, ()),
    ("punto_de_muestreo", "Punto de muestreo", "text", True, ()),
    ("masa_humeda_g", "Masa húmeda g", "decimal", True, ()),
    ("masa_seca_g", "Masa seca g", "decimal", True, ()),
    ("papel_filtro_g", "Papel filtro g", "text", True, ()),
    ("papel_muestra_g", "Papel + muestra g", "text", True, ()),
    ("peso_muestra_g", "Peso muestra g", "decimal", True, ()),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
P121_FIELDS = (
    ("numero_de_bobina", "Número de bobina", "text", True, ()),
    ("posicion_de_perfil", "Posición de perfil", "text", True, ()),
    ("gramaje", "Gramaje", "decimal", True, ()),
    ("peso_seco", "Peso seco", "decimal", True, ()),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
# FICTITIOUS demonstration values (nothing here is a limit, a catalog entry or a rule). The two paper weights of P1-18 are TEXT in the legacy contract and are stored as typed.
P118_VALUES = {"producto": "producto ficticio", "numero_de_cuba": "CUBA-EJEMPLO-2", "punto_de_muestreo": "punto ficticio", "masa_humeda_g": "100.50", "masa_seca_g": "3.25",
               "papel_filtro_g": "1,10 (texto)", "papel_muestra_g": "4.35", "peso_muestra_g": "0.0032", "observaciones": "dato ficticio DEV-Q2"}
P121_VALUES = {"numero_de_bobina": "OVERRIDDEN-BY-THE-BOBBIN-CODE", "posicion_de_perfil": "posición ficticia", "gramaje": "85.5", "peso_seco": "0.250", "observaciones": "dato ficticio DEV-Q2"}


def _install(connection, code, fields, name, machine_codes, publish):
    version = install_production_form(connection, code, machine_codes=machine_codes, fields=fields, area="quality", publish=False)  # published AFTER the name (published versions are immutable)
    connection.execute("UPDATE vinto_config.form_version SET name = %s WHERE id = %s", (name, version))
    if publish:
        connection.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (version,))
    return version


def install_p118(connection, *, machine_codes=BOBINAS_MACHINES, publish=True):
    """Publish the CANDIDATE P1-18 definition (quality area) for the given Bobinas machines, in this ephemeral database only."""
    return _install(connection, P118_CODE, P118_FIELDS, "Porcentaje de consistencia (candidato DEV-Q2)", machine_codes, publish)


def install_p121(connection, *, machine_codes=BOBINAS_MACHINES, publish=True):
    """Publish the CANDIDATE P1-21 definition (quality area) for the given Bobinas machines, in this ephemeral database only."""
    return _install(connection, P121_CODE, P121_FIELDS, "Perfil de gramaje y humedad (candidato DEV-Q2)", machine_codes, publish)

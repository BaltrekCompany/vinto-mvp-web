"""DEV-B1 test-only fixtures: CANDIDATE technical definitions of VINTO-P1-05 (Registro de tubetes) and VINTO-P1-31 (Consumo de químicos) for the Bobinas machines MP1 / MP3, installed ONLY in ephemeral *_test databases.

Nothing here is approved by VINTO and nothing here is part of backend/seed_data or of the real configuration:
- the field keys, labels and value types are the MANUAL fields of the legacy definitions (form_5_registro_de_tubetes: 10 manual + 4 automatic; form_31_consumo_de_quimicos: 9 manual + 3 automatic);
  the automatic fields (fecha, turno, máquina, responsable / responsable_mp1, responsable_mp3) are NOT stored as manual values: the backend resolves context and actor;
- every P1-05 field is text and the P1-31 consumptions are text (as in the legacy definitions); only the two flow rates are decimal. No catalog, formula, density, unit, range, tolerance,
  correlative or inventory rule is defined: pending VINTO decisions;
- enabling the forms is done per test / per process (patch.object on capture_service.CENTRAL_FORM_CODES), never in the shipped configuration.
"""

try:
    from m2a_fixtures import install_production_form
except ModuleNotFoundError:
    from tests.m2a_fixtures import install_production_form

P105_CODE = "VINTO-P1-05"
P131_CODE = "VINTO-P1-31"
BOBINAS_MACHINES = ("MP1", "MP3")

# key, label, value_type, required, option keys
P105_FIELDS = (
    ("numero_de_bobina", "Número de bobina", "text", True, ()),
    ("numero_codigo_de_tubete", "Número / código de tubete", "text", True, ()),
    ("tipo_de_tubete", "Tipo de tubete", "text", True, ()),
    ("cantidad_utilizada", "Cantidad utilizada", "text", True, ()),
    ("cantidad_recuperada", "Cantidad recuperada", "text", True, ()),
    ("cantidad_devuelta", "Cantidad devuelta", "text", True, ()),
    ("estado_del_tubete", "Estado del tubete", "text", True, ()),
    ("procedencia", "Procedencia", "text", True, ()),
    ("destino", "Destino", "text", True, ()),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
P131_FIELDS = (
    ("codigo_de_insumo", "Código de insumo", "text", True, ()),
    ("seccion", "Sección", "text", True, ()),
    ("insumo_quimico", "Insumo químico", "text", True, ()),
    ("caudal_mp1_ml_min", "Caudal MP1 ml/min", "decimal", True, ()),
    ("caudal_mp3_ml_min", "Caudal MP3 ml/min", "decimal", True, ()),
    ("consumo_dia_mp1_kg", "Consumo día MP1 kg", "text", True, ()),
    ("consumo_dia_mp3_kg", "Consumo día MP3 kg", "text", True, ()),
    ("consumo_total_kg", "Consumo total kg", "text", True, ()),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
# FICTITIOUS demonstration values (free text: nothing here is a catalog entry or a rule)
P105_VALUES = {"numero_de_bobina": "B-EJEMPLO-1", "numero_codigo_de_tubete": "TUB-EJEMPLO-9", "tipo_de_tubete": "tipo ficticio", "cantidad_utilizada": "12 (texto de ejemplo)",
               "cantidad_recuperada": "2", "cantidad_devuelta": "0", "estado_del_tubete": "estado ficticio", "procedencia": "procedencia ficticia", "destino": "destino ficticio",
               "observaciones": "dato ficticio DEV-B1"}
P131_VALUES = {"codigo_de_insumo": "INS-EJEMPLO", "seccion": "sección ficticia", "insumo_quimico": "químico ficticio", "caudal_mp1_ml_min": "125.5", "caudal_mp3_ml_min": "98",
               "consumo_dia_mp1_kg": "15,5 (texto)", "consumo_dia_mp3_kg": "12", "consumo_total_kg": "no es la suma", "observaciones": "dato ficticio DEV-B1"}


def _install(connection, code, fields, name, machine_codes, publish):
    version = install_production_form(connection, code, machine_codes=machine_codes, fields=fields, publish=False)  # published AFTER the name (published versions are immutable)
    connection.execute("UPDATE vinto_config.form_version SET name = %s WHERE id = %s", (name, version))
    if publish:
        connection.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (version,))
    return version


def install_p105(connection, *, machine_codes=BOBINAS_MACHINES, publish=True):
    """Publish the CANDIDATE P1-05 definition (production area) for the given Bobinas machines, in this ephemeral database only."""
    return _install(connection, P105_CODE, P105_FIELDS, "Registro de tubetes (candidato DEV-B1)", machine_codes, publish)


def install_p131(connection, *, machine_codes=BOBINAS_MACHINES, publish=True):
    """Publish the CANDIDATE P1-31 definition (production area) for the given Bobinas machines, in this ephemeral database only."""
    return _install(connection, P131_CODE, P131_FIELDS, "Consumo de químicos (candidato DEV-B1)", machine_codes, publish)

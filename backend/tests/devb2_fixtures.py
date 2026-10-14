"""DEV-B2 test-only fixture: a CANDIDATE technical definition of VINTO-P1-04 (Registro de consumo de fibra) for the Bobinas machines MP1 / MP3, installed ONLY in ephemeral *_test databases.

Built from the ORIGINAL definition (form_4_registro_de_consumo_de_fibra: 17 fields), not from the legacy Fiber screen. Only the 9 MANUAL fields are installed, with the original keys, order, types and
requirement (recorte_ph and materia_prima_ph are decimals; the rest text; observaciones optional). The 6 automatic fields (fecha, turno, maquina, operador, hora_inicio, hora_fin) and the 2 calculated
ones (total_kg, total_final) are NOT part of the stored contract: hora_inicio / hora_fin have no confirmed source and no total is calculated. Nothing here is part of backend/seed_data or of the real configuration.
"""

try:
    from devb1_fixtures import BOBINAS_MACHINES, _install
except ModuleNotFoundError:
    from tests.devb1_fixtures import BOBINAS_MACHINES, _install

P104_CODE = "VINTO-P1-04"

# key, label, value_type, required, option keys
P104_FIELDS = (
    ("fibra_corta_detalle", "Fibra corta - detalle", "text", True, ()),
    ("fibra_larga_detalle", "Fibra larga - detalle", "text", True, ()),
    ("recorte_ph", "Recorte PH", "decimal", True, ()),
    ("recorte_servilleta", "Recorte servilleta", "text", True, ()),
    ("recorte_toalla", "Recorte toalla", "text", True, ()),
    ("materia_prima_ph", "Materia prima PH", "decimal", True, ()),
    ("materia_prima_servilleta", "Materia prima servilleta", "text", True, ()),
    ("materia_prima_toalla", "Materia prima toalla", "text", True, ()),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
# FICTITIOUS demonstration values (free text: nothing here is a catalog entry or a rule)
P104_VALUES = {"fibra_corta_detalle": "detalle ficticio corta", "fibra_larga_detalle": "detalle ficticio larga", "recorte_ph": "12.5", "recorte_servilleta": "3 bultos (texto)",
               "recorte_toalla": "2", "materia_prima_ph": "340", "materia_prima_servilleta": "10", "materia_prima_toalla": "7", "observaciones": "dato ficticio DEV-B2"}


def install_p104(connection, *, machine_codes=BOBINAS_MACHINES, publish=True):
    """Publish the CANDIDATE P1-04 definition (production area) for the given Bobinas machines, in this ephemeral database only."""
    return _install(connection, P104_CODE, P104_FIELDS, "Registro de consumo de fibra (candidato DEV-B2)", machine_codes, publish)

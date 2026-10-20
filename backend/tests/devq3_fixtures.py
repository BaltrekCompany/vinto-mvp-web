"""DEV-Q3 test-only fixtures: CANDIDATE technical definitions of VINTO-P1-24 (Propiedades físicas en húmedo) and VINTO-P1-25 (Resistencia en húmedo-curado), AREA QUALITY, bound to a physical bobbin, for the
Bobinas machines MP1 / MP3, installed ONLY in ephemeral *_test databases.

Only the MANUAL fields of the legacy definitions are installed, with their keys, labels, order, types and requirement: P1-24 (18 fields = 12 manual + 4 automatic + 2 calculated) and P1-25 (20 fields = 14
manual + 3 automatic + 3 calculated). The automatic fields are resolved by the backend and the calculated ones are NOT stored: no formula is approved. MP1 / MP3 are used here only as technical test machines:
P1-24 also mentions every rewinder and P1-25 declares its machine scope as `por_definir` (pending VINTO). No range, limit, catalog, unit or approval criterion is defined.
Enabling the forms is done per test (patch.object on capture_service.ENABLED_BOBBIN_CANDIDATE_FORM_CODES), never in the shipped configuration.
"""

try:
    from devq2_fixtures import _install
except ModuleNotFoundError:
    from tests.devq2_fixtures import _install

P124_CODE = "ZZFIX-P1-24"
P125_CODE = "ZZFIX-P1-25"
BOBINAS_MACHINES = ("MP1", "MP3")

# key, label, value_type, required, option keys
P124_FIELDS = (
    ("numero_de_bobina", "Número de bobina", "text", True, ()),
    ("producto", "Producto", "text", True, ()),
    ("crepado", "Crepado", "decimal", True, ()),
    ("gramaje", "Gramaje", "decimal", True, ()),
    ("resistencia_longitudinal_humeda_centro", "Resistencia longitudinal húmeda centro", "decimal", True, ()),
    ("resistencia_longitudinal_humeda_medio", "Resistencia longitudinal húmeda medio", "decimal", True, ()),
    ("resistencia_longitudinal_humeda_extremo", "Resistencia longitudinal húmeda extremo", "decimal", True, ()),
    ("resistencia_transversal_humeda_centro", "Resistencia transversal húmeda centro", "decimal", True, ()),
    ("resistencia_transversal_humeda_medio", "Resistencia transversal húmeda medio", "decimal", True, ()),
    ("resistencia_transversal_humeda_extremo", "Resistencia transversal húmeda extremo", "decimal", True, ()),
    ("tiempo_de_curado_condicion", "Tiempo de curado / condición", "decimal", True, ()),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
P125_FIELDS = (
    ("numero_de_bobina", "Número de bobina", "text", True, ()),
    ("producto", "Producto", "text", True, ()),
    ("crepado", "Crepado", "decimal", True, ()),
    ("gramaje_laboratorio_g_m2", "Gramaje laboratorio g/m²", "decimal", True, ()),
    ("curado_min", "Curado min", "text", True, ()),
    ("resistencia_longitudinal_centro_kgf", "Resistencia longitudinal centro kgf", "decimal", True, ()),
    ("resistencia_longitudinal_medio_kgf", "Resistencia longitudinal medio kgf", "decimal", True, ()),
    ("resistencia_longitudinal_extremo_kgf", "Resistencia longitudinal extremo kgf", "decimal", True, ()),
    ("elongacion_media_longitudinal", "Elongación media longitudinal", "decimal", True, ()),
    ("resistencia_longitudinal_humeda_centro_kgf", "Resistencia longitudinal húmeda centro kgf", "decimal", True, ()),
    ("resistencia_longitudinal_humeda_medio_kgf", "Resistencia longitudinal húmeda medio kgf", "decimal", True, ()),
    ("resistencia_longitudinal_humeda_extremo_kgf", "Resistencia longitudinal húmeda extremo kgf", "decimal", True, ()),
    ("elongacion_media_transversal", "Elongación media transversal", "decimal", True, ()),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
# FICTITIOUS demonstration values (nothing here is a limit, a catalog entry or a rule). `numero_de_bobina` is replaced by the code of the selected bobbin; `curado_min` is TEXT and stored as typed.
P124_VALUES = {"numero_de_bobina": "REPLACED", "producto": "producto ficticio (no es el artículo)", "crepado": "18.5", "gramaje": "21.30", "resistencia_longitudinal_humeda_centro": "120.5",
               "resistencia_longitudinal_humeda_medio": "118", "resistencia_longitudinal_humeda_extremo": "119.25", "resistencia_transversal_humeda_centro": "60.1", "resistencia_transversal_humeda_medio": "59",
               "resistencia_transversal_humeda_extremo": "61.75", "tiempo_de_curado_condicion": "30", "observaciones": "dato ficticio DEV-Q3"}
P125_VALUES = {"numero_de_bobina": "REPLACED", "producto": "producto ficticio", "crepado": "17", "gramaje_laboratorio_g_m2": "20.5", "curado_min": "30 min a 100 °C (texto)",
               "resistencia_longitudinal_centro_kgf": "1.20", "resistencia_longitudinal_medio_kgf": "1.15", "resistencia_longitudinal_extremo_kgf": "1.18", "elongacion_media_longitudinal": "22.4",
               "resistencia_longitudinal_humeda_centro_kgf": "0.45", "resistencia_longitudinal_humeda_medio_kgf": "0.41", "resistencia_longitudinal_humeda_extremo_kgf": "0.43",
               "elongacion_media_transversal": "9.9", "observaciones": "dato ficticio DEV-Q3"}


def install_p124(connection, *, machine_codes=BOBINAS_MACHINES, publish=True):
    """Publish the CANDIDATE P1-24 definition (quality area) for the given Bobinas machines, in this ephemeral database only."""
    return _install(connection, P124_CODE, P124_FIELDS, "Propiedades físicas en húmedo (candidato DEV-Q3)", machine_codes, publish)


def install_p125(connection, *, machine_codes=BOBINAS_MACHINES, publish=True):
    """Publish the CANDIDATE P1-25 definition (quality area) for the given Bobinas machines, in this ephemeral database only."""
    return _install(connection, P125_CODE, P125_FIELDS, "Resistencia en húmedo-curado (candidato DEV-Q3)", machine_codes, publish)

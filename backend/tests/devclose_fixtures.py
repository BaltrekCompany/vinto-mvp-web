"""DEV-CLOSE test-only fixtures: CANDIDATE technical definitions of VINTO-P1-27 (Análisis de agua para caldero, machine-level) and VINTO-P1-28 (Registro de bobinas rechazadas, a DOCUMENTARY sheet bound to a
physical bobbin), AREA QUALITY, for the Bobinas machines MP1 / MP3, installed ONLY in ephemeral *_test databases.

Only the MANUAL fields of the legacy definitions are installed, with their keys, labels, order, types and requirement, generated from lib/vinto/form-definitions.ts: P1-27 (27 fields = 23 manual + 3 automatic +
1 calculated: purga_caldero_alcalinidad_total) and P1-28 (13 fields = 7 manual + 6 automatic). The automatic fields (fecha, turno, responsable / hora, maquina, operador, responsable_de_calidad,
visto_bueno_produccion) and the calculated one are NOT stored: no formula is approved and no signature / approval source exists. P1-27 keeps BOTH condensado MP1 and condensado MP3 in the same contract. No range, limit,
catalog or rule is defined. Enabling the forms is done per test (patch.object on machine_capture_service.MACHINE_QUALITY_FORM_CODES / capture_service.ENABLED_BOBBIN_CANDIDATE_FORM_CODES), never in the shipped configuration.
"""

try:
    from devq2_fixtures import _install
except ModuleNotFoundError:
    from tests.devq2_fixtures import _install

P127_CODE = "ZZFIX-P1-27"
P128_CODE = "ZZFIX-P1-28"
BOBINAS_MACHINES = ("MP1", "MP3")

# key, label, value_type, required, option keys
P127_FIELDS = (
    ("ablandador_ph", "Ablandador pH", "decimal", True, ()),
    ("ablandador_dureza", "Ablandador dureza", "decimal", True, ()),
    ("ablandador_solidos_disueltos", "Ablandador sólidos disueltos", "text", True, ()),
    ("ablandador_conductividad", "Ablandador conductividad", "text", True, ()),
    ("agua_alimentacion_caldero_ph", "Agua alimentación caldero pH", "decimal", True, ()),
    ("agua_alimentacion_caldero_dureza", "Agua alimentación caldero dureza", "decimal", True, ()),
    ("agua_alimentacion_caldero_solidos_disueltos", "Agua alimentación caldero sólidos disueltos", "text", True, ()),
    ("agua_alimentacion_caldero_conductividad", "Agua alimentación caldero conductividad", "text", True, ()),
    ("purga_caldero_ph", "Purga caldero pH", "decimal", True, ()),
    ("purga_caldero_dureza", "Purga caldero dureza", "decimal", True, ()),
    ("purga_caldero_solidos_disueltos", "Purga caldero sólidos disueltos", "text", True, ()),
    ("purga_caldero_conductividad", "Purga caldero conductividad", "text", True, ()),
    ("purga_caldero_cloruros", "Purga caldero cloruros", "text", True, ()),
    ("condensado_mp1_ph", "Condensado MP1 pH", "decimal", True, ()),
    ("condensado_mp1_dureza", "Condensado MP1 dureza", "decimal", True, ()),
    ("condensado_mp1_solidos_disueltos", "Condensado MP1 sólidos disueltos", "text", True, ()),
    ("condensado_mp1_conductividad", "Condensado MP1 conductividad", "text", True, ()),
    ("condensado_mp3_ph", "Condensado MP3 pH", "decimal", True, ()),
    ("condensado_mp3_dureza", "Condensado MP3 dureza", "decimal", True, ()),
    ("condensado_mp3_solidos_disueltos", "Condensado MP3 sólidos disueltos", "text", True, ()),
    ("condensado_mp3_conductividad", "Condensado MP3 conductividad", "text", True, ()),
    ("calibracion_equipo_multiparametro", "Calibración equipo multiparámetro", "text", True, ()),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
P128_FIELDS = (
    ("numero_de_bobina", "Número de bobina", "text", True, ()),
    ("producto", "Producto", "text", True, ()),
    ("detalle_motivo_de_rechazo", "Detalle / motivo de rechazo", "textarea", True, ()),
    ("accion_correctiva", "Acción correctiva", "text", True, ()),
    ("peso_rechazado", "Peso rechazado", "decimal", True, ()),
    ("estado_disposicion_final", "Estado / disposición final", "text", True, ()),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
# FICTITIOUS demonstration values (nothing here is a limit, a catalog entry or a rule). Solids / conductivity / chlorides / calibration are TEXT and stay text. `numero_de_bobina` is replaced by the bobbin code.
P127_VALUES = {}
for _key, _label, _kind, _required, _o in P127_FIELDS:
    P127_VALUES[_key] = "7.25" if _kind == "decimal" and _key.endswith("_ph") else "120.5" if _kind == "decimal" else "dato ficticio DEV-CLOSE" if _kind == "textarea" else f"{_key} (texto, 1.250 µS)"
P128_VALUES = {"numero_de_bobina": "REPLACED", "producto": "producto ficticio (no es el artículo)", "detalle_motivo_de_rechazo": "motivo ficticio\nsegunda línea", "accion_correctiva": "acción ficticia",
               "peso_rechazado": "125.50", "estado_disposicion_final": "rechazado (texto declarado en la ficha)", "observaciones": "dato ficticio DEV-CLOSE"}


def install_p127(connection, *, machine_codes=BOBINAS_MACHINES, publish=True):
    """Publish the CANDIDATE P1-27 definition (quality area) for the given Bobinas machines, in this ephemeral database only."""
    return _install(connection, P127_CODE, P127_FIELDS, "Análisis de agua para caldero (candidato DEV-CLOSE)", machine_codes, publish)


def install_p128(connection, *, machine_codes=BOBINAS_MACHINES, publish=True):
    """Publish the CANDIDATE P1-28 definition (quality area) for the given Bobinas machines, in this ephemeral database only."""
    return _install(connection, P128_CODE, P128_FIELDS, "Registro de bobinas rechazadas (candidato DEV-CLOSE)", machine_codes, publish)

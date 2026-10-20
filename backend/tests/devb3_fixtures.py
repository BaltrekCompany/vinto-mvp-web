"""DEV-B3 test-only fixtures: CANDIDATE technical definitions of VINTO-P1-02 (Parámetros de operación de máquina MP1) and VINTO-P1-01 (Operación e inspección de máquina MP3), installed ONLY in ephemeral
*_test databases for the real Bobinas machines (P1-02 -> MP1, P1-01 -> MP3).

Only the MANUAL fields of the legacy definitions are installed, with their keys, labels, order, types and requirement, generated from lib/vinto/form-definitions.ts: P1-02 (52 fields = 48 manual + 4 automatic) and
P1-01 (93 fields = 86 manual + 7 automatic; the key `opertado` is kept as in the source, three manual `time` fields and several text fields that look numeric: peso_balas_*, tiempo_de_pulpeo_*). The automatic
fields (nombre_operador, fecha, hora, turno, velocidad_maquina, firma_operador, revisado) are NOT stored: the backend resolves the date, the shift and the actor, and velocity / signature / review have no approved
source. No range, limit, catalog, unit conversion or approval rule is defined: pending VINTO decisions. Enabling the forms is done per test (patch.object on capture_service.CENTRAL_FORM_CODES).
"""

try:
    from m2a_fixtures import install_production_form
except ModuleNotFoundError:
    from tests.m2a_fixtures import install_production_form

P102_CODE = "ZZFIX-P1-02"
P101_CODE = "ZZFIX-P1-01"
P102_MACHINES = ("MP1",)
P101_MACHINES = ("MP3",)
TIME_KEYS = ("hora_cambio_cuchilla_de_cambio", "hora_cambio_cuchilla_de_crepado", "hora_cambio_cuchilla_de_limpieza")

# key, label, value_type, required, option keys
P102_FIELDS = (
    ("producto", "Producto", "text", True, ()),
    ("velocidad_cilindro_yankee", "Velocidad cilindro Yankee", "decimal", True, ()),
    ("corriente_cilindro_yankee", "Corriente cilindro Yankee", "decimal", True, ()),
    ("velocidad_prensa", "Velocidad prensa", "decimal", True, ()),
    ("corriente_prensa", "Corriente prensa", "decimal", True, ()),
    ("velocidad_tela", "Velocidad tela", "decimal", True, ()),
    ("corriente_tela", "Corriente tela", "decimal", True, ()),
    ("velocidad_pope", "Velocidad pope", "decimal", True, ()),
    ("corriente_pope", "Corriente pope", "decimal", True, ()),
    ("velocidad_bomba_5", "Velocidad bomba 5", "decimal", True, ()),
    ("corriente_bomba_5", "Corriente bomba 5", "decimal", True, ()),
    ("velocidad_bomba_fan", "Velocidad bomba Fan", "decimal", True, ()),
    ("corriente_bomba_fan", "Corriente bomba Fan", "decimal", True, ()),
    ("velocidad_refinador", "Velocidad refinador", "decimal", True, ()),
    ("corriente_refinador", "Corriente refinador", "decimal", True, ()),
    ("velocidad_safem", "Velocidad Safem", "decimal", True, ()),
    ("corriente_safem", "Corriente Safem", "decimal", True, ()),
    ("vacio_safem", "Vacío Safem", "decimal", True, ()),
    ("vacio_fieltro", "Vacío fieltro", "decimal", True, ()),
    ("vacio_tela", "Vacío tela", "decimal", True, ()),
    ("apertura_gas", "Apertura gas", "text", True, ()),
    ("presion_cilindro_yankee", "Presión cilindro Yankee", "decimal", True, ()),
    ("apertura_termocompresor", "Apertura termocompresor", "text", True, ()),
    ("temperatura_lado_humedo_campana", "Temperatura lado húmedo campana", "decimal", True, ()),
    ("temperatura_lado_seco_campana", "Temperatura lado seco campana", "decimal", True, ()),
    ("gramaje_minimo", "Gramaje mínimo", "decimal", True, ()),
    ("gramaje_medio", "Gramaje medio", "decimal", True, ()),
    ("gramaje_maximo", "Gramaje máximo", "decimal", True, ()),
    ("humedad_minima", "Humedad mínima", "decimal", True, ()),
    ("humedad_media", "Humedad media", "decimal", True, ()),
    ("humedad_maxima", "Humedad máxima", "decimal", True, ()),
    ("peso_seco_minimo", "Peso seco mínimo", "decimal", True, ()),
    ("peso_seco_medio", "Peso seco medio", "decimal", True, ()),
    ("peso_seco_maximo", "Peso seco máximo", "decimal", True, ()),
    ("apertura_valvula_de_gramaje", "Apertura válvula de gramaje", "decimal", True, ()),
    ("relacion_chorro_tela", "Relación chorro/tela", "text", True, ()),
    ("altura_caja_entrada", "Altura caja entrada", "text", True, ()),
    ("apertura_labio", "Apertura labio", "text", True, ()),
    ("dosificacion_release", "Dosificación Release", "text", True, ()),
    ("limpieza_sala_de_control", "Limpieza sala de control", "text", True, ()),
    ("limpieza_pasillo_lado_comando", "Limpieza pasillo lado comando", "text", True, ()),
    ("limpieza_pasillo_lado_transmision", "Limpieza pasillo lado transmisión", "text", True, ()),
    ("limpieza_sotano", "Limpieza sótano", "text", True, ()),
    ("limpieza_escaner", "Limpieza escáner", "text", True, ()),
    ("limpieza_mezzanine", "Limpieza mezzanine", "text", True, ()),
    ("limpieza_enfardadora", "Limpieza enfardadora", "text", True, ()),
    ("limpieza_rectificadora", "Limpieza rectificadora", "text", True, ()),
    ("novedades", "Novedades", "text", True, ()),
)
P101_FIELDS = (
    ("producto_gramaje_crepado", "Producto / gramaje / crepado", "text", True, ()),
    ("nivel_tanque_t_30", "Nivel tanque T-30", "decimal", True, ()),
    ("nivel_tanque_h_1", "Nivel tanque H-1", "decimal", True, ()),
    ("nivel_tanque_h_3", "Nivel tanque H-3", "decimal", True, ()),
    ("peso_balas_fibra_corta", "Peso balas fibra corta", "text", True, ()),
    ("peso_balas_fibra_larga", "Peso balas fibra larga", "text", True, ()),
    ("tiempo_de_pulpeo_fibra_corta", "Tiempo de pulpeo fibra corta", "text", True, ()),
    ("tiempo_de_pulpeo_fibra_larga", "Tiempo de pulpeo fibra larga", "text", True, ()),
    ("nivel_tanque_t_20", "Nivel tanque T-20", "decimal", True, ()),
    ("caudal_b_4", "Caudal B-4", "decimal", True, ()),
    ("caudal_b_7", "Caudal B-7", "decimal", True, ()),
    ("mezcla_fibra_corta_fibra_larga", "Mezcla fibra corta/fibra larga", "text", True, ()),
    ("nivel_tanque_h_20", "Nivel tanque H-20", "decimal", True, ()),
    ("consistencia_h_4", "Consistencia H-4", "decimal", True, ()),
    ("apertura_valvula_consistencia", "Apertura válvula consistencia", "decimal", True, ()),
    ("gramaje_valvula", "Gramaje válvula", "decimal", True, ()),
    ("nivel_tanque_p17", "Nivel tanque P17", "decimal", True, ()),
    ("motor_fan_b23", "Motor Fan B23", "text", True, ()),
    ("motor_fan_b23b", "Motor Fan B23B", "text", True, ()),
    ("nivel_tanque_t_21", "Nivel tanque T-21", "decimal", True, ()),
    ("velocidad_chorro", "Velocidad chorro", "decimal", True, ()),
    ("velocidad_tela", "Velocidad tela", "decimal", True, ()),
    ("error_chorro_tela", "Error chorro/tela", "text", True, ()),
    ("presion_labio", "Presión labio", "decimal", True, ()),
    ("apertura_labio", "Apertura labio", "text", True, ()),
    ("angulo_labio", "Ángulo labio", "text", True, ()),
    ("distancia", "Distancia", "text", True, ()),
    ("presion_entrada_colador", "Presión entrada colador", "decimal", True, ()),
    ("presion_salida_colador", "Presión salida colador", "decimal", True, ()),
    ("apertura_purga", "Apertura purga", "text", True, ()),
    ("dosificacion_release", "Dosificación Release", "text", True, ()),
    ("dosificacion_fosfato", "Dosificación Fosfato", "text", True, ()),
    ("dosificacion_pasiv_tela", "Dosificación Pasiv. tela", "text", True, ()),
    ("dosificacion_pasiv_fieltro", "Dosificación Pasiv. fieltro", "text", True, ()),
    ("bomba_ba1", "Bomba BA1", "text", True, ()),
    ("bomba_ba2", "Bomba BA2", "text", True, ()),
    ("bomba_ba3", "Bomba BA3", "text", True, ()),
    ("presion_cocedores", "Presión cocedores", "decimal", True, ()),
    ("cambio", "Cambio", "text", True, ()),
    ("crepado", "Crepado", "decimal", True, ()),
    ("limpieza", "Limpieza", "text", True, ()),
    ("nivel_tanque_t_30_aguas", "Nivel tanque T-30 aguas", "decimal", True, ()),
    ("nivel_tanque_h_20_aguas", "Nivel tanque H-20 aguas", "decimal", True, ()),
    ("nivel_tanque_t_30_aguas_2", "Nivel tanque T-30 aguas 2", "decimal", True, ()),
    ("nivel_tanque_h_20_aguas_2", "Nivel tanque H-20 aguas 2", "decimal", True, ()),
    ("nivel_tanque_t_30_accionamientos", "Nivel tanque T-30 accionamientos", "decimal", True, ()),
    ("nivel_tanque_h_20_accionamientos", "Nivel tanque H-20 accionamientos", "decimal", True, ()),
    ("opertado", "Opertado", "text", True, ()),
    ("produccion", "Producción", "text", True, ()),
    ("velocidad_fieltro", "Velocidad fieltro", "decimal", True, ()),
    ("velocidad_secador", "Velocidad secador", "decimal", True, ()),
    ("presion_cilindro", "Presión cilindro", "decimal", True, ()),
    ("presion_pope", "Presión pope", "decimal", True, ()),
    ("presion_caldero", "Presión caldero", "decimal", True, ()),
    ("temperatura_lado_seco", "Temperatura lado seco", "decimal", True, ()),
    ("temperatura_lado_humedo", "Temperatura lado húmedo", "decimal", True, ()),
    ("apertura_campana", "Apertura campana", "text", True, ()),
    ("presion_regaderas", "Presión regaderas", "decimal", True, ()),
    ("apertura_purga_prensa", "Apertura purga prensa", "text", True, ()),
    ("presion_aceite_alta_tela", "Presión aceite alta tela", "decimal", True, ()),
    ("presion_aceite_guia_tela", "Presión aceite guía tela", "decimal", True, ()),
    ("presion_aceite_lubricacion", "Presión aceite lubricación", "decimal", True, ()),
    ("presion_agua_prensa", "Presión agua prensa", "decimal", True, ()),
    ("presion_aire_prensa", "Presión aire prensa", "decimal", True, ()),
    ("presion_vacio_prensa", "Presión vacío prensa", "decimal", True, ()),
    ("presion_fuelle_comando", "Presión fuelle comando", "decimal", True, ()),
    ("presion_fuelle_transmision", "Presión fuelle transmisión", "decimal", True, ()),
    ("caudal_agua_sello_1", "Caudal agua sello 1", "decimal", True, ()),
    ("caudal_agua_sello_2", "Caudal agua sello 2", "decimal", True, ()),
    ("caudal_agua_sello_3", "Caudal agua sello 3", "decimal", True, ()),
    ("filtro_agua_prensa", "Filtro agua prensa", "text", True, ()),
    ("filtro_quimicos", "Filtro químicos", "text", True, ()),
    ("rodillos_quimicos", "Rodillos químicos", "text", True, ()),
    ("vacio_prensa", "Vacío prensa", "decimal", True, ()),
    ("vacio_pope", "Vacío pope", "decimal", True, ()),
    ("vacio_fieltro", "Vacío fieltro", "decimal", True, ()),
    ("vacio_tela", "Vacío tela", "decimal", True, ()),
    ("limpieza_sala_de_control", "Limpieza sala de control", "text", True, ()),
    ("limpieza_escalera", "Limpieza escalera", "text", True, ()),
    ("limpieza_mezzanine", "Limpieza mezzanine", "text", True, ()),
    ("limpieza_lado_transmision", "Limpieza lado transmisión", "text", True, ()),
    ("limpieza_pasos_y_escaleras", "Limpieza pasos y escaleras", "text", True, ()),
    ("hora_cambio_cuchilla_de_cambio", "Hora cambio cuchilla de cambio", "time", True, ()),
    ("hora_cambio_cuchilla_de_crepado", "Hora cambio cuchilla de crepado", "time", True, ()),
    ("hora_cambio_cuchilla_de_limpieza", "Hora cambio cuchilla de limpieza", "time", True, ()),
    ("novedades", "Novedades", "text", True, ()),
)


def _values(fields):
    """FICTITIOUS demonstration values: text is free text (a number-looking weight stays text), decimals are plain decimals, times are HH:MM. Nothing here is a limit, a catalog entry or a rule."""
    out = {}
    for n, (key, _label, kind, required, _o) in enumerate(fields):
        if kind == "decimal":
            out[key] = f"{n}.25"
        elif kind == "time":
            out[key] = ("06:30", "14:45", "22:10")[TIME_KEYS.index(key)]
        elif kind == "textarea":
            out[key] = "dato ficticio DEV-B3"
        else:
            out[key] = f"{key} (texto, 12,5)"
    return out


P102_VALUES = _values(P102_FIELDS)
P101_VALUES = {**_values(P101_FIELDS), "peso_balas_fibra_corta": "850,5 kg", "tiempo_de_pulpeo_fibra_corta": "35 min"}


def _install(connection, code, fields, name, machine_codes, publish):
    version = install_production_form(connection, code, machine_codes=machine_codes, fields=fields, publish=False)  # published AFTER the name (published versions are immutable)
    connection.execute("UPDATE vinto_config.form_version SET name = %s WHERE id = %s", (name, version))
    if publish:
        connection.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (version,))
    return version


def install_p102(connection, *, machine_codes=P102_MACHINES, publish=True):
    """Publish the CANDIDATE P1-02 definition (production area) for MP1, in this ephemeral database only."""
    return _install(connection, P102_CODE, P102_FIELDS, "Parámetros de operación de máquina MP1 (candidato DEV-B3)", machine_codes, publish)


def install_p101(connection, *, machine_codes=P101_MACHINES, publish=True):
    """Publish the CANDIDATE P1-01 definition (production area) for MP3, in this ephemeral database only."""
    return _install(connection, P101_CODE, P101_FIELDS, "Operación e inspección de máquina MP3 (candidato DEV-B3)", machine_codes, publish)

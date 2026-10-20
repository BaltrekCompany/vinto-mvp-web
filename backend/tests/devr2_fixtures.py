"""DEV-R2 test-only fixtures: a FICTITIOUS Rebobinado context (sector, machines COPASA / BELOIT / OVER / PERICHUN, shifts) and CANDIDATE technical definitions of VINTO-P1-30 (Producción Perichun) and
VINTO-P1-07 (Registro de producción de bobinas refiladas), installed ONLY in ephemeral *_test databases.

Nothing here is approved by VINTO and nothing here is part of backend/seed_data or of the real configuration (the approved seed only contains MP1 and MP3; REBOBINADO is recognised but NOT operational):
- the sector, the four machines and the two shifts are invented for tests (the real machines and shifts are unconfirmed);
- only the MANUAL fields of the legacy definitions are installed, with their keys, labels, order, types and requirement: P1-30 (15 fields = 10 manual + 5 automatic) and P1-07 (41 fields = 36 manual +
  5 automatic, among them the 21 individual cría weights `peso_cria_1`..`peso_cria_11` and `peso_cria_13`..`peso_cria_22`; there is NO `peso_cria_12`). The automatic fields (fecha, hora_inicio, hora_termino /
  hora_final, turno, operador) are NOT stored: the backend resolves the date, the shift and the actor, and the start / end hours have no approved source;
- no catalog, formula, range, unit conversion, correlative, genealogy or inventory rule is defined: pending VINTO decisions;
- enabling the sector and the forms is done per test with patch.object (sectors._OPERATIONAL, capture_service.CENTRAL_FORM_CODES), never in the shipped configuration.
"""

try:
    from m2a_fixtures import install_production_form
except ModuleNotFoundError:
    from tests.m2a_fixtures import install_production_form

# CLOUD-DEP G.12-C4-COMPLETE: VINTO-P1-07/P1-30, REBOBINADO y COPASA/BELOIT/OVER/PERICHUN son ahora
# códigos REALES (formulario, sector y máquinas genuinamente publicados en backend/seed_data); esta
# fixture usa códigos sintéticos ZZFIX* para no chocar con ellos (UNIQUE(form.code) / UNIQUE(sector.code)
# / UNIQUE(machine.code)).
P130_CODE = "ZZFIX-P1-30"
P107_CODE = "ZZFIX-P1-07"
REB_SECTOR = "ZZFIX_REBOBINADO"
P130_MACHINES = ("ZZFIX_PERICHUN",)
P107_MACHINES = ("ZZFIX_COPASA", "ZZFIX_BELOIT", "ZZFIX_OVER")
REB_MACHINES = P107_MACHINES + P130_MACHINES
ENABLED_SECTORS = ("BOBINAS", REB_SECTOR)  # test-only operational scope

CRIA_NUMBERS = tuple(range(1, 12)) + tuple(range(13, 23))  # 1-11 and 13-22: NO peso_cria_12

# key, label, value_type, required, option keys (labels as in the legacy definition)
P130_FIELDS = (
    ("numero_de_bobina", "Número de bobina", "text", True, ()),
    ("gramaje_g_m2", "Gramaje g/m²", "decimal", True, ()),
    ("peso_de_bobina", "Peso de bobina", "text", True, ()),
    ("formato_mp1", "Formato MP1", "decimal", True, ()),
    ("formato_de_salida", "Formato de salida", "decimal", True, ()),
    ("resistencia_longitudinal", "Resistencia longitudinal", "decimal", True, ()),
    ("resistencia_transversal", "Resistencia transversal", "decimal", True, ()),
    ("numero_mrp", "Número MRP", "text", True, ()),
    ("velocidad", "Velocidad", "decimal", True, ()),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
P107_FIELDS = (
    ("etiqueta_numero_de_bobina", "Etiqueta / número de bobina", "text", True, ()),
    ("peso", "Peso", "decimal", True, ()),
    ("destino", "Destino", "text", True, ()),
    ("producto_refilado", "Producto refilado", "text", True, ()),
    ("auxiliar", "Auxiliar", "text", True, ()),
    ("velocidad_minima", "Velocidad mínima", "decimal", True, ()),
    ("tension", "Tensión", "text", True, ()),
    ("velocidad", "Velocidad", "decimal", True, ()),
    ("metraje", "Metraje", "text", True, ()),
    ("diametro", "Diámetro", "decimal", True, ()),
    ("formato_1", "Formato 1", "decimal", True, ()),
    ("formato_2", "Formato 2", "decimal", True, ()),
    ("formato_3", "Formato 3", "decimal", True, ()),
    ("tubete", "Tubete", "text", True, ()),
) + tuple((f"peso_cria_{n}", f"Peso cría {n}", "decimal", True, ()) for n in CRIA_NUMBERS) + (("observaciones", "Observaciones", "textarea", False, ()),)

# FICTITIOUS demonstration values (free text: nothing here is a catalog entry or a rule). `peso_de_bobina` and `numero_mrp` are TEXT and stored as typed.
P130_VALUES = {"numero_de_bobina": "B-EJEMPLO-30 (texto, no crea bobina)", "gramaje_g_m2": "21.5", "peso_de_bobina": "850,5 kg (texto)", "formato_mp1": "2700", "formato_de_salida": "1350.5",
               "resistencia_longitudinal": "120.25", "resistencia_transversal": "60", "numero_mrp": "MRP-EJEMPLO-9", "velocidad": "310.5", "observaciones": "dato ficticio DEV-R2"}
P107_VALUES = {"etiqueta_numero_de_bobina": "ETQ-EJEMPLO-7 (texto, no es bobina madre)", "peso": "845.25", "destino": "destino ficticio", "producto_refilado": "producto ficticio", "auxiliar": "auxiliar ficticio",
               "velocidad_minima": "100", "tension": "tensión (texto)", "velocidad": "310.5", "metraje": "5000 m (texto)", "diametro": "1200.5", "formato_1": "1350", "formato_2": "1350.5", "formato_3": "1351",
               "tubete": "tubete ficticio", **{f"peso_cria_{n}": f"{n}.25" for n in CRIA_NUMBERS}, "observaciones": "dato ficticio DEV-R2"}


def install_rebobinado_machines(connection, article_codes):
    """Fictitious sector, the four machines and shifts for Rebobinado, plus the article-machine relation for `article_codes` (existing bundle articles)."""
    sector_id = connection.execute("INSERT INTO vinto_master.sector (code, name) VALUES (%s, %s) RETURNING id", (REB_SECTOR, "Rebobinado (prueba DEV-R2)")).fetchone()[0]
    for code in REB_MACHINES:
        machine_id = connection.execute("INSERT INTO vinto_master.machine (sector_id, code, name) VALUES (%s, %s, %s) RETURNING id", (sector_id, code, f"{code.title()} (prueba)")).fetchone()[0]
        for article in article_codes:
            connection.execute("INSERT INTO vinto_master.article_machine (article_id, machine_id) SELECT id, %s FROM vinto_master.article WHERE code = %s", (machine_id, article))
    for code, name, starts, ends in (("FICT_DIA", "Día (ficticio, prueba)", "06:00", "18:00"), ("FICT_NOCHE", "Noche (ficticio, prueba)", "18:00", "06:00")):
        shift_id = connection.execute("INSERT INTO vinto_config.shift (code, name) VALUES (%s, %s) RETURNING id", (code, name)).fetchone()[0]
        connection.execute(
            """INSERT INTO vinto_config.shift_schedule (shift_id, sector_id, starts_at, ends_at, timezone, valid_from)
               VALUES (%s, %s, %s, %s, 'America/La_Paz', DATE '2026-01-01')""", (shift_id, sector_id, starts, ends))


def _install(connection, code, fields, name, machine_codes, publish):
    version = install_production_form(connection, code, machine_codes=machine_codes, fields=fields, publish=False)  # published AFTER the name (published versions are immutable)
    connection.execute("UPDATE vinto_config.form_version SET name = %s WHERE id = %s", (name, version))
    if publish:
        connection.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (version,))
    return version


def install_p130(connection, *, machine_codes=P130_MACHINES, publish=True):
    """Publish the CANDIDATE P1-30 definition (production area) for the fictitious PERICHUN machine, in this ephemeral database only."""
    return _install(connection, P130_CODE, P130_FIELDS, "Producción Perichun (candidato DEV-R2)", machine_codes, publish)


def install_p107(connection, *, machine_codes=P107_MACHINES, publish=True):
    """Publish the CANDIDATE P1-07 definition (production area) for the fictitious COPASA / BELOIT / OVER machines, in this ephemeral database only."""
    return _install(connection, P107_CODE, P107_FIELDS, "Registro de producción de bobinas refiladas (candidato DEV-R2)", machine_codes, publish)

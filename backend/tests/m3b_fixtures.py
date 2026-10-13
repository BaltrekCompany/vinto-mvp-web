"""M3-B test-only fixtures: a CANDIDATE technical definition of VINTO-P1-29 «Producción Tubetera» and a FICTITIOUS Tubetera machine, installed ONLY in ephemeral *_test databases.

Nothing here is approved by VINTO, nothing is part of backend/seed_data or of the real configuration, and the code is never added to the real policy
(capture_service.CENTRAL_FORM_CODES): tests enable it per test with patch.object. The structure is a TECHNICAL PROPOSAL derived from the legacy classification
(docs/M3-B-p1-29-tubetera.md): keys and declared types are the legacy ones (quantities stay TEXT, decimals stay DECIMAL), the three automatic fields (operador, turno,
visto_bueno_responsable) are NOT stored as simulated manual fields, and the fictitious Rebobinado sector/shifts come from tests/m2b2_fixtures.py.

TEST-ONLY HYPOTHESES (not industrial rules, not to be moved to an operational bundle without VINTO's confirmation):
    rodelas : repeatable, min_rows = 1, max_rows = None   -> at least one rodela per lote is assumed only so the minimum can be exercised
    formatos: repeatable, min_rows = 1, max_rows = None   -> at least one format per lote is assumed only so the minimum can be exercised
"""

try:
    from m2b2_fixtures import install_rebobinado_fixture
    from m3a_fixtures import install_grouped_form
except ModuleNotFoundError:
    from tests.m2b2_fixtures import install_rebobinado_fixture
    from tests.m3a_fixtures import install_grouped_form

P129_CODE = "VINTO-P1-29"
TUBETERA_MACHINE = "TUBETERA"  # FICTITIOUS test machine. The legacy frontend definition says "tubertera"; the candidate catalog says TUBETERA (unresolved discrepancy)

# key, label, value_type, required, options  (declared types are the legacy ones)
P129_SIMPLE_FIELDS = (
    ("fecha_de_produccion", "Fecha de producción", "date", True, ()),
    ("lote_de_produccion", "Lote de producción", "text", True, ()),
    ("pegamento_total_kg", "Pegamento total (kg)", "text", True, ()),
    ("peso_fardo", "Peso fardo", "text", True, ()),
    ("numero_mrp_del_sistema", "Número MRP del sistema", "text", True, ()),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
P129_GROUPS = (
    ("rodelas", "Rodelas de papel kraft", True, 1, None, (  # HYPOTHESIS: repeatable, min 1, no declared maximum
        ("rodela_papel_kraft_identificacion", "Rodela papel kraft · identificación", "text", True, ()),
        ("rodela_papel_kraft_peso_kg", "Rodela papel kraft · peso (kg)", "decimal", True, ()),
    )),
    ("formatos", "Formatos de tubete", True, 1, None, (  # HYPOTHESIS: repeatable, min 1, no declared maximum
        ("formato_tipo_de_tubete", "Formato · tipo de tubete", "text", True, ()),
        ("cantidad_tubetes_producidos_por_formato", "Cantidad de tubetes producidos", "text", True, ()),
        ("cantidad_tubetes_observados_por_formato", "Cantidad de tubetes observados", "textarea", False, ()),
        ("merma_kg_por_formato", "Merma (kg)", "decimal", True, ()),
        ("diametro_interno_mm_por_formato", "Diámetro interno (mm)", "decimal", True, ()),
        ("diametro_externo_mm_por_formato", "Diámetro externo (mm)", "decimal", True, ()),
        ("cantidad_de_hojas_por_formato", "Cantidad de hojas", "text", True, ()),
        ("espesor_mm_por_formato", "Espesor (mm)", "decimal", True, ()),  # the legacy metadata records unit kg for this mm-named field: unresolved discrepancy
        ("peso_kg_por_formato", "Peso (kg)", "decimal", True, ()),
    )),
)
# FICTITIOUS demonstration data (obviously fake, never real production values)
P129_VALUES = {
    "fecha_de_produccion": "2026-01-15", "lote_de_produccion": "LOTE-FICTICIO-001", "pegamento_total_kg": "12,5 (texto de ejemplo)", "peso_fardo": "100,0 (texto de ejemplo)",
    "numero_mrp_del_sistema": "MRP-FICTICIO-0001", "observaciones": "Dato de prueba",
    "_groups": {
        "rodelas": [
            {"rodela_papel_kraft_identificacion": "RODELA-FICTICIA-A", "rodela_papel_kraft_peso_kg": "10.250"},
            {"rodela_papel_kraft_identificacion": "RODELA-FICTICIA-B", "rodela_papel_kraft_peso_kg": "8.100"},
        ],
        "formatos": [
            {"formato_tipo_de_tubete": "FORMATO-FICTICIO-1", "cantidad_tubetes_producidos_por_formato": "120 (texto)", "cantidad_tubetes_observados_por_formato": "3 observados",
             "merma_kg_por_formato": "0.500", "diametro_interno_mm_por_formato": "38.10", "diametro_externo_mm_por_formato": "42.00", "cantidad_de_hojas_por_formato": "4",
             "espesor_mm_por_formato": "1.800", "peso_kg_por_formato": "6.750"},
            {"formato_tipo_de_tubete": "FORMATO-FICTICIO-2", "cantidad_tubetes_producidos_por_formato": "80", "merma_kg_por_formato": "0.250", "diametro_interno_mm_por_formato": "30.00",
             "diametro_externo_mm_por_formato": "34.00", "cantidad_de_hojas_por_formato": "3", "espesor_mm_por_formato": "1.500", "peso_kg_por_formato": "4.125"},
        ],
    },
}


def install_tubetera_machine(connection, article_codes):
    """A fictitious TUBETERA machine in the (already installed) fictitious REBOBINADO sector, linked to `article_codes`; returns its id."""
    sector_id = connection.execute("SELECT id FROM vinto_master.sector WHERE code = 'REBOBINADO'").fetchone()[0]
    machine_id = connection.execute("INSERT INTO vinto_master.machine (sector_id, code, name) VALUES (%s, %s, %s) RETURNING id", (sector_id, TUBETERA_MACHINE, "Tubetera (prueba)")).fetchone()[0]
    for article in article_codes:
        connection.execute("INSERT INTO vinto_master.article_machine (article_id, machine_id) SELECT id, %s FROM vinto_master.article WHERE code = %s", (machine_id, article))
    return machine_id


def install_tubetera(connection, article_codes):
    """Fictitious REBOBINADO context (sector, shifts, COPASA) + the fictitious TUBETERA machine; returns the Tubetera machine id."""
    install_rebobinado_fixture(connection, article_codes)
    return install_tubetera_machine(connection, article_codes)


def install_p129(connection, *, groups=P129_GROUPS, publish=True):
    """Publish the CANDIDATE P1-29 definition (production area) for the fictitious Tubetera machine, in this ephemeral database only."""
    return install_grouped_form(connection, P129_CODE, machine_codes=(TUBETERA_MACHINE,), simple_fields=P129_SIMPLE_FIELDS, groups=groups, publish=publish)

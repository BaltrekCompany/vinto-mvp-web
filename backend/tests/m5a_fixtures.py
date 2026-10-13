"""M5-A test-only fixtures: a SYNTHETIC genealogy scenario (mother bobbin from F3 + a fictitious P1-07 capture + daughters) for the feasibility study of P1-07.

Everything is installed in ephemeral *_test databases and is NOT an industrial rule:
- the «P1-07» form below is a test-only stand-in (VINTO-TEST-P107-SYN) with three fields of the legacy definition; the real P1-07 is not in any bundle;
- daughters and relations are inserted DIRECTLY with SQL (never through an operational API: no API creates daughters or relations);
- no consumption, inventory, mass balance or quality rule is implied; the relation carries no quantity.
"""

from datetime import time

try:
    from m2a_fixtures import install_production_form
except ModuleNotFoundError:
    from tests.m2a_fixtures import install_production_form

P107_TEST_CODE = "VINTO-TEST-P107-SYN"
P107_TEST_FIELDS = (
    ("etiqueta_numero_de_bobina", "Etiqueta / número de bobina", "text", True, ()),
    ("peso", "Peso", "decimal", True, ()),
    ("observaciones", "Observaciones", "textarea", False, ()),
)
P107_TEST_VALUES = {"etiqueta_numero_de_bobina": "EJEMPLO-ETIQUETA", "peso": "100.5", "observaciones": "dato sintético M5-A"}


def install_p107_test_form(connection, machine_codes=("COPASA",)):
    """Publish the test-only stand-in form for the fictitious Rebobinado machine (ephemeral database only)."""
    return install_production_form(connection, P107_TEST_CODE, machine_codes=machine_codes, fields=P107_TEST_FIELDS)


def _context(connection, actor_id):
    connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
    connection.execute("SELECT set_config('vinto.request_id', 'm5a:synthetic', true)")
    connection.execute("SELECT set_config('vinto.reason', 'm5a synthetic genealogy fixture', true)")


def insert_numbered_bobbin(connection, *, actor_id, capture_id, status="pending", weight="50.0"):
    """Insert a NUMBERED bobbin (+ its quality_release) hanging from `capture_id`, exactly like the F3 row shape but WITHOUT the F3 API.

    Machine, management year and article are taken from the capture (the database guard requires them to match). Returns the bobbin id.
    The correlative is allocated from the same per-machine counter F3 uses (that is the point of the compatibility check).
    """
    with connection.transaction():
        _context(connection, actor_id)
        machine_id, operating_date, article_version_id = connection.execute(
            """SELECT c.machine_id, c.operating_date, l.article_version_id FROM vinto_txn.capture c
               JOIN vinto_txn.assignment a ON a.id = c.assignment_id JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id WHERE c.id = %s""", (capture_id,)).fetchone()
        year = connection.execute("SELECT vinto_txn.management_start_year(%s)", (operating_date,)).fetchone()[0]
        sequence = connection.execute(
            """INSERT INTO vinto_txn.bobbin_sequence (machine_id, management_start_year, last_value) VALUES (%s, %s, 1)
               ON CONFLICT (machine_id, management_start_year) DO UPDATE SET last_value = vinto_txn.bobbin_sequence.last_value + 1 RETURNING last_value""", (machine_id, year)).fetchone()[0]
        bobbin_id = connection.execute(
            """INSERT INTO vinto_txn.bobbin (code, source_capture_id, article_version_id, weight_kg, machine_id, management_start_year, sequence_number, start_time, end_time,
                                             diameter_mm, number_of_cuts)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (str(sequence), capture_id, article_version_id, weight, machine_id, year, sequence, time(7, 0), time(8, 0), "1000", "1")).fetchone()[0]
        if status == "pending":
            connection.execute("INSERT INTO vinto_txn.quality_release (bobbin_id, status) VALUES (%s, 'pending')", (bobbin_id,))
        else:  # released / rejected need a decider (CHECK of 0001): the test user. A row here is NOT an authorized release.
            connection.execute("INSERT INTO vinto_txn.quality_release (bobbin_id, status, decided_by, decided_at, decision_reason) VALUES (%s, %s, %s, clock_timestamp(), 'sintético M5-A')",
                               (bobbin_id, status, actor_id))
    return bobbin_id


def insert_relation(connection, *, actor_id, mother_id, daughter_id, capture_id):
    with connection.transaction():
        _context(connection, actor_id)
        return connection.execute("INSERT INTO vinto_txn.bobbin_relation (mother_bobbin_id, daughter_bobbin_id, capture_id) VALUES (%s,%s,%s) RETURNING id",
                                  (mother_id, daughter_id, capture_id)).fetchone()[0]


# Genealogy READ proposal (not part of any API): descendants of a mother, by UUID, with depth and cycle protection.
DESCENDANTS_SQL = """WITH RECURSIVE tree AS (
    SELECT r.mother_bobbin_id, r.daughter_bobbin_id, 1 AS depth, ARRAY[r.mother_bobbin_id, r.daughter_bobbin_id] AS path
    FROM vinto_txn.bobbin_relation r WHERE r.mother_bobbin_id = %s
  UNION ALL
    SELECT r.mother_bobbin_id, r.daughter_bobbin_id, t.depth + 1, t.path || r.daughter_bobbin_id
    FROM vinto_txn.bobbin_relation r JOIN tree t ON r.mother_bobbin_id = t.daughter_bobbin_id WHERE NOT r.daughter_bobbin_id = ANY(t.path)
)
SELECT daughter_bobbin_id, depth FROM tree ORDER BY depth, daughter_bobbin_id"""
ANCESTORS_SQL = """WITH RECURSIVE tree AS (
    SELECT r.mother_bobbin_id, 1 AS depth, ARRAY[r.daughter_bobbin_id, r.mother_bobbin_id] AS path
    FROM vinto_txn.bobbin_relation r WHERE r.daughter_bobbin_id = %s
  UNION ALL
    SELECT r.mother_bobbin_id, t.depth + 1, t.path || r.mother_bobbin_id
    FROM vinto_txn.bobbin_relation r JOIN tree t ON r.daughter_bobbin_id = t.mother_bobbin_id WHERE NOT r.mother_bobbin_id = ANY(t.path)
)
SELECT mother_bobbin_id, depth FROM tree ORDER BY depth, mother_bobbin_id"""

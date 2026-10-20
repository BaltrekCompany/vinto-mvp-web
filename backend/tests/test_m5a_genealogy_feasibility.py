"""M5-A · factibilidad de la genealogía madre/hija de P1-07 sobre el esquema ACTUAL (0001-0006). Estudio técnico, NO una regla industrial.

Una bobina madre se crea por el circuito F3 real; la captura «P1-07», las hijas y las relaciones son SINTÉTICAS (tests/m5a_fixtures.py) y se insertan con SQL directo, nunca por una
API operativa. Cada prueba documenta lo que el esquema actual SÍ garantiza y lo que NO (las limitaciones se afirman a propósito: si una migración futura las cierra, estas pruebas
deben cambiar de forma consciente). Nada aquí decide qué estado de Calidad habilita el consumo, ni descuenta inventario, ni genera hijas automáticamente.
Bases efímeras *_test; no se toca DEV, backend/seed_data, sectors.py ni CENTRAL_FORM_CODES (se parchean solo dentro del proceso de prueba).
"""

import secrets
import unittest
from datetime import date
from unittest.mock import patch
from uuid import uuid4

import psycopg

from app import capture_service as _capture_service
from app import sectors as _sectors
from app.assignments import service as _assignments
from app.auth.service import create_user
from app.bobbins import service as _bobbins
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database
from app.seed.bundle import load_bundle
from app.work_orders import service as _work_orders
from app.work_orders.service import LineInput

try:
    from m2b2_fixtures import ENABLED_SECTORS, REB_MACHINE, install_rebobinado_fixture
    from m5a_fixtures import ANCESTORS_SQL, DESCENDANTS_SQL, P107_TEST_CODE, P107_TEST_VALUES, insert_numbered_bobbin, insert_relation, install_p107_test_form
    from scope_helpers import internal
except ModuleNotFoundError:
    from tests.m2b2_fixtures import ENABLED_SECTORS, REB_MACHINE, install_rebobinado_fixture
    from tests.m5a_fixtures import ANCESTORS_SQL, DESCENDANTS_SQL, P107_TEST_CODE, P107_TEST_VALUES, insert_numbered_bobbin, insert_relation, install_p107_test_form
    from tests.scope_helpers import internal

capture_service = internal(_capture_service)
assignments = internal(_assignments)
bobbins = internal(_bobbins)
work_orders = internal(_work_orders)
SHIPPED_POLICY = _capture_service.CENTRAL_FORM_CODES
SHIPPED_SECTORS = _sectors.operational_sector_codes()
BUNDLE = load_bundle()
MP1_ARTICLE = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP1")[0]
F3_VALUES = {"hora_inicio": "07:15", "hora_fin": "08:40", "diametro": "1200.5", "peso_kg": "845.25", "numero_de_cortes": "3", "observaciones": "madre sintética"}
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_m5a_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class GenealogyCase(unittest.TestCase):
    def setUp(self):
        self.database = copy_database(STATE["template"], "vinto_m5a")
        self.addCleanup(drop_database, self.database)
        self.connection = connect(self.database)
        self.addCleanup(self.connection.close)
        for scope in (patch.object(_sectors, "_OPERATIONAL", ENABLED_SECTORS), patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({"VINTO-P1-06", P107_TEST_CODE}))):
            scope.start()
            self.addCleanup(scope.stop)
        install_rebobinado_fixture(self.connection, [MP1_ARTICLE])
        install_p107_test_form(self.connection)
        self.jefatura, self.supervisor, self.operator = (self.user(p) for p in ("JEFATURA", "SUPERVISION", "OPERACION"))
        self.device = str(uuid4())

    def user(self, profile):
        return create_user(self.connection, username=f"m5a.{uuid4().hex[:10]}", display_name=f"{profile.title()} M5-A", profile_code=profile, password="pw-" + secrets.token_urlsafe(18),
                           sectors=ENABLED_SECTORS).user_id

    def assignment(self, machine):
        order = work_orders.create_work_order(self.connection, actor_id=self.jefatura, machine_code=machine, lines=[LineInput("PV-M5A", MP1_ARTICLE, 10, date(2026, 12, 1))])
        order = work_orders.publish_work_order(self.connection, actor_id=self.jefatura, work_order_id=order.id)
        return assignments.activate(self.connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[0].id).assignment

    def scalar(self, sql, params=()):
        return self.connection.execute(sql, params).fetchone()[0]

    # ---- escenario -----------------------------------------------------------------------------------------------------------------
    def mother_from_f3(self):
        """Madre real: circuito F3 (captura + bobina + quality_release 'pending' en una transacción)."""
        result = bobbins.submit_bobbin_production(self.connection, actor_id=self.operator, capture_id=uuid4(), assignment_id=self.assignment("MP1").id, device_key=self.device, values=F3_VALUES)
        return result

    def p107_capture(self):
        """Captura sintética «P1-07» en COPASA por el motor central real (política parcheada solo en la prueba)."""
        assignment = self.assignment(REB_MACHINE)
        result = capture_service.submit_production_capture(self.connection, actor_id=self.operator, capture_id=uuid4(), form_code=P107_TEST_CODE, assignment_id=assignment.id,
                                                           device_key=self.device, values=dict(P107_TEST_VALUES))
        return result.capture.id

    def daughter(self, capture_id=None, status="pending"):
        """Hija numerada. Cada una necesita SU PROPIA captura (una captura origina como máximo una bobina numerada), salvo que se indique `capture_id`."""
        return insert_numbered_bobbin(self.connection, actor_id=self.operator, capture_id=capture_id or self.p107_capture(), status=status)

    def relate(self, mother, daughter, capture_id):
        return insert_relation(self.connection, actor_id=self.operator, mother_id=mother, daughter_id=daughter, capture_id=capture_id)


class MotherFromF3Tests(GenealogyCase):
    def test_mother_has_identification_article_weight_and_pending_quality(self):
        mother = self.mother_from_f3()
        bobbin = mother.bobbin
        self.assertEqual((bobbin.code, bobbin.machine_code, bobbin.article_code, bobbin.weight_kg, bobbin.quality_status), ("1", "MP1", MP1_ARTICLE, "845.25", "pending"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin_relation"), 0)  # F3 no crea relaciones: F3 y genealogía son independientes
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.quality_release WHERE bobbin_id = %s", (bobbin.id,)), "pending")

    def test_policy_and_sectors_are_only_patched_inside_the_test(self):
        self.assertEqual(SHIPPED_POLICY, frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", "VINTO-P1-06", "VINTO-P1-31", "VINTO-P1-07", "VINTO-P1-10", "VINTO-P1-30", "VINTO-P1-11", "VINTO-P1-12", "VINTO-P1-13", "VINTO-P1-16", "VINTO-P1-29"}))  # CLOUD-DEP G.12-C4-FINAL25: +5 candidatos (Conversión/TUBETERA) habilitados para QA
        self.assertEqual(SHIPPED_SECTORS, ("BOBINAS", "REBOBINADO", "CONVERSION"))


class RelationModelTests(GenealogyCase):
    def setUp(self):
        super().setUp()
        self.mother = self.mother_from_f3().bobbin.id
        self.capture = self.p107_capture()
        self.d1 = self.daughter(self.capture)

    def test_valid_relation_is_persisted_and_readable_by_uuid(self):
        relation = self.relate(self.mother, self.d1, self.capture)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin_relation WHERE id = %s", (relation,)), 1)
        self.assertEqual([r[0] for r in self.connection.execute(DESCENDANTS_SQL, (self.mother,)).fetchall()], [self.d1])
        self.assertEqual([r[0] for r in self.connection.execute(ANCESTORS_SQL, (self.d1,)).fetchall()], [self.mother])

    def test_visible_code_is_ambiguous_so_uuid_is_required(self):
        """El correlativo F3 es único por (máquina, gestión): «1» existe en MP1 y en COPASA a la vez."""
        self.assertEqual(self.scalar("SELECT code FROM vinto_txn.bobbin WHERE id = %s", (self.d1,)), "1")
        self.assertEqual(self.scalar("SELECT code FROM vinto_txn.bobbin WHERE id = %s", (self.mother,)), "1")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin WHERE code = '1'"), 2)

    def test_self_reference_is_rejected_by_the_database(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.relate(self.mother, self.mother, self.capture)

    def test_duplicate_link_is_rejected(self):
        self.relate(self.mother, self.d1, self.capture)
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.relate(self.mother, self.d1, self.capture)

    def test_unknown_mother_or_daughter_or_capture_is_rejected_by_foreign_keys(self):
        for mother, daughter, capture in ((uuid4(), self.d1, self.capture), (self.mother, uuid4(), self.capture), (self.mother, self.d1, uuid4())):
            with self.subTest(), self.assertRaises(psycopg.errors.ForeignKeyViolation):
                self.relate(mother, daughter, capture)

    def test_one_mother_many_daughters_and_many_mothers_one_daughter_are_both_allowed(self):
        """Multiplicidad: el esquema NO impone cardinalidad (ni una sola madre por hija ni un tope de hijas). Es una decisión de VINTO."""
        other_capture = self.p107_capture()
        d2 = self.daughter(other_capture)
        second_mother = self.daughter()  # cualquier bobina numerada sirve como «madre» para el esquema
        self.relate(self.mother, self.d1, self.capture)
        self.relate(self.mother, d2, other_capture)
        self.relate(second_mother, self.d1, self.capture)  # la misma hija con dos madres
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin_relation WHERE daughter_bobbin_id = %s", (self.d1,)), 2)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin_relation WHERE mother_bobbin_id = %s", (self.mother,)), 2)

    def test_cycles_are_NOT_prevented_but_the_read_proposal_terminates(self):
        """LIMITACIÓN: A->B y B->A coexisten (solo se prohíbe la autorreferencia). La lectura recursiva con ruta evita el bucle infinito."""
        b = self.daughter()
        self.relate(self.mother, b, self.capture)
        self.relate(b, self.mother, self.capture)  # ciclo de longitud 2: el esquema lo acepta
        rows = self.connection.execute(DESCENDANTS_SQL, (self.mother,)).fetchall()
        self.assertEqual([r[1] for r in rows], [1])  # termina: la madre no se repite en su propia ruta

    def test_relation_capture_is_NOT_tied_to_the_daughter_or_to_p107(self):
        """LIMITACIÓN: capture_id solo exige una captura existente. Puede ser la captura F3 de la madre u otra cualquiera; no hay vínculo con source_capture_id de la hija."""
        f3_capture = self.scalar("SELECT source_capture_id FROM vinto_txn.bobbin WHERE id = %s", (self.mother,))
        self.relate(self.mother, self.d1, f3_capture)
        self.assertNotEqual(f3_capture, self.scalar("SELECT source_capture_id FROM vinto_txn.bobbin WHERE id = %s", (self.d1,)))

    def test_relation_rows_are_mutable_and_deletable_unlike_quality_or_sequences(self):
        """LIMITACIÓN: bobbin_relation solo tiene triggers de auditoría; no hay inmutabilidad (sí la hay en identidad de bobina numerada y en el contador)."""
        relation = self.relate(self.mother, self.d1, self.capture)
        other = self.daughter()
        self.connection.execute("UPDATE vinto_txn.bobbin_relation SET daughter_bobbin_id = %s WHERE id = %s", (other, relation))
        self.connection.execute("DELETE FROM vinto_txn.bobbin_relation WHERE id = %s", (relation,))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin_relation"), 0)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'bobbin_relation'"), 3)  # alta, cambio y baja quedan auditados


class SectorAndMachineTests(GenealogyCase):
    def test_relation_across_machines_and_sectors_is_NOT_restricted(self):
        """LIMITACIÓN: madre en MP1 (BOBINAS) e hija en COPASA (REBOBINADO): permitido. Tampoco hay regla de máquina ni de que la madre sea de un sector previo."""
        mother = self.mother_from_f3().bobbin.id
        capture = self.p107_capture()
        daughter = self.daughter(capture)
        self.relate(mother, daughter, capture)
        machines = dict(self.connection.execute("SELECT b.id, m.code FROM vinto_txn.bobbin b JOIN vinto_master.machine m ON m.id = b.machine_id").fetchall())
        self.assertEqual((machines[mother], machines[daughter]), ("MP1", REB_MACHINE))
        # ...y la inversa (madre en Rebobinado, hija en Bobinas) tampoco se rechaza: el sentido industrial no está modelado.
        self.relate(daughter, mother, capture)

    def test_numbered_bobbin_must_match_the_capture_machine_and_article(self):
        """SÍ garantizado por el trigger de 0004: una bobina numerada hereda máquina, gestión y artículo de la captura que la origina."""
        self.mother_from_f3()  # garantiza una fila de origen para el INSERT ... SELECT
        capture = self.p107_capture()
        mp1 = self.scalar("SELECT id FROM vinto_master.machine WHERE code = 'MP1'")
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.connection.execute(
                """INSERT INTO vinto_txn.bobbin (code, source_capture_id, article_version_id, weight_kg, machine_id, management_start_year, sequence_number, start_time, end_time, diameter_mm, number_of_cuts)
                   SELECT '9', %s, article_version_id, 1, %s, management_start_year, 9, '07:00', '08:00', 1, '1' FROM vinto_txn.bobbin LIMIT 1""", (capture, mp1))

    def test_a_p107_capture_can_originate_only_ONE_numbered_bobbin(self):
        """LIMITACIÓN BLOQUEANTE: bobbin_source_capture_uidx (0004) = una bobina numerada por captura. Una captura P1-07 con varias salidas no cabe en bobinas numeradas."""
        capture = self.p107_capture()
        self.daughter(capture)
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.daughter(capture)

    def test_legacy_style_daughters_share_a_capture_but_have_no_machine_and_are_invisible_to_the_services(self):
        """Alternativa técnica probada: filas «legacy» (sin correlativo) pueden compartir captura, pero no tienen máquina/sector ni F3: los servicios no las ven."""
        capture = self.p107_capture()
        ids = []
        for code in ("LEG-A", "LEG-B"):
            ids.append(self.connection.execute("INSERT INTO vinto_txn.bobbin (code, source_capture_id, weight_kg) VALUES (%s, %s, 5) RETURNING id", (code, capture)).fetchone()[0])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin WHERE source_capture_id = %s", (capture,)), 2)
        self.assertIsNone(self.scalar("SELECT machine_id FROM vinto_txn.bobbin WHERE id = %s", (ids[0],)))
        from app.bobbins.errors import BobbinNotFoundError
        with self.assertRaises(BobbinNotFoundError):
            bobbins.get_bobbin(self.connection, ids[0])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.quality_release WHERE bobbin_id = ANY(%s)", (ids,)), 0)  # sin release no entra a la bandeja de Calidad


class QualityStatesTests(GenealogyCase):
    def test_relation_is_not_conditioned_on_the_quality_state_of_the_mother(self):
        """Estados de PRUEBA (pending / released / rejected). Ninguno se interpreta: el esquema no vincula consumo con Calidad y una fila `released` aquí NO es una liberación autorizada."""
        capture = self.p107_capture()
        daughter = self.daughter(capture)
        for status in ("pending", "released", "rejected"):
            with self.subTest(status):
                mother = self.daughter(self.p107_capture(), status=status)
                self.relate(mother, daughter, capture)
                self.assertEqual(self.scalar("SELECT status FROM vinto_txn.quality_release WHERE bobbin_id = %s", (mother,)), status)

    def test_every_numbered_daughter_enters_calidad_as_pending(self):
        """Efecto colateral a decidir: toda bobina numerada exige su quality_release; las hijas de P1-07 entrarían a la bandeja de Calidad como pendientes."""
        daughter = self.daughter(self.p107_capture())
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.quality_release WHERE bobbin_id = %s", (daughter,)), "pending")
        with self.assertRaises(psycopg.errors.CheckViolation), self.connection.transaction():  # sin release no se puede confirmar una bobina numerada
            self.connection.execute(
                """INSERT INTO vinto_txn.bobbin (code, source_capture_id, article_version_id, weight_kg, machine_id, management_start_year, sequence_number, start_time, end_time, diameter_mm, number_of_cuts)
                   SELECT '77', %s, article_version_id, 1, machine_id, management_start_year, 77, '07:00', '08:00', 1, '1' FROM vinto_txn.bobbin WHERE id = %s""", (self.p107_capture(), daughter))


class CounterAndTransactionTests(GenealogyCase):
    def test_daughters_share_the_f3_correlative_of_their_machine(self):
        """Compatibilidad con F3: las hijas numeradas de COPASA consumen el MISMO contador (máquina, gestión) que F3 usaría; no hay contador propio de genealogía."""
        capture = self.p107_capture()
        a = self.daughter(capture)
        b = self.daughter(self.p107_capture())
        codes = [self.scalar("SELECT code FROM vinto_txn.bobbin WHERE id = %s", (x,)) for x in (a, b)]
        self.assertEqual(codes, ["1", "2"])
        self.assertEqual(self.scalar("SELECT last_value FROM vinto_txn.bobbin_sequence s JOIN vinto_master.machine m ON m.id = s.machine_id WHERE m.code = %s", (REB_MACHINE,)), 2)

    def test_failure_rolls_back_daughters_relations_and_the_counter_together(self):
        mother = self.mother_from_f3().bobbin.id
        capture = self.p107_capture()
        before = (self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), self.scalar("SELECT count(*) FROM vinto_txn.bobbin_relation"),
                  self.scalar("SELECT count(*) FROM vinto_txn.bobbin_sequence"))
        with self.assertRaises(psycopg.errors.CheckViolation), self.connection.transaction():
            insert_numbered_bobbin(self.connection, actor_id=self.operator, capture_id=capture)  # hija + contador dentro de la transacción externa
            self.connection.execute("INSERT INTO vinto_txn.bobbin_relation (mother_bobbin_id, daughter_bobbin_id, capture_id) VALUES (%s,%s,%s)", (mother, mother, capture))  # autorreferencia
        self.assertEqual(before, (self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), self.scalar("SELECT count(*) FROM vinto_txn.bobbin_relation"), self.scalar("SELECT count(*) FROM vinto_txn.bobbin_sequence")))

    def test_retry_of_the_same_link_creates_no_duplicate_but_there_is_no_idempotency_key(self):
        """El reintento del MISMO vínculo se rechaza por UNIQUE (no hay clave de idempotencia propia: un servicio futuro necesitaría una, p. ej. por captura P1-07 + clave de salida)."""
        mother = self.mother_from_f3().bobbin.id
        capture = self.p107_capture()
        daughter = self.daughter(capture)
        self.relate(mother, daughter, capture)
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.relate(mother, daughter, capture)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin_relation"), 1)


class AuditTests(GenealogyCase):
    def test_relation_and_daughter_inserts_are_audited_with_the_actor(self):
        mother = self.mother_from_f3().bobbin.id
        capture = self.p107_capture()
        daughter = self.daughter(capture)
        self.relate(mother, daughter, capture)
        for table in ("bobbin", "bobbin_relation", "quality_release", "bobbin_sequence"):
            with self.subTest(table):
                self.assertGreaterEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = %s AND actor_id = %s", (table, self.operator)), 1)


if __name__ == "__main__":
    unittest.main()

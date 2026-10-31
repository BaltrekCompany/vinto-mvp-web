"""Equivalencia entre catálogo, concesión, motor de autorización y captura (MF-13-01D.1.1).

El modelo NO impide versiones publicadas de un mismo formulario en áreas distintas (solo UNIQUE(form_id, version_number)); el bundle real no las tiene, pero un import futuro podría crearlas.
Estas pruebas fijan que el motor jamás autoriza un par que el catálogo y el servicio de concesiones consideran inerte, incluso con versiones mixtas o vínculos históricos, sin cambiar lo que
hacen la captura ni la disponibilidad. Las versiones mixtas se construyen por la vía legal de la base (borrador → vínculo → publicar) en una copia efímera por prueba.
"""

import unittest
from uuid import uuid4

import psycopg

from app import capture_service
from app.admin.catalog import load_catalog
from app.auth import permissions
from app.auth.machine_form_grants import grant_machine_form
from app.auth.service import AuthenticatedUser, create_user
from app.authz import Operation, authorize
from app.authz.readiness import coverage_report
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database
from app.production_access import production_machines

PRODUCTION, BOBBIN, Q_BOBBIN = Operation.PRODUCTION_CAPTURE, Operation.BOBBIN_PRODUCTION, Operation.QUALITY_BOBBIN_CAPTURE
P101, P103, P105, P110, P119, P131 = "VINTO-P1-01", "VINTO-P1-03", "VINTO-P1-05", "VINTO-P1-10", "VINTO-P1-19", "VINTO-P1-31"
AREA = {PRODUCTION: "production", BOBBIN: "production", Q_BOBBIN: "quality"}
TEMPLATE = None


def setUpModule():
    global TEMPLATE
    TEMPLATE = build_reference_template("vinto_eqv_tpl")


def tearDownModule():
    drop_database(TEMPLATE)


def principal(user_id):
    return AuthenticatedUser(user_id, "u", "U", ("OPERACION",), permissions.permissions_for_profiles(["OPERACION", "CALIDAD"]), False)


def forms_listed(node, machine):
    """Formularios que production_access lista en una máquina (recorre el modelo serializado)."""
    if isinstance(node, dict):
        if node.get("code") == machine and "forms" in node:
            return [f["code"] for f in node["forms"]]
        for value in node.values():
            found = forms_listed(value, machine)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = forms_listed(value, machine)
            if found is not None:
                return found
    return None


class EquivalenceCase(unittest.TestCase):
    def setUp(self):
        self.db = copy_database(TEMPLATE, "vinto_eqv")
        self.addCleanup(drop_database, self.db)
        self.connection = connect(self.db)
        self.addCleanup(self.connection.close)
        self.admin = self.user("DATA_BALTREK")

    def user(self, profile="OPERACION", sectors=("BOBINAS", "REBOBINADO", "CONVERSION")):
        user_id = create_user(self.connection, username=f"eq.{uuid4().hex[:12]}", display_name=profile, profile_code=profile, password="pw-" + uuid4().hex, sectors=sectors).user_id
        if profile == "OPERACION":  # perfiles múltiples: aísla la lógica de versión de la de permisos
            self.connection.execute("INSERT INTO vinto_master.user_profile (user_id, profile_id) SELECT %s, id FROM vinto_master.profile WHERE code = 'CALIDAD'", (user_id,))
        return user_id

    def add_version(self, form, number, area, machine=None):
        """Publica una versión nueva copiando la última: borrador → vínculo → publicada (la base rechaza vincular una ya publicada)."""
        c = self.connection
        c.execute("DROP TABLE IF EXISTS _fv")
        c.execute("CREATE TEMP TABLE _fv AS SELECT * FROM vinto_config.form_version WHERE form_id = (SELECT id FROM vinto_config.form WHERE code = %s) ORDER BY version_number DESC LIMIT 1", (form,))
        c.execute("UPDATE _fv SET id = gen_random_uuid(), version_number = %s, area = %s, status = 'draft', published_at = NULL", (number, area))
        c.execute("INSERT INTO vinto_config.form_version SELECT * FROM _fv")
        if machine:
            c.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT (SELECT id FROM _fv), id FROM vinto_master.machine WHERE code = %s", (machine,))
        c.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = (SELECT id FROM _fv)")

    def grant(self, user_id, machine, form):
        try:
            grant_machine_form(self.connection, user_id=user_id, machine_code=machine, form_code=form, actor_id=self.admin)
            return True
        except Exception:
            return False

    def observe(self, holder, operation, machine, form):
        """Todo lo que cada pieza dice del par, en un solo lugar."""
        c = self.connection
        machine_id = c.execute("SELECT id FROM vinto_master.machine WHERE code = %s", (machine,)).fetchone()[0]
        decision = authorize(c, principal(holder), operation, machine, form)

        def capture_available(area):
            try:
                capture_service.published_form_version(c, form, machine_id, area=area)
                return True
            except Exception:
                return False
        return {"catalog_offered": load_catalog(c).pair(machine, form)["offered"], "engine": decision, "capture": capture_available(AREA[operation]),
                "listed": form in (forms_listed(production_machines(c, ("BOBINAS", "REBOBINADO", "CONVERSION")).model_dump(), machine) or [])}

    def readiness_offers(self, operation, machine, form):
        twin = self.user()
        name = self.connection.execute("SELECT username FROM vinto_auth.credential WHERE user_id = %s", (twin,)).fetchone()[0]
        report = coverage_report(self.connection)[operation.value]["blocked"]
        return any(i["username"] == name and i["machine"] == machine and i["form"] == form for i in report)


class MixedAreaTests(EquivalenceCase):
    def test_the_database_allows_mixed_areas_so_the_policy_must_not_rely_on_a_constraint(self):
        self.add_version(P101, 5, "quality")  # no lanza: no hay restricción verificable que lo impida
        self.assertEqual(self.connection.execute("SELECT count(DISTINCT area) FROM vinto_config.form_version fv JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = %s", (P101,)).fetchone()[0], 2)

    def test_the_real_bundle_has_no_form_with_versions_in_more_than_one_area(self):
        rows = self.connection.execute("SELECT f.code FROM vinto_config.form f JOIN vinto_config.form_version fv ON fv.form_id = f.id GROUP BY f.code HAVING count(DISTINCT fv.area) > 1").fetchall()
        self.assertEqual(rows, [])

    def test_older_production_link_with_a_newer_quality_version_is_inert_for_catalog_grant_engine_and_readiness(self):
        """El caso del informe: v4 production vinculada a MP1, v5 quality publicada sin vínculo y una concesión antigua activa."""
        holder = self.user()
        self.assertTrue(self.grant(holder, "MP1", P101))
        self.add_version(P101, 5, "quality")
        seen = self.observe(holder, PRODUCTION, "MP1", P101)
        self.assertFalse(seen["catalog_offered"])
        self.assertFalse(self.grant(self.user(), "MP1", P101))  # el servicio de concesiones ya no lo concede
        self.assertEqual((seen["engine"].allowed, seen["engine"].reason), (False, "EFFECTIVE_VERSION_OTHER_AREA"))  # ANTES de MF-13-01D.1.1 devolvía ALLOWED
        self.assertFalse(self.readiness_offers(PRODUCTION, "MP1", P101))
        # La captura y la disponibilidad NO se alteran: siguen resolviendo por área (decisión funcional pendiente, ver docs)
        self.assertTrue(seen["capture"] and seen["listed"])

    def test_a_quality_version_vigente_linked_to_the_machine_offers_it_but_production_stays_closed(self):
        """Inverso: v2 production solo MP3 + v3 quality vinculada a MP1. El catálogo lo ofrece y se puede conceder, pero no es utilizable en Producción (ni captura ni motor)."""
        holder = self.user()
        self.add_version(P105, 3, "quality", "MP1")
        seen = self.observe(holder, PRODUCTION, "MP1", P105)
        self.assertTrue(seen["catalog_offered"])
        self.assertTrue(self.grant(holder, "MP1", P105))
        seen = self.observe(holder, PRODUCTION, "MP1", P105)
        self.assertEqual((seen["engine"].allowed, seen["engine"].reason), (False, "EFFECTIVE_VERSION_OTHER_AREA"))
        self.assertFalse(seen["capture"] or seen["listed"])  # captura coherente con el motor: ambos cerrados
        self.assertFalse(self.readiness_offers(PRODUCTION, "MP1", P105))

    def test_a_historical_same_area_link_is_inert_everywhere(self):
        holder = self.user()
        self.add_version(P105, 1, "production", "MP1")  # v1 histórica vinculada a MP1; la vigente (v2) solo vincula MP3
        seen = self.observe(holder, PRODUCTION, "MP1", P105)
        self.assertFalse(seen["catalog_offered"] or seen["capture"] or seen["listed"])
        self.assertFalse(self.grant(holder, "MP1", P105))
        self.assertEqual((seen["engine"].allowed, seen["engine"].reason), (False, "PAIR_NOT_OFFERED"))
        self.assertFalse(self.readiness_offers(PRODUCTION, "MP1", P105))

    def test_a_newer_same_area_version_that_drops_the_machine_makes_an_old_grant_inert(self):
        holder = self.user()
        self.assertTrue(self.grant(holder, "MP1", P101))
        self.add_version(P101, 5, "production")  # vigente sin vínculo a MP1
        seen = self.observe(holder, PRODUCTION, "MP1", P101)
        self.assertEqual((seen["catalog_offered"], seen["engine"].reason, seen["capture"], seen["listed"]), (False, "PAIR_NOT_OFFERED", False, False))
        self.assertFalse(self.readiness_offers(PRODUCTION, "MP1", P101))

    def test_a_newer_same_area_version_that_keeps_the_machine_keeps_everything_open(self):
        holder = self.user()
        self.assertTrue(self.grant(holder, "MP1", P101))
        self.add_version(P101, 5, "production", "MP1")
        seen = self.observe(holder, PRODUCTION, "MP1", P101)
        self.assertEqual((seen["catalog_offered"], seen["engine"].allowed, seen["engine"].effective_version, seen["capture"], seen["listed"]), (True, True, 5, True, True))
        self.assertTrue(self.readiness_offers(PRODUCTION, "MP1", P101))

    def test_a_vigente_version_of_another_area_closes_a_quality_route_pair_in_the_engine_only(self):
        holder = self.user()
        self.assertTrue(self.grant(holder, "MP1", P119))
        self.add_version(P119, 2, "production", "MP1")  # una vigente de OTRA área para un formulario de Calidad por bobina
        seen = self.observe(holder, Q_BOBBIN, "MP1", P119)
        self.assertEqual((seen["engine"].allowed, seen["engine"].reason), (False, "EFFECTIVE_VERSION_OTHER_AREA"))
        self.assertTrue(seen["catalog_offered"])  # el catálogo la ofrece; el motor es más estricto (nunca más laxo)
        self.assertTrue(seen["capture"])  # la captura resuelve por área (v1 quality vinculada) y NO se altera: el motor, al integrarse, es una barrera adicional más estricta


class RealBundleEquivalenceTests(EquivalenceCase):
    FORMS = ((P101, PRODUCTION), (P103, BOBBIN), (P110, PRODUCTION), (P119, Q_BOBBIN), (P131, PRODUCTION))

    def test_for_every_machine_grantable_equals_catalog_offered_equals_engine_open_equals_capture_available(self):
        """Compatibilidad con los formularios existentes: P1-01, P1-03, P1-10, P1-19 y P1-31, en TODAS las máquinas del bundle."""
        holder = self.user()
        machines = [row[0] for row in self.connection.execute("SELECT code FROM vinto_master.machine WHERE active ORDER BY code").fetchall()]
        for form, operation in self.FORMS:
            open_machines = []
            for machine in machines:
                with self.subTest(form=form, machine=machine):
                    before = self.observe(holder, operation, machine, form)
                    grantable = self.grant(holder, machine, form)
                    after = self.observe(holder, operation, machine, form)
                    self.assertEqual(grantable, before["catalog_offered"])
                    self.assertEqual(after["engine"].allowed, grantable)  # con concesión y todo lo demás en regla: abierto ⇔ el catálogo lo ofrece
                    self.assertEqual(after["capture"], grantable)  # y la captura de su área lo encuentra igual
                    self.assertEqual(before["engine"].reason, "GRANT_MISSING" if grantable else before["engine"].reason)
                    if grantable:
                        open_machines.append(machine)
            self.assertTrue(open_machines, f"{form} debe seguir abierto en al menos una máquina")

    def test_p1_10_stays_open_on_the_five_rebobinadoras(self):
        holder = self.user()
        for machine in ("BELOIT", "COPASA", "OVER", "PERICHUN", "TUBETERA"):
            self.assertTrue(self.grant(holder, machine, P110))
            self.assertTrue(authorize(self.connection, principal(holder), PRODUCTION, machine, P110).allowed, machine)

    def test_p1_03_is_open_only_through_its_own_route_and_p1_01_in_mp1_and_mp3_are_independent_grants(self):
        holder = self.user()
        self.assertTrue(self.grant(holder, "MP1", P103) and self.grant(holder, "MP1", P101))
        self.assertTrue(authorize(self.connection, principal(holder), BOBBIN, "MP1", P103).allowed)
        self.assertFalse(authorize(self.connection, principal(holder), PRODUCTION, "MP1", P103).allowed)
        self.assertFalse(authorize(self.connection, principal(holder), PRODUCTION, "MP3", P101).allowed)  # la concesión de MP1 no abre MP3


if __name__ == "__main__":
    unittest.main()

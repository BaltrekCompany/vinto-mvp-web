"""MF-12A: VINTO-P1-01 versión 4 (MD_Ejec 9 y 14) y VINTO-P1-05 / VINTO-P1-31 versión 2 solo para MP3 (MD_Ejec 20).

  - MD_Ejec 9 (P1-01, MP1 y MP3): «frecuencia_release», «dosificacion_coating» y «frecuencia_coating» (texto libre, OPCIONALES, sin unidad ni rango); «dosificacion_release» no cambia.
  - MD_Ejec 14 (P1-01): se retiran los cuatro campos rojos (apertura_purga_prensa, presion_aceite_guia_tela, presion_aceite_lubricacion, vacio_tela); «rodillos_quimicos» y «vacio_pope» se sustituyen por
    «boquillas_quimicos» y «velocidad_pope» (CLAVES NUEVAS: no se traslada ni reinterpreta ningún valor histórico); «vacio_prensa» y «vacio_fieltro» se retiran porque la velocidad ya existe.
  - MD_Ejec 20 (P1-05 y P1-31): la versión 2 (mismos campos) solo está vinculada a MP3. La versión 1, ya publicada e inmutable, sigue vinculada a MP1 y MP3 y conserva sus capturas.

Se verifica contra PostgreSQL REAL (base efímera *_test) con los formularios REALES del bundle; las versiones anteriores (instaladas aquí como en producción) siguen publicadas, intactas y legibles."""

import contextlib
import dataclasses
import io
import json
import secrets
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app import capture_service as _capture_service
from app.assignments import service as _assignments_service
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, create_database, database_url, drop_database
from app.seed import reference
from app.seed.bundle import compute_definition_checksum, load_bundle
from migrate import apply as apply_migrations
from migrate import read_migrations

try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

P101, P102, P104, P105, P131 = "VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", "VINTO-P1-31"
NEW_VERSION = {P101: 4, P105: 2, P131: 2}
BUNDLE = load_bundle()
FORMS = {f["code"]: f for f in BUNDLE.forms}
V3 = json.loads((Path(__file__).with_name("mf12a_p101_v3.json")).read_text(encoding="utf-8"))  # P1-01 v3 tal como está publicada en producción
ARTICLE = {m: sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == m)[0] for m in {r["machine_code"] for r in BUNDLE.article_machines}}
SECTORS = ("BOBINAS", "REBOBINADO", "CONVERSION")
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)
STATE = {}
VERSIONS = {"VINTO-P1-01": 4, "VINTO-P1-02": 1, "VINTO-P1-03": 1, "VINTO-P1-04": 2, "VINTO-P1-05": 2, "VINTO-P1-06": 2, "VINTO-P1-07": 2, "VINTO-P1-10": 2, "VINTO-P1-11": 2, "VINTO-P1-12": 3, "VINTO-P1-13": 2,
            "VINTO-P1-16": 3, "VINTO-P1-18": 2, "VINTO-P1-19": 1, "VINTO-P1-20": 1, "VINTO-P1-21": 2, "VINTO-P1-22": 2, "VINTO-P1-24": 4, "VINTO-P1-25": 3, "VINTO-P1-26": 3, "VINTO-P1-27": 2, "VINTO-P1-28": 1,
            "VINTO-P1-29": 2, "VINTO-P1-30": 2, "VINTO-P1-31": 2}
RED = ("apertura_purga_prensa", "presion_aceite_guia_tela", "presion_aceite_lubricacion", "vacio_tela")
BLUE_DROPPED = ("vacio_prensa", "vacio_fieltro")  # su concepto ya existe como velocidad_secador / velocidad_fieltro
BLUE_REPLACED = {"rodillos_quimicos": "boquillas_quimicos", "vacio_pope": "velocidad_pope"}
RETIRED = RED + BLUE_DROPPED + tuple(BLUE_REPLACED)
OPTIONAL = ("frecuencia_release", "dosificacion_coating", "frecuencia_coating")
ADDED = OPTIONAL + tuple(BLUE_REPLACED.values())


def setUpModule():
    STATE["template"] = build_reference_template("vinto_mf12a_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def previous(code):
    """Definición ANTERIOR (la de producción antes de MF-12A): versión, campos, grupos y máquinas."""
    if code == P101:
        return 3, [dict(f) for f in V3["fields"]], V3["groups"], V3["machines"]
    return NEW_VERSION[code] - 1, [dict(f) for f in FORMS[code]["fields"]], FORMS[code]["groups"], ["MP1", "MP3"]


def variant(checksum, spec):
    """El bundle vigente con algunos formularios sustituidos por una versión anterior: {código: (versión, campos, grupos, máquinas)}."""
    forms = []
    for form in BUNDLE.forms:
        if form["code"] in spec:
            number, fields, groups, machines = spec[form["code"]]
            form = {**form, "version_number": number, "machines": machines, "groups": groups,
                    "fields": [{"source": "manual", "unit": None, **f, "display_order": n} for n, f in enumerate(fields, start=1)]}
            form["definition_checksum"] = compute_definition_checksum(form)
        forms.append(form)
    return dataclasses.replace(BUNDLE, source_checksum=checksum, forms=tuple(forms))


def old_spec(codes):
    return {code: previous(code) for code in codes}


def fill(fields, skip=()):
    """Valores FICTICIOS (nada aquí es un límite ni una regla) para los campos manuales de una definición."""
    out = {}
    for n, f in enumerate(fields):
        if f["source"] != "manual" or f["key"] in skip or f["key"] in ("observaciones", "observacion"):
            continue
        kind = f["value_type"]
        out[f["key"]] = f"{n}.25" if kind == "decimal" else ("06:30" if kind == "time" else "dato ficticio MF-12A")
    return out


def v4_values(**extra):
    """Captura completa de P1-01 v4: los campos obligatorios y los tres opcionales (salvo que se indique lo contrario)."""
    return {**fill(FORMS[P101]["fields"]), **extra}


def v3_values():
    return fill(V3["fields"])


class DefinitionTests(unittest.TestCase):
    def keys(self, code):
        return [f["key"] for f in FORMS[code]["fields"]]

    def test_only_the_three_forms_get_a_new_version(self):
        self.assertEqual({c: f["version_number"] for c, f in FORMS.items()}, VERSIONS)
        self.assertEqual(sorted(FORMS[P101]["machines"]), ["MP1", "MP3"], "P1-01 sigue en MP1 y MP3 (obs. 9 aplica a ambas)")
        self.assertEqual(FORMS[P105]["machines"], ["MP3"])
        self.assertEqual(FORMS[P131]["machines"], ["MP3"])
        for code in ("VINTO-P1-02", "VINTO-P1-03", P104, "VINTO-P1-06"):
            self.assertEqual(sorted(FORMS[code]["machines"]), ["MP1", "MP3"], f"{code}: la disponibilidad no cambia")
        self.assertEqual(sum(len(f["fields"]) + sum(len(g["fields"]) for g in f["groups"]) for f in BUNDLE.forms), 464)  # 469 tras MF-12A; MF-12B: P1-04 v2 (9 -> 7) y P1-16 v3 (10 -> 7)

    def test_p1_01_v4_removes_replaces_and_adds_exactly_what_was_approved(self):
        v3 = [f["key"] for f in V3["fields"]]
        v4 = self.keys(P101)
        self.assertEqual((len(v3), len(v4)), (73, 70))
        self.assertEqual(sorted(set(v3) - set(v4)), sorted(RETIRED), "salen exactamente 8 claves: 4 rojos, 2 azules retirados y 2 azules sustituidos")
        self.assertEqual(sorted(set(v4) - set(v3)), sorted(ADDED), "entran exactamente 5 claves: 3 opcionales y 2 sustitutos")
        self.assertEqual([k for k in v4 if k in v3], [k for k in v3 if k in v4], "las claves que se conservan mantienen su orden relativo")
        old = {f["key"]: {k: v for k, v in f.items() if k != "display_order"} for f in V3["fields"]}
        new = {f["key"]: {k: v for k, v in f.items() if k != "display_order"} for f in FORMS[P101]["fields"]}
        for key in set(v3) & set(v4):
            self.assertEqual(new[key], old[key], f"{key}: etiqueta, tipo, obligatoriedad y unidad intactos")

    def test_release_keeps_its_field_and_the_three_new_ones_are_optional_free_text_next_to_it(self):
        by = {f["key"]: f for f in FORMS[P101]["fields"]}
        release = by["dosificacion_release"]
        self.assertEqual((release["label"], release["value_type"], release["required"], release["unit"]), ("Dosificación Release", "text", True, None))
        keys = self.keys(P101)
        i = keys.index("dosificacion_release")
        self.assertEqual(keys[i:i + 5], ["dosificacion_release", "frecuencia_release", "dosificacion_coating", "frecuencia_coating", "dosificacion_fosfato"])
        for key, label in (("frecuencia_release", "Frecuencia Release"), ("dosificacion_coating", "Dosificación Coating"), ("frecuencia_coating", "Frecuencia Coating")):
            f = by[key]
            self.assertEqual((f["label"], f["value_type"], f["required"], f["unit"], f["source"], f.get("options")), (label, "text", False, None, "manual", None), key)

    def test_the_blue_replacements_have_new_keys_and_the_types_of_the_fields_they_replace(self):
        by = {f["key"]: f for f in FORMS[P101]["fields"]}
        old = {f["key"]: f for f in V3["fields"]}
        for gone, new in BLUE_REPLACED.items():
            self.assertNotIn(gone, by)
            self.assertEqual((by[new]["value_type"], by[new]["required"], by[new]["unit"]), (old[gone]["value_type"], old[gone]["required"], None), new)
        self.assertEqual((by["boquillas_quimicos"]["label"], by["velocidad_pope"]["label"]), ("Boquillas químicos", "Velocidad pope"))
        self.assertEqual(self.keys(P101).index("boquillas_quimicos"), [f["key"] for f in V3["fields"] if f["key"] not in RED + BLUE_DROPPED].index("rodillos_quimicos") + 3, "ocupa la posición de la clave que sustituye")

    def test_one_active_field_per_concept_and_no_duplicate_labels(self):
        keys, labels = self.keys(P101), [f["label"] for f in FORMS[P101]["fields"]]
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual(len(set(labels)), len(labels), "sin etiquetas repetidas")
        self.assertEqual((keys.count("velocidad_secador"), keys.count("velocidad_fieltro"), keys.count("velocidad_pope")), (1, 1, 1))
        self.assertFalse([k for k in keys if k.startswith("vacio_")], "ningún «vacío» queda en P1-01 v4")

    def test_p1_05_and_p1_31_v2_keep_their_fields_and_only_change_their_machines(self):
        self.assertEqual(self.keys(P105), ["numero_de_bobina", "numero_codigo_de_tubete", "tipo_de_tubete", "cantidad_utilizada", "cantidad_recuperada", "cantidad_devuelta", "estado_del_tubete", "procedencia", "destino", "observaciones"])
        self.assertEqual(self.keys(P131), ["codigo_de_insumo", "seccion", "insumo_quimico", "caudal_mp1_ml_min", "caudal_mp3_ml_min", "consumo_dia_mp1_kg", "consumo_dia_mp3_kg", "consumo_total_kg", "observaciones"])


class Base(unittest.IsolatedAsyncioTestCase):
    """Producción central con asignación sobre una base efímera: bundle vigente + las versiones anteriores publicadas como en producción."""

    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_mf12a")
        cls.connection = connect(cls.database)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        with contextlib.redirect_stdout(io.StringIO()):
            reference.apply(cls.connection, variant("7" * 64, old_spec(NEW_VERSION)))  # P1-01 v3, P1-05 v1 y P1-31 v1 (MP1 y MP3), publicadas como en producción (aditivo)
        cls.old = {code: cls.version(code, NEW_VERSION[code] - 1) for code in NEW_VERSION}
        cls.new = {code: cls.version(code, NEW_VERSION[code]) for code in NEW_VERSION}
        cls.users, cls.cookies = {}, {}
        for name, profile in (("JEFATURA", "JEFATURA"), ("SUPERVISION", "SUPERVISION"), ("OPERACION", "OPERACION")):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"mf12a.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=SECTORS), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    @classmethod
    def version(cls, code, number):
        return cls.connection.execute("SELECT v.id FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.version_number = %s", (code, number)).fetchone()[0]

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        for target in (_capture_service, _assignments_service):
            p = patch.object(target, "_now", return_value=DAY)
            p.start()
            self.addCleanup(p.stop)

    async def cookie(self, name):
        if name not in self.cookies:
            created, password = self.users[name]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, name)
            self.cookies[name] = reply.set_cookie_value()
        return self.cookies[name]

    async def assignment(self, machine):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        order = await call("POST", "/api/work-orders", json_body={"machine_code": machine, "lines": [{"pv_reference": "PV-1", "article_code": ARTICLE[machine], "quantity": 10, "due_date": "2026-11-01"}]}, cookie=await self.cookie("JEFATURA"))
        self.assertEqual(order.status, 201, order.text)
        order = (await call("POST", f"/api/work-orders/{order.json()['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        reply = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"), json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        self.assertEqual(reply.status, 201, reply.text)
        return reply.json()["assignment"]

    async def post(self, assignment, code, values, old=False, capture_id=None, device_key=None):
        body = {"capture_id": capture_id or str(uuid4()), "form_code": code, "assignment_id": assignment["id"], "device_key": device_key or str(uuid4()), "values": values}
        if not old:
            return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION")), body
        with patch.object(_capture_service, "published_form_version", return_value=self.old[code]):  # solo aquí se fuerza la versión anterior, como antes de publicar la nueva
            return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION")), body

    async def get(self, capture_id):
        return await call("GET", f"/api/captures/{capture_id}", cookie=await self.cookie("OPERACION"))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def stored(self, capture_id):
        return {k: (t, v) for k, t, v in self.connection.execute(
            """SELECT f.key, d.value_type, coalesce(d.value_decimal::text, d.value_time::text, d.value_text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s AND d.group_row_id IS NULL""", (capture_id,)).fetchall()}


class P101Tests(Base):
    async def test_new_capture_with_release_and_coating_in_mp1_and_mp3(self):
        for machine in ("MP1", "MP3"):
            assignment = await self.assignment(machine)
            values = v4_values(frecuencia_release="50 Hz", dosificacion_coating="12", frecuencia_coating="cada 2 h")
            reply, _ = await self.post(assignment, P101, values)
            self.assertEqual(reply.status, 201, (machine, reply.text))
            capture = reply.json()["capture"]
            self.assertEqual(capture["form"]["version_number"], 4)
            for key, expected in (("frecuencia_release", "50 Hz"), ("dosificacion_coating", "12"), ("frecuencia_coating", "cada 2 h")):
                self.assertEqual(capture["values"][key], expected, "texto libre: se guarda tal como se digitó")
                self.assertEqual(self.stored(capture["id"])[key], ("text", expected), "sin conversión a número ni unidad")
            self.assertEqual(capture["values"]["dosificacion_release"], values["dosificacion_release"], "la dosificación de Release existente se conserva")
            got = await self.get(capture["id"])
            self.assertEqual((got.status, got.json()["values"]), (200, capture["values"]))

    async def test_the_three_new_fields_are_optional_and_empty_values_store_nothing(self):
        assignment = await self.assignment("MP3")
        base = {k: v for k, v in v4_values().items() if k not in OPTIONAL}
        for empty in ("absent", None, "", "   "):
            values = dict(base) if empty == "absent" else {**base, **{k: empty for k in OPTIONAL}}
            reply, _ = await self.post(assignment, P101, values)
            self.assertEqual(reply.status, 201, (repr(empty), reply.text))
            capture = reply.json()["capture"]
            for key in OPTIONAL:
                self.assertNotIn(key, capture["values"], "un valor vacío no se guarda ni se rellena")
                self.assertNotIn(key, self.stored(capture["id"]))
        partial, _ = await self.post(assignment, P101, {**base, "frecuencia_coating": "60"})
        self.assertEqual(partial.status, 201, "cada uno es independiente de los otros dos")
        self.assertEqual(list(set(partial.json()["capture"]["values"]) & set(OPTIONAL)), ["frecuencia_coating"])

    async def test_required_fields_stay_required_including_the_two_new_blue_ones(self):
        assignment = await self.assignment("MP1")
        good = v4_values()
        required = [f["key"] for f in FORMS[P101]["fields"] if f["required"]]
        self.assertEqual(len(required), 67)
        for key in ("boquillas_quimicos", "velocidad_pope", "dosificacion_release", "nivel_tanque_p17", "velocidad_secador", "velocidad_fieltro"):
            self.assertIn(key, required)
            reply, _ = await self.post(assignment, P101, {k: v for k, v in good.items() if k != key})
            self.assertEqual(reply.status, 422, key)
            self.assertIn(key, reply.text)
        reply, _ = await self.post(assignment, P101, {**good, "velocidad_pope": "rápida"})
        self.assertEqual(reply.status, 422, "velocidad_pope es decimal, como el campo que sustituye")
        self.assertEqual((await self.post(assignment, P101, {**good, "velocidad_pope": "310.5", "boquillas_quimicos": "B-3"}))[0].status, 201)

    async def test_retired_keys_are_rejected_in_a_new_v4_capture(self):
        assignment = await self.assignment("MP3")
        n = self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = %s", (assignment["id"],))
        for key in RETIRED:
            reply, _ = await self.post(assignment, P101, {**v4_values(), key: "1"})
            self.assertEqual(reply.status, 422, key)
            self.assertIn(key, reply.text)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = %s", (assignment["id"],)), n, "los rechazos no dejaron filas")

    async def test_old_values_are_never_moved_to_the_new_keys(self):
        assignment = await self.assignment("MP3")
        values = v3_values()
        values.update({"rodillos_quimicos": "RODILLO-HISTÓRICO", "vacio_pope": "-0.8", "vacio_prensa": "-1.1", "vacio_fieltro": "-0.5"})
        old, _ = await self.post(assignment, P101, values, old=True)
        self.assertEqual(old.status, 201, old.text)
        capture = old.json()["capture"]
        self.assertEqual(capture["form"]["version_number"], 3)
        for key in ADDED:
            self.assertNotIn(key, capture["values"], f"{key}: ninguna captura v3 trae las claves nuevas")
            self.assertNotIn(key, self.stored(capture["id"]))
        self.assertEqual((capture["values"]["rodillos_quimicos"], capture["values"]["vacio_pope"]), ("RODILLO-HISTÓRICO", "-0.8"), "el valor sigue en su clave original")
        got = await self.get(capture["id"])
        self.assertEqual((got.status, got.json()["values"]), (200, capture["values"]))
        self.assertEqual(got.json()["form"]["version_number"], 3)

    async def test_version_3_stays_published_readable_and_does_not_accept_the_new_keys(self):
        self.assertEqual(self.scalar("SELECT status FROM vinto_config.form_version WHERE id = %s", (self.old[P101],)), "published")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.old[P101],)), 73)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.new[P101],)), 70)
        assignment = await self.assignment("MP1")
        old, _ = await self.post(assignment, P101, v3_values(), old=True)
        self.assertEqual(old.status, 201, old.text)
        for key in ADDED:
            reply, _ = await self.post(assignment, P101, {**v3_values(), key: "x"}, old=True)
            self.assertEqual(reply.status, 422, f"la v3 no declara {key}")
        listed = await call("GET", f"/api/captures?form_code={P101}&machine_code=MP1", cookie=await self.cookie("OPERACION"))
        self.assertEqual(listed.status, 200)
        self.assertIn(old.json()["capture"]["id"], [c["id"] for c in listed.json()])
        new, _ = await self.post(assignment, P101, v4_values())
        self.assertEqual(new.json()["capture"]["form"]["version_number"], 4, "las capturas nuevas usan la versión más alta")

    async def test_the_rest_of_the_mp1_forms_keep_working(self):
        assignment = await self.assignment("MP1")
        reply, _ = await self.post(assignment, P102, fill(FORMS[P102]["fields"]))
        self.assertEqual(reply.status, 201, reply.text)
        self.assertEqual(reply.json()["capture"]["form"]["version_number"], 1)
        # P1-04 pasó a la versión 2 en MF-12B (un registro por consumo)
        reply, _ = await self.post(assignment, P104, {"hora_consumo": "07:30", "material": "Recorte", "origen": "Máquina", "presentacion": "Fardo", "cantidad_um": 3, "peso_unitario_real": "10.5"})
        self.assertEqual(reply.status, 201, reply.text)
        self.assertEqual(reply.json()["capture"]["form"]["version_number"], 2)


class AvailabilityTests(Base):
    async def machines(self):
        reply = await call("GET", "/api/production/machines", cookie=await self.cookie("OPERACION"))
        self.assertEqual(reply.status, 200, reply.text)
        return {m["code"]: sorted(f["code"] for f in m["forms"]) for s in reply.json()["sectors"] for m in s["machines"]}

    async def test_offer_for_mp1_drops_only_p1_05_and_p1_31(self):
        offered = await self.machines()
        mp1_before = sorted(["VINTO-P1-01", P102, P104, "VINTO-P1-06", P105, P131])
        self.assertEqual(offered["MP1"], sorted(set(mp1_before) - {P105, P131}), "MP1 conserva P1-01, P1-02, P1-04 y P1-06")
        self.assertEqual(offered["MP3"], mp1_before, "MP3 conserva las seis fichas")

    async def test_every_other_machine_keeps_exactly_the_offer_of_the_bundle(self):
        offered = await self.machines()
        for machine, codes in offered.items():
            expected = sorted(f["code"] for f in BUNDLE.forms if machine in f["machines"] and f["code"] in _capture_service.CENTRAL_FORM_CODES and f["area"] == "production")
            self.assertEqual(codes, expected, machine)

    async def test_new_captures_are_rejected_in_mp1_even_through_the_direct_api(self):
        assignment = await self.assignment("MP1")
        n = self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = %s", (assignment["id"],))
        for code in (P105, P131):
            reply, _ = await self.post(assignment, code, fill(FORMS[code]["fields"]))
            self.assertEqual(reply.status, 409, (code, reply.text))
            self.assertIn("FORM_NOT_AVAILABLE", reply.text)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = %s", (assignment["id"],)), n, "el rechazo no dejó filas")

    async def test_new_captures_are_accepted_in_mp3_with_the_same_fields(self):
        assignment = await self.assignment("MP3")
        for code in (P105, P131):
            reply, _ = await self.post(assignment, code, fill(FORMS[code]["fields"]))
            self.assertEqual(reply.status, 201, (code, reply.text))
            capture = reply.json()["capture"]
            self.assertEqual((capture["form"]["version_number"], capture["machine"]["code"]), (2, "MP3"))
        missing, _ = await self.post(assignment, P105, {k: v for k, v in fill(FORMS[P105]["fields"]).items() if k != "numero_de_bobina"})
        self.assertEqual(missing.status, 422, "las reglas de entrada no cambian")

    async def test_the_existing_mp1_captures_of_v1_stay_readable_and_listed(self):
        assignment = await self.assignment("MP1")
        for code in (P105, P131):
            reply, body = await self.post(assignment, code, fill(FORMS[code]["fields"]), old=True)
            self.assertEqual(reply.status, 201, (code, reply.text))
            capture = reply.json()["capture"]
            self.assertEqual((capture["form"]["version_number"], capture["machine"]["code"]), (1, "MP1"))
            got = await self.get(capture["id"])
            self.assertEqual((got.status, got.json()["values"], got.json()["form"]["version_number"]), (200, capture["values"], 1))
            listed = await call("GET", f"/api/captures?form_code={code}&machine_code=MP1", cookie=await self.cookie("OPERACION"))
            self.assertEqual(listed.status, 200, listed.text)
            self.assertIn(capture["id"], [c["id"] for c in listed.json()], "el historial de MP1 sigue accesible")
            retry = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
            self.assertEqual(retry.status, 200, "el reintento idempotente de una captura ya guardada no se rechaza")
            self.assertEqual(retry.json()["capture"]["id"], capture["id"])
        for code in (P105, P131):
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.form_version_machine WHERE form_version_id = %s", (self.old[code],)), 2, "la versión 1 conserva sus dos vínculos (inmutable)")
            self.assertEqual(self.scalar("SELECT status FROM vinto_config.form_version WHERE id = %s", (self.old[code],)), "published")
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.form_version_machine fvm JOIN vinto_master.machine m ON m.id = fvm.machine_id WHERE fvm.form_version_id = %s AND m.code = 'MP3'", (self.new[code],)), 1)
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.form_version_machine WHERE form_version_id = %s", (self.new[code],)), 1, "la versión 2 solo tiene MP3")


class ProductionImportScenarioTests(unittest.TestCase):
    """Producción tiene P1-01 v3, P1-05 v1 y P1-31 v1 (y MF-05 a MF-11 ya importados): el importador debe AÑADIR las tres versiones nuevas y dejar todo lo anterior exactamente igual."""

    @classmethod
    def setUpClass(cls):
        cls.database = f"vinto_mf12a_imp_{uuid4().hex[:10]}_test"
        create_database(cls.database)
        cls.connection = connect(cls.database)
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(cls.connection, read_migrations())
        reference.apply(cls.connection, variant("1" * 64, old_spec(NEW_VERSION)))

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        drop_database(cls.database)

    def snapshot(self, where):
        c = self.connection
        versions = c.execute(f"""SELECT f.code, v.version_number, v.status, v.definition_checksum, v.published_at FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id
                                 WHERE {where} ORDER BY 1, 2""").fetchall()
        fields = c.execute(f"""SELECT f.code, v.version_number, d.id, d.key, d.label, d.value_type, d.source, d.required, d.display_order FROM vinto_config.field_definition d
                               JOIN vinto_config.form_version v ON v.id = d.form_version_id JOIN vinto_config.form f ON f.id = v.form_id WHERE {where} ORDER BY 1, 2, 9""").fetchall()
        links = c.execute(f"""SELECT f.code, v.version_number, m.code FROM vinto_config.form_version_machine l JOIN vinto_config.form_version v ON v.id = l.form_version_id
                              JOIN vinto_config.form f ON f.id = v.form_id JOIN vinto_master.machine m ON m.id = l.machine_id WHERE {where} ORDER BY 1, 2, 3""").fetchall()
        return versions, fields, links

    def test_the_bundle_adds_only_the_three_new_versions_and_is_idempotent(self):
        codes = ", ".join(f"'{c}'" for c in NEW_VERSION)
        old_where = " OR ".join(f"(f.code = '{c}' AND v.version_number = {NEW_VERSION[c] - 1})" for c in NEW_VERSION)
        other_where = f"f.code NOT IN ({codes})"
        old, other = self.snapshot(old_where), self.snapshot(other_where)
        self.assertEqual(len(old[0]), 3)
        self.assertEqual(sorted(old[2]), sorted([(P101, 3, "MP1"), (P101, 3, "MP3"), (P105, 1, "MP1"), (P105, 1, "MP3"), (P131, 1, "MP1"), (P131, 1, "MP3")]))
        dry = reference.dry_run(self.connection, BUNDLE)
        self.assertEqual(dry.conflicts, [])
        self.assertEqual(dry.counts["form_version"]["create"], 3)
        self.assertEqual(dry.counts["field"]["create"], 70 + 10 + 9)
        self.assertEqual(dry.counts["form_version_machine"]["create"], 2 + 1 + 1)
        self.assertEqual(dry.counts["field_group"]["create"], 0)
        self.assertEqual(dry.counts["option"]["create"], 0)
        self.assertEqual(self.snapshot(old_where), old, "el dry-run no escribe")
        result = reference.apply(self.connection, BUNDLE)
        self.assertEqual((result.mode, result.conflicts), ("applied", []))
        self.assertEqual(self.snapshot(old_where), old, "las versiones anteriores, sus campos y sus vínculos quedan idénticos")
        self.assertEqual(self.snapshot(other_where), other, "los demás formularios no se tocan")
        for code, number in NEW_VERSION.items():
            rows = self.connection.execute("SELECT v.version_number, v.status FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s ORDER BY 1", (code,)).fetchall()
            self.assertEqual([r for r in rows if r[0] >= number - 1], [(number - 1, "published"), (number, "published")], code)
        new_links = self.connection.execute("SELECT f.code, m.code FROM vinto_config.form_version_machine l JOIN vinto_config.form_version v ON v.id = l.form_version_id JOIN vinto_config.form f ON f.id = v.form_id JOIN vinto_master.machine m ON m.id = l.machine_id "
                                            "WHERE (f.code = 'VINTO-P1-05' AND v.version_number = 2) OR (f.code = 'VINTO-P1-31' AND v.version_number = 2) OR (f.code = 'VINTO-P1-01' AND v.version_number = 4) ORDER BY 1, 2").fetchall()
        self.assertEqual(new_links, [(P101, "MP1"), (P101, "MP3"), (P105, "MP3"), (P131, "MP3")])
        again = reference.apply(self.connection, dataclasses.replace(BUNDLE, source_checksum="3" * 64))
        self.assertTrue(all(n["create"] == 0 for n in again.counts.values()), "segunda importación idempotente: no crea duplicados")


if __name__ == "__main__":
    unittest.main()

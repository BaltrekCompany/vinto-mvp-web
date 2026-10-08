"""Validates the committed reference bundle (backend/seed_data). No database access."""

import hashlib
import json
import re
import unittest
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent.parent / "seed_data"
FORM_FILE = "forms/VINTO-P1-06.json"
EXPECTED_PROFILES = {"JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD", "DATA_BALTREK"}
FORBIDDEN = re.compile(
    r"password|passwd|secret|token|argon|api[_-]?key|credential|OT-PRUEBA|ASG-PRUEBA|PV-PRUEBA|usuario-demo|equipo-",
    re.IGNORECASE)


def read_text(name):
    # Git may check files out with CRLF on Windows; the manifest hashes the LF form.
    return (BUNDLE / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def read(name):
    return json.loads(read_text(name))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def data_files():
    return sorted(p.relative_to(BUNDLE).as_posix() for p in BUNDLE.rglob("*.json"))


class ManifestTests(unittest.TestCase):
    def test_checksums_and_sizes_match_every_file(self):
        manifest = read("manifest.json")
        for entry in manifest["files"]:
            text = read_text(entry["path"])
            self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), entry["sha256"], entry["path"])
            self.assertEqual(len(text.encode("utf-8")), entry["bytes"], entry["path"])

    def test_manifest_lists_exactly_the_bundle_files(self):
        manifest = read("manifest.json")
        listed = [f["path"] for f in manifest["files"]]
        self.assertEqual(listed, [n for n in data_files() if n != "manifest.json"])
        self.assertEqual(listed, sorted(listed))

    def test_counts_match_the_data(self):
        counts = read("manifest.json")["counts"]
        self.assertEqual(counts["articles"], len(read("articles.json")["items"]))
        self.assertEqual(counts["article_machines"], len(read("article_machines.json")["items"]))
        self.assertEqual(counts["units"], len(read("units.json")["items"]))
        self.assertEqual(counts["material_classes"], len(read("material_classes.json")["items"]))
        self.assertEqual(counts["machines"], len(read("machines.json")["items"]))
        self.assertEqual(counts["profiles"], len(read("profiles.json")["items"]))
        self.assertEqual(counts["articles_also_material"], sum(a["is_material"] for a in read("articles.json")["items"]))

    def test_manifest_is_reproducible_and_leaks_no_host_data(self):
        text = read_text("manifest.json")
        self.assertNotRegex(text, r"[A-Za-z]:[\\/]|/Users/|/home/|generated_at|hostname")
        manifest = json.loads(text)
        self.assertEqual(manifest["schema_version"], 1)
        for source in manifest["generated_from"]:
            self.assertFalse(Path(source["path"]).is_absolute(), source["path"])
            self.assertRegex(source["sha256"], r"^[a-f0-9]{64}$")
        self.assertTrue(any(w["code"] == "SHIFT_VALIDITY_PROVISIONAL" for w in manifest["warnings"]))


class ReferenceDataTests(unittest.TestCase):
    def test_sector_is_unique_and_named_bobinas(self):
        sectors = read("sectors.json")["items"]
        self.assertEqual([(s["code"], s["name"]) for s in sectors], [("BOBINAS", "Bobinas")])

    def test_mp1_and_mp3_belong_to_the_sector(self):
        machines = read("machines.json")["items"]
        self.assertEqual([m["code"] for m in machines], ["MP1", "MP3"])
        self.assertEqual({m["sector"] for m in machines}, {"BOBINAS"})

    def test_article_codes_are_unique_and_complete(self):
        articles = read("articles.json")["items"]
        codes = [a["code"] for a in articles]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(codes, sorted(codes))
        units = {u["code"] for u in read("units.json")["items"]}
        classes = {c["code"] for c in read("material_classes.json")["items"]}
        for article in articles:
            self.assertTrue(article["is_product"])
            version = article["version"]
            self.assertEqual(version["version_number"], 1)
            self.assertTrue(version["description"].strip())
            self.assertIn(version["unit"], units)
            if version["material_class"] is not None:
                self.assertIn(version["material_class"], classes)
                self.assertTrue(article["is_material"])
            if version["nominal_weight_kg"] is not None:
                self.assertGreaterEqual(version["nominal_weight_kg"], 0)
        self.assertEqual(units, {a["version"]["unit"] for a in articles} | {"MM"})  # MM comes from the F3 diameter field
        self.assertEqual(classes, {a["version"]["material_class"] for a in articles} - {None})

    def test_article_machine_relations_are_valid(self):
        codes = {a["code"] for a in read("articles.json")["items"]}
        machines = {m["code"] for m in read("machines.json")["items"]}
        relations = read("article_machines.json")["items"]
        pairs = [(r["article_code"], r["machine_code"]) for r in relations]
        self.assertEqual(len(pairs), len(set(pairs)))
        for article_code, machine_code in pairs:
            self.assertIn(article_code, codes)
            self.assertIn(machine_code, machines)
        self.assertEqual({a for a, _ in pairs}, codes)  # every article is linked to a machine

    def test_profiles_are_exactly_the_five_expected(self):
        profiles = read("profiles.json")["items"]
        self.assertEqual({p["code"] for p in profiles}, EXPECTED_PROFILES)
        self.assertEqual(len(profiles), 5)
        self.assertTrue(all(p["name"].strip() for p in profiles))

    def test_workflows_cover_the_forms(self):
        workflows = {w["code"] for w in read("workflows.json")["items"]}
        self.assertEqual(workflows, {"production-standard", "quality-release"})
        self.assertIn(read(FORM_FILE)["workflow"], workflows)

    def test_shifts_are_declarative_and_open_ended(self):
        shifts = read("shifts.json")
        self.assertEqual({s["code"] for s in shifts["shifts"]}, {"DIA", "NOCHE"})
        times = {s["shift"]: (s["starts_at"], s["ends_at"]) for s in shifts["schedules"]}
        self.assertEqual(times, {"DIA": ("07:00", "19:00"), "NOCHE": ("19:00", "07:00")})
        for schedule in shifts["schedules"]:
            self.assertEqual(schedule["timezone"], "America/La_Paz")
            self.assertEqual(schedule["valid_from"], "2026-01-01")
            self.assertIsNone(schedule["valid_to"])
            self.assertEqual(schedule["sector"], "BOBINAS")
        self.assertIn("provisional", shifts["note"])


class FormSixTests(unittest.TestCase):
    def setUp(self):
        self.form = read(FORM_FILE)

    def test_identity(self):
        form = self.form
        self.assertEqual(form["legacy_key"], "form_6_registro_de_control_de_fardos")
        self.assertEqual((form["code"], form["area"], form["machines"]), ("VINTO-P1-06", "production", ["MP1", "MP3"]))
        self.assertEqual(form["groups"], [])

    def test_exactly_five_manual_fields(self):
        fields = self.form["fields"]
        self.assertEqual([f["key"] for f in fields],
                         ["cantidad_fardos", "punto_merma", "tipo_producto", "peso_kg", "observaciones"])
        self.assertEqual([(f["value_type"], f["required"]) for f in fields],
                         [("integer", True), ("text", True), ("text", True), ("decimal", True), ("textarea", False)])
        self.assertEqual({f["source"] for f in fields}, {"manual"})
        self.assertEqual([f["unit"] for f in fields], [None, None, None, "KG", None])
        self.assertEqual([f["display_order"] for f in fields], [1, 2, 3, 4, 5])

    def test_five_options_in_total(self):
        options = {f["key"]: [o["option_key"] for o in f.get("options", [])] for f in self.form["fields"]}
        self.assertEqual(options["punto_merma"], ["bobina_rechazada", "recorte_maquina"])
        self.assertEqual(options["tipo_producto"], ["servilleta", "hoja_doble", "hoja_simple"])
        self.assertEqual(sum(len(v) for v in options.values()), 5)
        for field in self.form["fields"]:
            keys = [o["option_key"] for o in field.get("options", [])]
            self.assertEqual(len(keys), len(set(keys)))

    def test_no_contextual_fields(self):
        keys = {f["key"] for f in self.form["fields"]}
        self.assertFalse(keys & {"fecha", "turno", "maquina", "operador", "responsable", "numero_de_fardo", "peso_total",
                                 "orden_trabajo", "linea_ot", "pv", "codigo_producto", "producto", "gramaje"})

    def test_definition_checksum_is_reproducible(self):
        definition = {k: v for k, v in self.form.items() if k not in ("schema_version", "definition_checksum")}
        self.assertEqual(hashlib.sha256(canonical(definition).encode("utf-8")).hexdigest(), self.form["definition_checksum"])


class NoSecretsTests(unittest.TestCase):
    def test_no_secrets_or_dev_user_data_in_the_bundle(self):
        for name in data_files():
            if name == "manifest.json":
                continue  # the manifest legitimately mentions sha256; its data is checked below
            self.assertNotRegex(read_text(name), FORBIDDEN, name)
        manifest_text = read_text("manifest.json")
        for forbidden in ("OT-PRUEBA", "ASG-PRUEBA", "password", "secret", "usuario-demo"):
            self.assertNotIn(forbidden, manifest_text)

class GrammageAndF3Tests(unittest.TestCase):
    def test_every_article_carries_grammage_derived_from_its_description(self):
        pattern = re.compile(r"(?<![A-Za-z0-9])G-(\d+(?:[.,]\d+)?)(?!\d)")
        for article in read("articles.json")["items"]:
            version = article["version"]
            match = pattern.search(version["description"])
            expected = None if match is None else float(match.group(1).replace(",", "."))
            self.assertEqual(version["grammage_g_m2"], expected, article["code"])

    def test_grammage_examples_and_nulls(self):
        by_description = {a["version"]["description"]: a["version"]["grammage_g_m2"] for a in read("articles.json")["items"]}
        self.assertEqual(by_description["M1-BOBINA PH G-22 CR-25% R-540640"], 22)
        self.assertEqual(by_description["M1-BOBINA PH G-15.5 CR-22% R-540640"], 15.5)
        self.assertEqual(by_description["M3-BOBINA PH G-14,5 CR-13% R-9109"], 14.5)
        self.assertIn(None, by_description.values())
        self.assertEqual(read("manifest.json")["counts"]["articles_with_grammage"], sum(v is not None for v in by_description.values()))

    def test_f3_is_published_in_the_bundle_with_only_operator_fields(self):
        form = read("forms/VINTO-P1-03.json")
        self.assertEqual((form["code"], form["area"], form["machines"], form["groups"]), ("VINTO-P1-03", "production", ["MP1", "MP3"], []))
        self.assertEqual([(f["key"], f["value_type"], f["required"], f["unit"]) for f in form["fields"]], [
            ("hora_inicio", "time", True, None), ("hora_fin", "time", True, None), ("diametro", "decimal", True, "MM"),
            ("peso_kg", "decimal", True, "KG"), ("numero_de_cortes", "text", True, None), ("observaciones", "textarea", False, None)])
        self.assertEqual({f["source"] for f in form["fields"]}, {"manual"})
        self.assertNotIn("pending_forms", read("manifest.json"))
        self.assertIn("MM", {u["code"] for u in read("units.json")["items"]})

class QualityP119Tests(unittest.TestCase):
    def test_p1_19_is_published_with_the_seven_manual_source_fields(self):
        form = read("forms/VINTO-P1-19.json")
        self.assertEqual((form["code"], form["name"], form["area"], form["workflow"], form["version_number"], form["machines"], form["groups"]),
                         ("VINTO-P1-19", "Control de humedad", "quality", "quality-release", 1, ["MP1", "MP3"], []))
        self.assertEqual([(f["key"], f["value_type"], f["required"], f["unit"], f["source"]) for f in form["fields"]], [
            ("peso_humedo_comando", "decimal", True, "KG", "manual"), ("peso_seco_comando", "decimal", True, "KG", "manual"),
            ("peso_humedo_medio", "decimal", True, "KG", "manual"), ("peso_seco_medio", "decimal", True, "KG", "manual"),
            ("peso_humedo_transversal", "decimal", True, "KG", "manual"), ("peso_seco_transversal", "decimal", True, "KG", "manual"),
            ("observaciones", "textarea", False, None, "manual")])
        self.assertEqual([f["display_order"] for f in form["fields"]], [1, 2, 3, 4, 5, 6, 7])

    def test_derived_and_automatic_values_are_not_central_fields(self):
        text = json.dumps(read("forms/VINTO-P1-19.json"))
        for forbidden in ("humedad_comando", "humedad_medio", "humedad_transversal", "promedio_humedad", "muestra_", "calculated", "automatic",
                          "numero_de_bobina", "responsable", "maquina", "fecha", '"hora"'):
            self.assertNotIn(forbidden, text, forbidden)

    def test_manifest_counts_cover_the_three_forms(self):
        counts = read("manifest.json")["counts"]
        self.assertEqual((counts["forms"], counts["form_fields"], counts["form_options"], counts["workflows"]), (3, 18, 5, 2))
        self.assertIn("forms/VINTO-P1-19.json", [f["path"] for f in read("manifest.json")["files"]])


if __name__ == "__main__":
    unittest.main()

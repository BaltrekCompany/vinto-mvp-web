"""Informe de solo lectura del bundle candidato (M4-B1): sobre el bundle aprobado y sobre uno dañado; sin PostgreSQL y sin escrituras."""

import contextlib
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import candidate_report
from app.seed.bundle import BUNDLE_DIR


class ReportOnApprovedBundleTests(unittest.TestCase):
    def test_approved_bundle_compared_with_itself_has_no_pending_data(self):
        report = candidate_report.build_report(BUNDLE_DIR, BUNDLE_DIR)
        self.assertFalse(report["candidato"])
        self.assertTrue(all(report["coincide_con_lo_aprobado"].values()))
        self.assertEqual(report["conflictos"]["articulos_aprobados_modificados_o_ausentes"], [])
        self.assertEqual(report["pendiente_de_aprobacion"]["sectores"], [])
        self.assertEqual(report["pendiente_de_aprobacion"]["maquinas"], [])
        self.assertEqual(report["conflictos"]["relaciones_con_articulo_inexistente"], [])
        # CLOUD-DEP G.12-C4-FINAL25: VINTO-P1-10 y VINTO-P1-29 ya están en el bundle real.
        self.assertEqual(report["faltantes"]["formularios_rebobinado_ausentes"], [])

    def test_cli_prints_json_and_reports_invalid_bundles_without_traceback(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(candidate_report.main([str(BUNDLE_DIR)]), 0)
        self.assertEqual(json.loads(out.getvalue())["conteos"]["machines"], 18)
        damaged = Path(tempfile.mkdtemp(prefix="seed-report-"))
        self.addCleanup(shutil.rmtree, damaged, ignore_errors=True)
        shutil.copytree(BUNDLE_DIR, damaged, dirs_exist_ok=True)
        machines = damaged / "machines.json"
        machines.write_text(machines.read_text(encoding="utf-8").replace("MP1", "MPX"), encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(candidate_report.main([str(damaged)]), 2)
        self.assertIn("Bundle inválido", err.getvalue())

    def test_tool_is_read_only(self):
        source = Path(candidate_report.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"psycopg|connect\(|\.write|open\(|DATABASE_URL|INSERT|UPDATE |DELETE", source))


class ApprovedArticleChangeTests(unittest.TestCase):
    def copy_with(self, edit):
        directory = Path(tempfile.mkdtemp(prefix="seed-report-edit-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        shutil.copytree(BUNDLE_DIR, directory, dirs_exist_ok=True)
        articles = directory / "articles.json"
        document = json.loads(articles.read_text(encoding="utf-8"))
        edit(document["items"])
        text = json.dumps(document, ensure_ascii=False, indent=2) + chr(10)
        articles.write_text(text, encoding="utf-8")
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        import hashlib
        manifest["counts"]["articles_also_material"] = sum(1 for item in document["items"] if item["is_product"] and item["is_material"])  # el bundle valida sus conteos
        manifest["counts"]["articles_with_nominal_weight"] = sum(1 for item in document["items"] if item["version"]["nominal_weight_kg"] is not None)
        manifest["counts"]["articles_with_grammage"] = sum(1 for item in document["items"] if item["version"].get("grammage_g_m2") is not None)
        for entry in manifest["files"]:
            if entry["path"] == "articles.json":
                entry["sha256"], entry["bytes"] = hashlib.sha256(text.encode("utf-8")).hexdigest(), len(text.encode("utf-8"))
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
        return directory

    def test_changed_approved_article_is_detected_even_if_relations_are_identical(self):
        def edit(items):
            items[0]["version"]["description"] += " (MODIFICADO)"
        report = candidate_report.build_report(self.copy_with(edit), BUNDLE_DIR)
        self.assertFalse(report["coincide_con_lo_aprobado"]["articulos_aprobados_identicos"])
        self.assertTrue(report["coincide_con_lo_aprobado"]["relaciones_articulo_maquina_aprobadas"])
        self.assertEqual(len(report["conflictos"]["articulos_aprobados_modificados_o_ausentes"]), 1)

    def test_every_attribute_counts(self):
        for attribute, value in (("unit", "UN"), ("grammage_g_m2", 999), ("nominal_weight_kg", 1.5), ("material_class", "TUBETE")):
            with self.subTest(attribute):
                report = candidate_report.build_report(self.copy_with(lambda items: items[0]["version"].__setitem__(attribute, value)), BUNDLE_DIR)
                self.assertFalse(report["coincide_con_lo_aprobado"]["articulos_aprobados_identicos"])

    def test_flag_change_is_detected(self):
        report = candidate_report.build_report(self.copy_with(lambda items: items[0].__setitem__("is_material", not items[0]["is_material"])), BUNDLE_DIR)
        self.assertFalse(report["coincide_con_lo_aprobado"]["articulos_aprobados_identicos"])

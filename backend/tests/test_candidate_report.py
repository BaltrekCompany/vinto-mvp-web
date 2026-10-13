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
        self.assertEqual(report["pendiente_de_aprobacion"]["sectores"], [])
        self.assertEqual(report["pendiente_de_aprobacion"]["maquinas"], [])
        self.assertEqual(report["conflictos"]["relaciones_con_articulo_inexistente"], [])
        self.assertEqual(report["faltantes"]["formularios_rebobinado_ausentes"], ["VINTO-P1-10", "VINTO-P1-29"])  # ningún bundle contiene P1-10 / P1-29 todavía

    def test_cli_prints_json_and_reports_invalid_bundles_without_traceback(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(candidate_report.main([str(BUNDLE_DIR)]), 0)
        self.assertEqual(json.loads(out.getvalue())["conteos"]["machines"], 2)
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

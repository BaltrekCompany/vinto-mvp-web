"""RBE-04: permisos de perfil y contratos de reserva/generación."""
import ast
import unittest
from pathlib import Path

from app.auth import permissions

BACKEND = Path(__file__).resolve().parent.parent


class RewindingExportPermissionTests(unittest.TestCase):
    def test_rbe_permissions_follow_the_approved_role_split(self):
        self.assertTrue(permissions.has_permission(("OPERACION",), permissions.REWINDING_EXPORT_CREATE))
        self.assertTrue(permissions.has_permission(("OPERACION",), permissions.REWINDING_EXPORT_READ_OWN))
        self.assertFalse(permissions.has_permission(("OPERACION",), permissions.REWINDING_EXPORT_READ_SECTOR))
        self.assertTrue(permissions.has_permission(("SUPERVISION",), permissions.REWINDING_EXPORT_READ_SECTOR))
        self.assertFalse(permissions.has_permission(("SUPERVISION",), permissions.REWINDING_EXPORT_ANNUL))
        self.assertTrue(permissions.has_permission(("JEFATURA",), permissions.REWINDING_EXPORT_READ_SECTOR))
        self.assertTrue(permissions.has_permission(("JEFATURA",), permissions.REWINDING_EXPORT_ANNUL))
        self.assertTrue(permissions.has_permission(("JEFATURA",), permissions.REWINDING_EXPORT_CLASSIFY_SOURCE))
        for permission in (permissions.REWINDING_EXPORT_CREATE, permissions.REWINDING_EXPORT_READ_OWN,
                           permissions.REWINDING_EXPORT_READ_SECTOR, permissions.REWINDING_EXPORT_ANNUL,
                           permissions.REWINDING_EXPORT_CLASSIFY_SOURCE):
            self.assertFalse(permissions.has_permission(("DATA_BALTREK",), permission))

    def test_generation_reserves_selected_children_inside_the_same_transaction(self):
        source = (BACKEND / "app/rewinding_export/service.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        generate = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "generate_report")
        body = ast.get_source_segment(source, generate)
        self.assertIn("with connection.transaction()", body)
        self.assertIn("FOR SHARE", body)
        self.assertIn("INSERT INTO vinto_txn.rewinding_export_reservation", body)
        self.assertIn("rewinding_export_pdf", body)
        self.assertIn("report_generated", body)

    def test_original_pdf_download_checks_the_stored_bytes_hash(self):
        source = (BACKEND / "app/rewinding_export/service.py").read_text(encoding="utf-8")
        self.assertIn("hashlib.sha256(content).hexdigest() != expected", source)
        self.assertIn("pdf_bytes", source)

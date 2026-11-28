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


    def test_rbe03_http_paths_and_response_contract_are_exposed(self):
        router = (BACKEND / "app/rewinding_export/router.py").read_text(encoding="utf-8")
        self.assertIn('prefix="/api/reports/rewinding-export"', router)
        for route in (
            '@router.get("/pvs")', '@router.get("/products")',
            '@router.get("/mothers")', '@router.get("/mothers/{mother_capture_id}/children")',
            '@router.get("/drafts")', '@router.get("/drafts/{report_id}")',
            '@router.post("/drafts",', '@router.patch("/drafts/{report_id}")',
            '@router.post("/drafts/{report_id}/packages",',
            '@router.patch("/drafts/{report_id}/packages/{package_id}")',
            '@router.post("/drafts/{report_id}/packages/{package_id}/remove")',
            '@router.post("/drafts/{report_id}/preview")',
            '@router.get("/work-orders")',
            '@router.get("/work-orders/{work_order_id}/classification")',
            '@router.post("/work-orders/{work_order_id}/classification"',
        ):
            self.assertIn(route, router)
        self.assertIn('"items":', router)

    def test_effective_authorization_is_registered_for_rewinding_p107(self):
        from app.authz.policies import Operation, policy_for
        policy = policy_for(Operation.REWINDING_EXPORT_CREATE)
        self.assertEqual(policy.permission, permissions.REWINDING_EXPORT_CREATE)
        self.assertEqual(policy.admitted(), frozenset({"VINTO-P1-07"}))
        self.assertEqual(policy.area, "production")

    def test_annulment_retains_pdf_and_releases_active_reservations(self):
        source = (BACKEND / "app/rewinding_export/service.py").read_text(encoding="utf-8")
        annul = next(node for node in ast.parse(source).body
                     if isinstance(node, ast.FunctionDef) and node.name == "annul_report")
        body = ast.get_source_segment(source, annul)
        self.assertIn("require_sector_permission(connection, user, REWINDING_EXPORT_ANNUL, lock=True)", body)
        self.assertIn("released_at=clock_timestamp()", body)
        self.assertIn("report_annulled", body)
        self.assertNotIn("DELETE FROM vinto_txn.rewinding_export_pdf", body)
        generate = next(node for node in ast.parse(source).body
                        if isinstance(node, ast.FunctionDef) and node.name == "generate_report")
        self.assertIn('"annulled"', ast.get_source_segment(source, generate))

    def test_original_pdf_download_checks_the_stored_bytes_hash(self):
        source = (BACKEND / "app/rewinding_export/service.py").read_text(encoding="utf-8")
        self.assertIn("hashlib.sha256(content).hexdigest() != expected", source)
        self.assertIn("pdf_bytes", source)

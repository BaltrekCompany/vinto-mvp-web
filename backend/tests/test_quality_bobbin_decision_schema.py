"""Pruebas del contrato de liberacion y rechazo; sin tocar PostgreSQL de produccion."""
import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.quality.decision_schemas import QualityDecisionIn


class QualityDecisionSchemaTests(unittest.TestCase):
    def test_release_requires_no_rejection_fields(self):
        item = QualityDecisionIn(decision_id=uuid4(), action="release")
        self.assertEqual(item.action, "release")
        with self.assertRaises(ValidationError):
            QualityDecisionIn(decision_id=uuid4(), action="release", classification="humedad")

    def test_reject_requires_all_four_fields(self):
        valid = dict(decision_id=uuid4(), action="reject", rejection_type="reutilizable",
                     classification="humedad", detail="Resultado fuera de especificacion",
                     corrective_action="Separar material y revalidar")
        self.assertEqual(QualityDecisionIn(**valid).rejection_type, "reutilizable")
        for missing in ("rejection_type", "classification", "detail", "corrective_action"):
            with self.subTest(missing=missing):
                with self.assertRaises(ValidationError):
                    QualityDecisionIn(**{k: v for k, v in valid.items() if k != missing})

    def test_reject_disallows_blank_text_and_unknown_choices(self):
        base = dict(decision_id=uuid4(), action="reject", rejection_type="rechazado",
                    classification="dimensiones", detail="Observacion", corrective_action="Accion")
        for field, value in (("detail", "   "), ("corrective_action", "  "),
                             ("rejection_type", "inventado"), ("classification", "inventada")):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    QualityDecisionIn(**dict(base, **{field: value}))

    def test_no_unknown_fields_or_excessive_text(self):
        base = dict(decision_id=uuid4(), action="reject", rejection_type="rechazado",
                    classification="otros", detail="D", corrective_action="A")
        with self.assertRaises(ValidationError):
            QualityDecisionIn(**dict(base, another_field="surprise"))
        with self.assertRaises(ValidationError):
            QualityDecisionIn(**dict(base, detail="x" * 4001))


if __name__ == "__main__":
    unittest.main()

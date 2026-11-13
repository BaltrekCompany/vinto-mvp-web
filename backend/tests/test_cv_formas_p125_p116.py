"""CV 13/11/2026: contrato declarativo de P1-25 v4 y P1-16 v4, sin tocar DB."""

import unittest
from app.seed.bundle import load_bundle


class FormasNovember13Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.forms = {item["code"]: item for item in load_bundle().forms}

    def test_p125_labels_only_and_calculations(self):
        form = self.forms["VINTO-P1-25"]
        self.assertEqual(form["version_number"], 4)
        fields = {field["key"]: field for field in form["fields"]}
        expected = {
            "resistencia_longitudinal_centro_kgf": "Resistencia en Húmedo Longitudinal - Comando",
            "resistencia_longitudinal_medio_kgf": "Resistencia en Húmedo Longitudinal - Medio",
            "resistencia_longitudinal_extremo_kgf": "Resistencia en Húmedo Longitudinal - Transversal",
            "resistencia_longitudinal_humeda_centro_kgf": "Resistencia en Húmedo Transversal - Comando",
            "resistencia_longitudinal_humeda_medio_kgf": "Resistencia en Húmedo Transversal - Medio",
            "resistencia_longitudinal_humeda_extremo_kgf": "Resistencia en Húmedo Transversal - Transversal",
        }
        self.assertEqual({key: fields[key]["label"] for key in expected}, expected)
        self.assertTrue(all(fields[key]["value_type"] == "decimal" and fields[key]["required"] for key in expected))
        self.assertEqual([f["key"] for f in form["fields"] if f["source"] == "calculated"], [
            "promedio_resistencia_longitudinal_kgf", "promedio_resistencia_longitudinal_humeda_kgf"
        ])

    def test_p116_hours_retired_but_pesada_kept(self):
        form = self.forms["VINTO-P1-16"]
        self.assertEqual(form["version_number"], 4)
        fields = [f for f in form["fields"] if f["source"] == "manual"]
        self.assertEqual([f["key"] for f in fields], [
            "numero_correlativo", "tipo_merma", "origen_merma", "peso_merma_kg", "observacion"
        ])
        self.assertEqual([f["display_order"] for f in fields], list(range(1, 6)))
        self.assertTrue(all(f["required"] for f in fields[:-1]))
        self.assertFalse(fields[-1]["required"])


if __name__ == "__main__":
    unittest.main()

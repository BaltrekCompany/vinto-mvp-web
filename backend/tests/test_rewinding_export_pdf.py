"""PDF layout, text and byte limits, with synthetic artifact fixtures."""
import hashlib
import os
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4

from app.rewinding_export import pdf_renderer


def make_snapshot(count, **overrides):
    snapshot = {
        "generated_at": "2026-11-29T01:05:00Z", "machine_name": "Máquina de ensayo",
        "article_code": "ART-SINTÉTICO", "article_description": "Papel de exportación",
        "pv_reference": "PV-ENSAYO", "destination": "Perú", "truck_number": "CAMIÓN-1",
        "order_number": "ORD-1", "format": "120.00 + 98.0", "observations": "Revisión final — envío a Perú.",
        "packages": [
            {"package_number": index, "mother_label": f"MADRE-{index:05d}", "diameter": "1200.00",
             "cuts": "0.00", "tubete": "Ensayo", "helper": None, "operator": "Operación sintética",
             "children": [{"slot": "A", "position": 13, "weight_kg": "123.50"},
                          {"slot": "E", "position": 22, "weight_kg": "7.00"}],
             "source_fields": {"producto_refilado": "EXCLUIR-DEL-PDF"}}
            for index in range(1, count + 1)
        ],
    }
    snapshot.update(overrides)
    return snapshot


class RewindingExportPDFTests(unittest.TestCase):
    def test_package_boundaries_page_numbers_and_evidence(self):
        evidence = os.environ.get("RBE05_EVIDENCE_DIR")
        for count, expected in ((1, 1), (20, 1), (21, 2), (40, 2), (41, 3), (2021, 102)):
            with self.subTest(packages=count):
                data, page_count = pdf_renderer.render_pdf(make_snapshot(count))
                reader = PdfReader(BytesIO(data), strict=True)
                self.assertEqual(len(reader.pages), expected)
                self.assertEqual(page_count, expected)
                for index, page in enumerate(reader.pages, 1):
                    self.assertAlmostEqual(float(page.mediabox.width), A4[0], places=2)
                    self.assertAlmostEqual(float(page.mediabox.height), A4[1], places=2)
                    text = page.extract_text()
                    self.assertIn(pdf_renderer.TITLE, text)
                    self.assertIn("Cría A", text)
                    self.assertIn(f"Página {index} de {expected}", text)
                    self.assertEqual("Observaciones generales" in text, index == expected)
                    self.assertEqual(text.count("MADRE-"), min(count - (index - 1) * 20, 20))
                    self.assertIn(f"MADRE-{(index - 1) * 20 + 1:05d}", text)
                if evidence and count in {1, 20, 21, 2021}:
                    path = Path(evidence) / f"sintetico-{count}.pdf"
                    path.write_bytes(data)
                    with path.open("rb") as document:
                        self.assertEqual(hashlib.sha256(data).hexdigest(), hashlib.file_digest(document, "sha256").hexdigest())

    def test_literal_values_spanish_and_optional_fields(self):
        data, _ = pdf_renderer.render_pdf(make_snapshot(1))
        text = PdfReader(BytesIO(data)).pages[0].extract_text()
        for value in ("Formato: 120.00 + 98.0", "0.00", "28/11/2026 21:05", "Perú",
                      "Operación", "123.50", "22", "7.00", "Revisión final"):
            self.assertIn(value, text)
        self.assertNotIn("0-C", text)
        self.assertNotIn("EXCLUIR-DEL-PDF", text)
        snapshot = make_snapshot(1, observations="", article_description=None, format="120.00")
        snapshot["packages"][0]["cuts"] = None
        data, _ = pdf_renderer.render_pdf(snapshot)
        text = PdfReader(BytesIO(data)).pages[0].extract_text()
        self.assertNotIn("Observaciones generales", text)
        self.assertNotIn("None", text)
        self.assertIn("Formato: 120.00", text)

    def test_long_values_are_wrapped_and_preserved(self):
        mother = "".join(f"TAG{index:02d}" for index in range(15))
        notes = [f"Línea informativa número {index:02d}" for index in range(58)]
        snapshot = make_snapshot(21, observations="\n".join(notes))
        snapshot["packages"][-1]["mother_label"] = mother
        data, _ = pdf_renderer.render_pdf(snapshot)
        pages = [page.extract_text() for page in PdfReader(BytesIO(data)).pages]
        self.assertNotIn("Observaciones generales", pages[0])
        self.assertIn(mother, "".join(pages[1].split()))
        for note in notes:
            self.assertEqual(sum(page.count(note) for page in pages[1:]), 1)

    def test_byte_limit_rejects_complete_output_over_25_mib(self):
        self.assertEqual(pdf_renderer.MAX_PDF_BYTES, 25 * 1024 * 1024)
        buffer = pdf_renderer._LimitedBuffer()
        buffer.write(b"x" * (25 * 1024 * 1024))
        with self.assertRaises(pdf_renderer.PDFTooLarge):
            buffer.write(b"x")
        self.assertEqual(buffer.tell(), 25 * 1024 * 1024)
        with patch.object(pdf_renderer, "MAX_PDF_BYTES", 1024):
            with self.assertRaises(pdf_renderer.PDFTooLarge):
                pdf_renderer.render_pdf(make_snapshot(1))

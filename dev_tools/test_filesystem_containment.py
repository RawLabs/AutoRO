from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.estimate_conversion import _resolve_input_pdf
from app.operations_reports import available_months, resolve_month_directory, valid_month
from app.config import settings
from app.routes import operations_digest
from fastapi import HTTPException


class EstimateInputContainmentTests(unittest.TestCase):
    def test_valid_uploaded_pdf_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            uploads.mkdir()
            pdf = uploads / "estimate.pdf"
            pdf.write_bytes(b"%PDF")
            self.assertEqual(pdf.resolve(), _resolve_input_pdf(str(pdf), {"uploads": uploads}))

    def test_absolute_pdf_outside_uploads_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            uploads = root / "uploads"
            uploads.mkdir()
            outside = root / "private.pdf"
            outside.write_bytes(b"%PDF")
            with self.assertRaisesRegex(ValueError, "AutoRO upload"):
                _resolve_input_pdf(str(outside), {"uploads": uploads})

    def test_parent_traversal_and_prefix_collision_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            uploads = root / "uploads"
            uploads.mkdir()
            sibling = root / "uploads-private"
            sibling.mkdir()
            outside = sibling / "estimate.pdf"
            outside.write_bytes(b"%PDF")
            for value in (uploads / ".." / "uploads-private" / "estimate.pdf", outside):
                with self.assertRaisesRegex(ValueError, "AutoRO upload"):
                    _resolve_input_pdf(str(value), {"uploads": uploads})

    def test_non_pdf_upload_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            uploads.mkdir()
            text = uploads / "estimate.txt"
            text.write_text("not a pdf", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "PDF upload"):
                _resolve_input_pdf(str(text), {"uploads": uploads})


class ReportContainmentTests(unittest.TestCase):
    def test_valid_month_resolves_under_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertEqual((root / "2026-07").resolve(), resolve_month_directory("2026-07", root))

    def test_traversal_absolute_and_malformed_months_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for value in ("../docs", "2026-07/../../docs", "C:\\private", "/private", "2026-7", "2026-13"):
                with self.assertRaisesRegex(ValueError, "YYYY-MM"):
                    resolve_month_directory(value, root)

    def test_available_months_ignores_non_month_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in ("2026-07", "2025-12", "docs", "2026-13"):
                (root / name).mkdir()
            import app.operations_reports as reports

            original = reports.reports_root
            try:
                reports.reports_root = lambda: root
                self.assertEqual(["2026-07", "2025-12"], available_months())
            finally:
                reports.reports_root = original

    def test_month_validator_is_exact(self) -> None:
        self.assertTrue(valid_month("2026-07"))
        self.assertFalse(valid_month("2026-07-extra"))

    def test_digest_route_returns_400_for_traversal(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            operations_digest(month="../docs", x_manager_code=settings.management_code)
        self.assertEqual(400, raised.exception.status_code)


if __name__ == "__main__":
    unittest.main()

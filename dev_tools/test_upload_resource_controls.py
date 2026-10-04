from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.upload_security import stream_pdf_upload


class FakeRequest:
    def __init__(self, chunks: list[bytes], content_length: str | None = None):
        self._chunks = chunks
        self.headers = {}
        if content_length is not None:
            self.headers["content-length"] = content_length

    async def stream(self):
        for chunk in self._chunks:
            yield chunk


class UploadResourceControlTests(unittest.TestCase):
    def run_upload(self, request: FakeRequest, destination: Path, max_bytes: int = 64) -> int:
        return asyncio.run(stream_pdf_upload(request, destination, max_bytes=max_bytes))

    def test_valid_pdf_stream_is_saved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "upload.pdf"
            size = self.run_upload(FakeRequest([b"%P", b"DF-1.7\ncontent"]), destination)
            self.assertEqual(len(b"%PDF-1.7\ncontent"), size)
            self.assertEqual(b"%PDF-1.7\ncontent", destination.read_bytes())

    def test_declared_oversize_is_rejected_before_streaming(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "upload.pdf"
            with self.assertRaisesRegex(ValueError, "too large"):
                self.run_upload(FakeRequest([b"%PDF"], content_length="65"), destination)
            self.assertFalse(destination.exists())

    def test_chunked_oversize_removes_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            destination = root / "upload.pdf"
            with self.assertRaisesRegex(ValueError, "too large"):
                self.run_upload(FakeRequest([b"%PDF", b"x" * 61]), destination)
            self.assertFalse(destination.exists())
            self.assertEqual([], list(root.glob("*.part")))
            self.assertEqual([], list(root.glob(".*.part")))

    def test_non_pdf_removes_completed_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            destination = root / "upload.pdf"
            with self.assertRaisesRegex(ValueError, "does not look like a PDF"):
                self.run_upload(FakeRequest([b"not a pdf"]), destination)
            self.assertFalse(destination.exists())
            self.assertEqual([], list(root.iterdir()))


if __name__ == "__main__":
    unittest.main()

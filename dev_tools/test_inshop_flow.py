#!/usr/bin/env python3
"""Manual, hermetic smoke test for parsing and in-shop PDF generation."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.parse_asr_pdf import parse_asr_pdf  # noqa: E402
from estimate_conversion.workspace.estimates.build_inshop_pdf import build_inshop_pdf  # noqa: E402


def select_sample() -> Path | None:
    if len(sys.argv) > 1:
        sample = Path(sys.argv[1]).expanduser().resolve()
        if not sample.is_file():
            raise FileNotFoundError(sample)
        return sample
    uploads = PROJECT_ROOT / "estimate_conversion" / "workspace" / "uploads"
    return next(iter(sorted(uploads.glob("*.pdf"))), None)


def test_flow() -> int:
    sample_pdf = select_sample()
    if sample_pdf is None:
        print("SKIP: supply a PDF path or place a test PDF in estimate_conversion/workspace/uploads.")
        return 0

    print(f"Parsing: {sample_pdf}")
    manifest = parse_asr_pdf(str(sample_pdf))
    jobs = list(manifest.get("jobs") or [])
    if not jobs:
        raise AssertionError("Parser returned no jobs")
    print(
        f"Parsed {len(jobs)} jobs for {manifest.get('year', '')} "
        f"{manifest.get('make', '')} {manifest.get('model', '')}"
    )

    with tempfile.TemporaryDirectory(prefix="autoro-inshop-smoke-") as temp_dir:
        temp_root = Path(temp_dir)
        database_path = temp_root / "autoro.db"
        with sqlite3.connect(database_path) as connection:
            connection.executescript((PROJECT_ROOT / "app" / "schema.sql").read_text(encoding="utf-8"))
            cursor = connection.execute(
                "INSERT INTO inshop_estimates "
                "(asr_filename, asr_manifest, story_mappings, advisor_edits, status_flags, pdf_path) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sample_pdf.name, json.dumps(manifest), None, None, None, None),
            )
            estimate_id = int(cursor.lastrowid)
            for index, job in enumerate(jobs):
                connection.execute(
                    "INSERT INTO inshop_jobs (estimate_id, job_index, data) VALUES (?, ?, ?)",
                    (estimate_id, index, json.dumps(job)),
                )
            inserted = connection.execute(
                "SELECT COUNT(*) FROM inshop_jobs WHERE estimate_id = ?",
                (estimate_id,),
            ).fetchone()[0]
            if inserted != len(jobs):
                raise AssertionError(f"Inserted {inserted} of {len(jobs)} jobs")

        mappings = {
            str(index): {
                "priority": "Maintenance - Recommended",
                "tech_found": "Source-grounded test finding.",
                "recommendation": f"Complete {str(job.get('title') or 'the quoted work').lower()}.",
                "why_matters": "Confirms the complete document path works without model output.",
                "repair_includes": list(job.get("labour_lines") or job.get("part_lines") or [])[:4],
            }
            for index, job in enumerate(jobs)
        }
        output_pdf = temp_root / "inshop-smoke.pdf"
        build_inshop_pdf(
            manifest,
            mappings,
            {"customer_concern": "Manual in-shop workflow smoke test."},
            output_pdf,
        )
        if not output_pdf.is_file() or output_pdf.stat().st_size == 0:
            raise AssertionError("PDF output was not created")
        print(f"Generated temporary PDF: {output_pdf.stat().st_size} bytes")

    print("In-shop smoke: PASS (temporary database and PDF removed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(test_flow())

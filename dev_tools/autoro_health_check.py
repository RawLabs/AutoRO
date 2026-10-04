#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
SCRIPTS_DIR = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from app.config import settings  # noqa: E402
from release_identity import DEFAULT_MANIFEST, verify_manifest  # noqa: E402


@dataclass
class CheckResult:
    label: str
    ok: bool
    detail: str
    severity: str = "required"  # required | optional


def resolve_portable_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (ROOT / path).resolve()


def check_endpoint(provider: str, base_url: str) -> tuple[bool, str]:
    provider = (provider or "").strip().lower()
    base_url = (base_url or "").strip().rstrip("/")

    if not base_url:
        return False, "No URL configured"

    if provider == "llamafile":
        url = f"{base_url}/v1/models"
    elif provider == "ollama":
        url = f"{base_url}/api/tags"
    else:
        return False, f"Unsupported provider: {provider or 'unknown'}"

    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if 200 <= resp.status < 300:
                return True, f"HTTP {resp.status} from {url}"
            return False, f"HTTP {resp.status} from {url}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} from {url}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return False, f"unreachable ({reason}) via {url}"


def parse_required_modules(requirements_path: Path) -> list[str]:
    if not requirements_path.exists():
        return []

    modules: list[str] = []
    for raw in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        base = line.split(";", 1)[0].strip()
        for sep in ("==", ">=", "<=", "~=", "!=", ">", "<"):
            if sep in base:
                base = base.split(sep, 1)[0].strip()
                break
        if "[" in base:
            base = base.split("[", 1)[0].strip()

        normalized = base.lower().replace("-", "_")
        module_name = {
            "pillow": "PIL",
        }.get(normalized, normalized)
        modules.append(module_name)

    # preserve order, unique
    seen: set[str] = set()
    deduped: list[str] = []
    for mod in modules:
        if mod not in seen:
            seen.add(mod)
            deduped.append(mod)
    return deduped


def check_manifest_valid(manifest_path: Path) -> tuple[bool, str]:
    if not manifest_path.exists():
        return False, f"missing manifest: {manifest_path}"

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"invalid JSON ({exc})"

    required = ["release_id", "tree_fingerprint_sha256", "file_count", "files"]
    missing = [k for k in required if k not in data]
    if missing:
        return False, f"missing keys: {', '.join(missing)}"

    if not isinstance(data.get("files"), list):
        return False, "'files' must be a list"

    return True, f"release_id={data.get('release_id')}"


def check_db_path(db_path: Path) -> tuple[bool, str]:
    if not db_path.exists():
        return False, f"database file missing: {db_path}"

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.execute("SELECT 1")
        conn.close()
        return True, str(db_path)
    except sqlite3.Error as exc:
        return False, f"sqlite unreachable: {exc}"


def check_directory_reachable(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing: {path}"
    if not path.is_dir():
        return False, f"not a directory: {path}"
    if not os.access(path, os.R_OK | os.X_OK):
        return False, f"not readable/executable: {path}"
    return True, str(path)


def check_directory_writable(path: Path) -> tuple[bool, str]:
    ok, detail = check_directory_reachable(path)
    if not ok:
        return False, detail

    probe_name = None
    try:
        with tempfile.NamedTemporaryFile(prefix="hermes-healthcheck-", dir=path, delete=False) as tmp:
            probe_name = tmp.name
            tmp.write(b"healthcheck\n")
        return True, str(path)
    except OSError as exc:
        return False, f"not writable: {path} ({exc})"
    finally:
        if probe_name:
            try:
                Path(probe_name).unlink(missing_ok=True)
            except OSError:
                pass


def main() -> int:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    manifest_path = DEFAULT_MANIFEST

    db_path = resolve_portable_path(settings.db_path)
    reports_root = resolve_portable_path(settings.reports_root)

    estimate_root = resolve_portable_path(settings.estimate_conversion_root)
    estimate_output = resolve_portable_path(settings.estimate_conversion_output_dir)
    estimate_uploads = estimate_root / "workspace" / "uploads"
    estimate_import_records = estimate_root / "workspace" / "import_records"
    estimate_workspace = estimate_root / "workspace"
    logs_dir = ROOT / "runtime" / "logs"

    req_modules = parse_required_modules(ROOT / "requirements.txt")
    missing_modules = [m for m in req_modules if importlib.util.find_spec(m) is None]

    manifest_ok, manifest_detail = check_manifest_valid(manifest_path)

    fingerprint_ok = False
    fingerprint_detail = ""
    try:
        match, result = verify_manifest(manifest_path)
        fingerprint_ok = bool(match)
        fingerprint_detail = (
            f"release_id={result.get('release_id')} tree_match={result.get('tree_match')} "
            f"file_count_match={result.get('file_count_match')} changed={result.get('changed_files_count')}"
        )
    except Exception as exc:
        fingerprint_ok = False
        fingerprint_detail = f"verify failed: {exc}"

    db_ok, db_detail = check_db_path(db_path)
    reports_ok, reports_detail = check_directory_reachable(reports_root)

    estimate_required = [estimate_root, estimate_workspace, estimate_output, estimate_uploads, estimate_import_records]
    estimate_missing = [str(p) for p in estimate_required if not p.exists() or not p.is_dir()]
    estimate_ok = len(estimate_missing) == 0
    estimate_detail = "all present" if estimate_ok else f"missing: {', '.join(estimate_missing)}"

    packages_ok = len(missing_modules) == 0
    packages_detail = (
        f"required modules present ({', '.join(req_modules)})"
        if packages_ok
        else f"missing modules: {', '.join(missing_modules)}"
    )

    primary_provider = settings.model_provider
    primary_url = settings.llamafile_url if primary_provider == "llamafile" else settings.ollama_url
    primary_ok, primary_detail = check_endpoint(primary_provider, primary_url)

    qwen_provider = settings.estimate_conversion_provider
    qwen_url = settings.estimate_conversion_llamafile_url if qwen_provider == "llamafile" else settings.ollama_url
    qwen_ok, qwen_detail = check_endpoint(qwen_provider, qwen_url)

    pdftotext_path = shutil.which("pdftotext")
    pdftotext_ok = bool(pdftotext_path)
    pdftotext_detail = pdftotext_path or "pdftotext not found in PATH"

    reportlab_ok = importlib.util.find_spec("reportlab") is not None
    reportlab_detail = "reportlab importable" if reportlab_ok else "reportlab not importable"

    writable_targets = [estimate_output, estimate_import_records, logs_dir]
    writable_failures: list[str] = []
    for target in writable_targets:
        ok, detail = check_directory_writable(target)
        if not ok:
            writable_failures.append(detail)
    writable_ok = len(writable_failures) == 0
    writable_detail = "all writable" if writable_ok else "; ".join(writable_failures)

    checks = [
        CheckResult("Release manifest valid", manifest_ok, manifest_detail),
        CheckResult("Code fingerprint matches", fingerprint_ok, fingerprint_detail),
        CheckResult("Database path reachable", db_ok, db_detail),
        CheckResult("Reports directory reachable", reports_ok, reports_detail),
        CheckResult("Estimate conversion directories present", estimate_ok, estimate_detail),
        CheckResult("Required Python packages available", packages_ok, packages_detail),
        CheckResult("Primary Qwen endpoint reachable", primary_ok, primary_detail),
        CheckResult(
            "Estimate AI endpoint reachable (fallback available for pre-estimate)",
            qwen_ok,
            qwen_detail,
            severity="optional",
        ),
        CheckResult("Poppler/pdftotext available", pdftotext_ok, pdftotext_detail),
        CheckResult("ReportLab available", reportlab_ok, reportlab_detail),
        CheckResult("Writable output directories", writable_ok, writable_detail),
    ]

    required_failures = [c for c in checks if c.severity == "required" and not c.ok]
    optional_failures = [c for c in checks if c.severity == "optional" and not c.ok]

    print(f"AutoRO Health Check @ {now}")
    print(f"Root: {ROOT}")
    print()

    for check in checks:
        if check.ok:
            prefix = "PASS"
        elif check.severity == "optional":
            prefix = "WARN"
        else:
            prefix = "FAIL"
        print(f"[{prefix}] {check.label}: {check.detail}")

    print()
    if required_failures:
        print("Overall status: FAIL (required checks failed)")
    elif optional_failures:
        print("Overall status: PASS with warnings (optional checks failed)")
    else:
        print("Overall status: PASS")

    return 1 if required_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

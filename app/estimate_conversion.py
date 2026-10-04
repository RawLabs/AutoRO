from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import time
import tempfile
import urllib.error
import urllib.request
import threading
from pathlib import Path
from typing import Any

from app.config import PORTABLE_ROOT, settings
from app.estimate_naming import estimate_output_stem
from app.upload_security import MAX_PDF_UPLOAD_BYTES, stream_pdf_upload


VALID_MODES = {"preestimate", "quote", "proposal"}
MAX_UPLOAD_BYTES = MAX_PDF_UPLOAD_BYTES
_conversion_slot = threading.BoundedSemaphore(value=1)


def conversion_paths() -> dict[str, Path]:
    root = _resolve_portable_path(settings.estimate_conversion_root)
    script = _resolve_portable_path(settings.estimate_conversion_script)
    output_dir = _resolve_portable_path(settings.estimate_conversion_output_dir)
    return {
        "root": root,
        "script": script,
        "output_dir": output_dir,
        "parser": root / "scripts" / "parse_mitchell_pdf.py",
        "logo": root / "images" / "autoro_logo.png",
        "uploads": root / "workspace" / "uploads",
        "import_records": root / "workspace" / "import_records",
    }


def get_conversion_status() -> dict[str, Any]:
    paths = conversion_paths()
    reportlab_ready = importlib.util.find_spec("reportlab") is not None
    pdftotext_path = shutil.which("pdftotext")
    setup_ready = all(
        [
            paths["root"].exists(),
            paths["script"].exists(),
            paths["parser"].exists(),
            paths["logo"].exists(),
            reportlab_ready,
            pdftotext_path,
        ]
    )
    model_engines = build_model_engine_status()
    estimator_online = bool(model_engines["estimate_ai"]["online"])
    return {
        "root": str(paths["root"]),
        "script": str(paths["script"]),
        "output_dir": str(paths["output_dir"]),
        "setup_ready": setup_ready,
        "ready": setup_ready and estimator_online,
        "checks": {
            "conversion_root": paths["root"].exists(),
            "decision_pipeline": paths["script"].exists(),
            "mitchell_parser": paths["parser"].exists(),
            "logo": paths["logo"].exists(),
            "reportlab": reportlab_ready,
            "pdftotext": bool(pdftotext_path),
        },
        "model_engines": model_engines,
        "modes": sorted(VALID_MODES),
        "default_model": settings.estimate_conversion_model,
        "model_provider": settings.estimate_conversion_provider,
        "llamafile_url": settings.estimate_conversion_llamafile_url,
    }


def build_model_engine_status() -> dict[str, dict[str, Any]]:
    estimate_status = check_model_engine(
        label="Shared Qwen model",
        provider=settings.estimate_conversion_provider,
        model=settings.estimate_conversion_model,
        base_url=settings.estimate_conversion_llamafile_url,
    )
    result = {"estimate_ai": estimate_status}
    primary_url = settings.llamafile_url if settings.model_provider == "llamafile" else settings.ollama_url
    if (
        settings.model_provider != settings.estimate_conversion_provider
        or settings.model_name != settings.estimate_conversion_model
        or primary_url != settings.estimate_conversion_llamafile_url
    ):
        result["translator"] = check_model_engine(
            label="Translator model",
            provider=settings.model_provider,
            model=settings.model_name,
            base_url=primary_url,
        )
    return result


def check_model_engine(label: str, provider: str, model: str, base_url: str) -> dict[str, Any]:
    provider = (provider or "").strip().lower()
    base_url = (base_url or "").rstrip("/")
    result = {
        "label": label,
        "provider": provider or "unknown",
        "model": model,
        "url": base_url,
        "online": False,
        "status": "offline",
        "detail": "Model server not checked.",
    }
    if not base_url:
        result["detail"] = "No model server URL configured."
        return result

    if provider == "llamafile":
        url = f"{base_url}/v1/models"
    elif provider == "ollama":
        url = f"{base_url}/api/tags"
    else:
        result["detail"] = f"Unsupported model provider: {provider or 'unknown'}."
        return result

    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if 200 <= resp.status < 300:
                result["online"] = True
                result["status"] = "online"
                result["detail"] = "Model server responded."
            else:
                result["status"] = "not ready"
                result["detail"] = f"Model server returned HTTP {resp.status}."
    except urllib.error.HTTPError as exc:
        result["status"] = "loading" if exc.code == 503 else "error"
        result["detail"] = f"Model server returned HTTP {exc.code}."
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        result["detail"] = f"Model server not reachable: {getattr(exc, 'reason', exc)}"
    return result


def run_estimate_conversion(payload: dict[str, Any]) -> dict[str, Any]:
    if not _conversion_slot.acquire(blocking=False):
        raise RuntimeError("Another estimate conversion is already running. Please retry shortly.")
    try:
        return _run_estimate_conversion(payload)
    finally:
        _conversion_slot.release()


def _run_estimate_conversion(payload: dict[str, Any]) -> dict[str, Any]:
    paths = conversion_paths()
    input_pdf = _resolve_input_pdf(str(payload.get("input_pdf") or ""), paths)
    mode = str(payload.get("mode") or "preestimate").strip()
    parsed_for_history: dict[str, Any] | None = None
    requested_prefix = str(payload.get("prefix") or "").strip()
    if not requested_prefix or requested_prefix == "autoro_estimate":
        parsed_for_history = _parse_for_record(paths, input_pdf)
        prefix = history_prefix(parsed_for_history, mode)
        payload["prefix"] = prefix
    else:
        prefix = _clean_prefix(requested_prefix)
    model_name = str(payload.get("model_name") or settings.estimate_conversion_model).strip()
    provider = settings.estimate_conversion_provider
    delete_after_run = bool(payload.get("delete_after_run"))
    imported_file = delete_after_run and _is_uploaded_file(input_pdf, paths)

    if mode not in VALID_MODES:
        raise ValueError(f"Unsupported estimate conversion mode: {mode}")
    if not input_pdf.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")
    if not paths["script"].exists():
        raise FileNotFoundError(f"Estimate conversion pipeline not found: {paths['script']}")
    if mode != "preestimate" and provider == "llamafile":
        model_error = _llamafile_unavailable_message(settings.estimate_conversion_llamafile_url)
        if model_error:
            _write_import_record(paths, input_pdf, payload, None, model_error)
            _delete_imported_file(input_pdf, imported_file)
            raise RuntimeError(model_error)

    paths["output_dir"].mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(paths["script"]),
        str(input_pdf),
        "--mode",
        mode,
        "--model",
        model_name,
        "--model-provider",
        provider,
        "--prefix",
        prefix,
    ]
    if provider == "llamafile":
        command.extend(["--llamafile-url", settings.estimate_conversion_llamafile_url])
    if mode == "preestimate":
        command.extend(["--timeout", "75", "--num-predict", "1200"])
    if payload.get("sanity_confirmed"):
        command.append("--sanity-confirmed")
    if payload.get("include_part_details"):
        command.append("--include-parts")
    if mode in {"quote", "proposal"}:
        output_pdf = paths["output_dir"] / f"{prefix}_{mode}.pdf"
        command.extend(["--output", str(output_pdf)])

    result: dict[str, Any] | None = None
    error_text = ""
    try:
        completed = subprocess.run(
            command,
            cwd=str(paths["root"]),
            capture_output=True,
            text=True,
            timeout=max(settings.request_timeout, 300),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        error_text = "Estimate conversion timed out."
        _write_import_record(paths, input_pdf, payload, None, error_text)
        _delete_imported_file(input_pdf, imported_file)
        raise TimeoutError("Estimate conversion timed out.") from exc
    final_pdf = _extract_final_pdf(completed.stdout) or _extract_named_pdf(completed.stdout)
    if completed.returncode != 0:
        error_text = (completed.stderr or completed.stdout or "Estimate conversion failed.").strip()
        _write_import_record(paths, input_pdf, payload, completed, error_text)
        _delete_imported_file(input_pdf, imported_file)
        raise RuntimeError(error_text)

    result = {
        "status": "completed",
        "mode": mode,
        "model_provider": provider,
        "model": model_name,
        "prefix": prefix,
        "pdf": final_pdf,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    record_path = _write_import_record(paths, input_pdf, payload, completed, "", parsed_for_history)
    _delete_imported_file(input_pdf, imported_file)
    if record_path:
        result["technical_record"] = str(record_path)
    if imported_file:
        result["import_cleanup"] = "uploaded PDF removed after processing"
    return result


def preflight_estimate_conversion(payload: dict[str, Any]) -> dict[str, Any]:
    paths = conversion_paths()
    input_pdf = _resolve_input_pdf(str(payload.get("input_pdf") or ""), paths)
    if not input_pdf.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")
    parsed = _parse_for_record(paths, input_pdf)
    if parsed.get("status") != "parsed":
        detail = str(parsed.get("error") or "PDF text could not be parsed.").strip()
        raise ValueError(f"Could not read this estimate PDF. {detail}")
    vehicle = parsed.get("vehicle") or {}
    jobs = parsed.get("jobs") or []
    if not vehicle.get("make") or not vehicle.get("model") or not jobs:
        raise ValueError(
            "This is not a recognizable Mitchell estimate. Upload the original Mitchell PDF, "
            "not a previously generated AutoRO pre-estimate, quote, or proposal."
        )
    findings = estimate_sanity_findings(parsed)
    return {
        "status": "review_required" if findings else "ok",
        "input_pdf": str(input_pdf),
        "suggested_prefix": history_prefix(parsed, str(payload.get("mode") or "preestimate")),
        "vehicle": parsed.get("vehicle", {}),
        "job_count": len(parsed.get("jobs") or []),
        "findings": findings,
    }


def resolve_output_pdf(value: str) -> Path:
    if not value:
        raise ValueError("PDF path is required.")
    paths = conversion_paths()
    output_dir = paths["output_dir"].resolve()
    pdf_path = Path(value).expanduser()
    if not pdf_path.is_absolute():
        pdf_path = output_dir / pdf_path
    pdf_path = pdf_path.resolve()
    try:
        pdf_path.relative_to(output_dir)
    except ValueError as exc:
        raise ValueError("PDF must be in the AutoRO estimate output directory.") from exc
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError("Only generated PDF files can be previewed.")
    return pdf_path


def save_estimate_upload(filename: str, content: bytes) -> dict[str, Any]:
    if not content:
        raise ValueError("Uploaded PDF was empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Uploaded PDF is too large. Limit is 25 MB.")
    if not content.startswith(b"%PDF"):
        raise ValueError("Uploaded file does not look like a PDF.")

    paths = conversion_paths()
    upload_dir = paths["uploads"]
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _clean_filename(filename or "estimate.pdf")
    if not safe_name.lower().endswith(".pdf"):
        safe_name = f"{safe_name}.pdf"
    stamped_name = f"{int(time.time())}_{safe_name}"
    target = upload_dir / stamped_name
    target.write_bytes(content)
    return {
        "status": "uploaded",
        "filename": safe_name,
        "path": str(target),
        "size_bytes": len(content),
        "delete_after_run": True,
    }


async def save_estimate_upload_stream(request: Any, filename: str) -> dict[str, Any]:
    paths = conversion_paths()
    safe_name = _clean_filename(filename or "estimate.pdf")
    if not safe_name.lower().endswith(".pdf"):
        safe_name = f"{safe_name}.pdf"
    target = paths["uploads"] / f"{time.time_ns()}_{safe_name}"
    size = await stream_pdf_upload(request, target)
    return {
        "status": "uploaded",
        "filename": safe_name,
        "path": str(target),
        "size_bytes": size,
        "delete_after_run": True,
    }


def _resolve_portable_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (PORTABLE_ROOT / path).resolve()


def _resolve_input_pdf(value: str, paths: dict[str, Path]) -> Path:
    if not value:
        raise ValueError("Input PDF path is required.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PORTABLE_ROOT / path
    resolved = path.resolve()
    upload_root = paths["uploads"].resolve()
    try:
        resolved.relative_to(upload_root)
    except ValueError as exc:
        raise ValueError("Input PDF must be an AutoRO upload.") from exc
    if resolved.suffix.lower() != ".pdf":
        raise ValueError("Input file must be a PDF upload.")
    return resolved


def _is_uploaded_file(input_pdf: Path, paths: dict[str, Path]) -> bool:
    try:
        input_pdf.resolve().relative_to(paths["uploads"].resolve())
        return True
    except ValueError:
        return False


def _delete_imported_file(input_pdf: Path, should_delete: bool) -> None:
    if not should_delete:
        return
    try:
        input_pdf.unlink(missing_ok=True)
    except OSError:
        pass


def _llamafile_unavailable_message(base_url: str) -> str:
    url = f"{base_url.rstrip('/')}/v1/models"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            if 200 <= resp.status < 300:
                return ""
            return f"The shared Qwen model is not ready at {base_url}. Start AutoRO, then retry Build PDF."
    except urllib.error.HTTPError as exc:
        if exc.code == 503:
            return f"The shared Qwen model is still loading at {base_url}. Wait until the Qwen terminal says the server is ready, then retry Build PDF."
        return f"The shared Qwen model returned HTTP {exc.code} at {base_url}. Check the Qwen terminal, then retry Build PDF."
    except (urllib.error.URLError, TimeoutError, OSError):
        return f"The shared Qwen model is not running at {base_url}. Start AutoRO with the supported launcher, then retry Build PDF."


def _write_import_record(
    paths: dict[str, Path],
    input_pdf: Path,
    payload: dict[str, Any],
    completed: subprocess.CompletedProcess[str] | None,
    error_text: str,
    parsed_for_history: dict[str, Any] | None = None,
) -> Path | None:
    paths["import_records"].mkdir(parents=True, exist_ok=True)
    prefix = _clean_prefix(str(payload.get("prefix") or "autoro_estimate"))
    record_path = paths["import_records"] / f"{int(time.time())}_{prefix}.json"
    parser_result = parsed_for_history or _parse_for_record(paths, input_pdf)
    record = {
        "created_at": int(time.time()),
        "created_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source_filename": input_pdf.name,
        "source_was_import_upload": _is_uploaded_file(input_pdf, paths),
        "source_removed_after_processing": bool(payload.get("delete_after_run")) and _is_uploaded_file(input_pdf, paths),
        "mode": str(payload.get("mode") or "preestimate"),
        "prefix": prefix,
        "history_key": prefix,
        "parser": parser_result,
        "conversion": {
            "returncode": completed.returncode if completed else None,
            "success": bool(completed and completed.returncode == 0),
            "final_pdf": _extract_final_pdf(completed.stdout) or _extract_named_pdf(completed.stdout) if completed else "",
            "error": error_text,
        },
    }
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record_path


def _parse_for_record(paths: dict[str, Path], input_pdf: Path) -> dict[str, Any]:
    if not paths["parser"].exists() or not input_pdf.exists():
        return {"status": "unavailable", "jobs": []}
    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        completed = subprocess.run(
            [sys.executable, str(paths["parser"]), str(input_pdf), str(tmp_path)],
            cwd=str(paths["root"]),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0 or not tmp_path.exists():
            return {"status": "failed", "error": (completed.stderr or completed.stdout).strip(), "jobs": []}
        parsed = json.loads(tmp_path.read_text(encoding="utf-8"))
        return {
            "status": "parsed",
            "source_filename": input_pdf.name,
            "customer": parsed.get("customer", {}),
            "vehicle": {
                "year": parsed.get("year", ""),
                "make": parsed.get("make", ""),
                "model": parsed.get("model", ""),
            },
            "vin": parsed.get("VIN", ""),
            "mileage": parsed.get("mileage", ""),
            "estimate_date": parsed.get("estimate_date", ""),
            "estimate_number": parsed.get("estimate_number", ""),
            "job_count": len(parsed.get("jobs", [])),
            "parts_confirmed": bool(parsed.get("PARTS_CONFIRMED")),
            "jobs": [
                {
                    "title": job.get("title", ""),
                    "labour_hours": job.get("labour_hours", 0),
                    "parts_retail_cad": job.get("parts_retail_cad", 0),
                    "part_desc": job.get("part_desc", ""),
                    "labour_lines": job.get("labour_lines", []),
                    "part_lines": job.get("part_lines", []),
                }
                for job in parsed.get("jobs", [])
            ],
        }
    except Exception as exc:
        return {"status": "failed", "error": str(exc), "jobs": []}
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def estimate_sanity_findings(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    jobs = parsed.get("jobs", []) or []

    # 1. Standard check: Parts with 0.0 labor
    for job in jobs:
        title = str(job.get("title") or "Estimate line")
        part_desc = str(job.get("part_desc") or "")
        labour = float(job.get("labour_hours") or 0)
        parts = float(job.get("parts_retail_cad") or 0)
        haystack = f"{title} {part_desc}".upper()
        if labour == 0.0 and parts > 0 and not has_zero_labour_override(haystack):
            findings.append({
                "severity": "review",
                "job_title": title,
                "check": "parts_without_labour",
                "message": f"Parts detected (${parts:,.2f}) but labor is 0.0 hrs.",
                "labour_hours": labour,
                "parts_retail_cad": parts,
                "recommendation": "Verify if labor is missing, or mark as 'No Charge' / 'NC'.",
            })

    # Helper classifiers
    def get_steering_type(text: str) -> str | None:
        upper = text.upper()
        if "RACK" in upper or "PINION" in upper:
            return "rack"
        if "PUMP" in upper or "P/S" in upper:
            return "pump"
        return None

    # 2. Check for misplaced parts & duplicate lines
    for i, job_a in enumerate(jobs):
        title_a = job_a.get("title", "")
        type_a = get_steering_type(title_a)
        
        # Check parts in job_a for category mismatches
        part_lines_a = job_a.get("part_lines", []) or []
        for part_desc in part_lines_a:
            type_part = get_steering_type(part_desc)
            
            # If job is a Pump job but part is a Rack/Pinion part
            if type_a == "pump" and type_part == "rack":
                # Look for a Rack job in the same estimate to suggest moving it
                rack_job_found = False
                for job_b in jobs:
                    title_b = job_b.get("title", "")
                    if get_steering_type(title_b) == "rack" and not job_b.get("part_lines"):
                        if not any(f["check"] == "misplaced_parts" and f["job_title"] == title_a for f in findings):
                            findings.append({
                                "severity": "review",
                                "job_title": title_a,
                                "check": "misplaced_parts",
                                "message": "Steering rack parts are listed under the pump job.",
                                "labour_hours": float(job_a.get("labour_hours") or 0),
                                "parts_retail_cad": float(job_a.get("parts_retail_cad") or 0),
                                "recommendation": f"Verify if parts should be moved to the '{title_b}' line in Mitchell.",
                            })
                        rack_job_found = True
                        break
                if not rack_job_found:
                    if not any(f["check"] == "mismatched_components" and f["job_title"] == title_a for f in findings):
                        findings.append({
                            "severity": "review",
                            "job_title": title_a,
                            "check": "mismatched_components",
                            "message": "Job title is steering pump but contains steering rack parts.",
                            "labour_hours": float(job_a.get("labour_hours") or 0),
                            "parts_retail_cad": float(job_a.get("parts_retail_cad") or 0),
                            "recommendation": "Verify if parts match the job title in Mitchell.",
                        })

        # Check for duplicate/split jobs (Pump vs Pump / Rack vs Rack)
        for job_b in jobs[i+1:]:
            title_b = job_b.get("title", "")
            type_b = get_steering_type(title_b)
            if type_a and type_a == type_b:
                hrs_a = float(job_a.get("labour_hours") or 0)
                hrs_b = float(job_b.get("labour_hours") or 0)
                if (hrs_a == 0.0 and hrs_b > 0.0) or (hrs_b == 0.0 and hrs_a > 0.0):
                    findings.append({
                        "severity": "review",
                        "job_title": title_a,
                        "check": "duplicate_jobs",
                        "message": f"Duplicate line for Steering {type_a.capitalize()} with '{title_b}'.",
                        "labour_hours": hrs_a,
                        "parts_retail_cad": float(job_a.get("parts_retail_cad") or 0),
                        "recommendation": "Confirm if these lines should be combined or corrected in Mitchell.",
                    })

    return findings


def has_zero_labour_override(text: str) -> bool:
    override_patterns = [
        r"\bNO\s+CHARGE\b",
        r"\bN/C\b",
        r"\bNC\b",
        r"\bNO\s+LABOU?R\b",
        r"\bLABOU?R\s+N/C\b",
        r"\bLABOU?R\s+NO\s+CHARGE\b",
        r"\b0\.00\s+OVERRIDE\b",
        r"\bZERO\s+LABOU?R\s+OK\b",
    ]
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in override_patterns)


def history_prefix(parsed: dict[str, Any], mode: str) -> str:
    return estimate_output_stem(parsed, mode)


def _clean_prefix(prefix: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", prefix.strip())
    return cleaned.strip("._-") or "autoro_estimate"


def _clean_filename(filename: str) -> str:
    name = Path(filename).name
    cleaned = re.sub(r"[^A-Za-z0-9_. -]+", "_", name.strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._-")
    return cleaned or "estimate.pdf"


def _extract_final_pdf(text: str) -> str:
    match = re.search(r"FINAL_PDF=(.+)", text)
    return match.group(1).strip() if match else ""


def _extract_named_pdf(text: str) -> str:
    match = re.search(r"(?:Pre-estimate|Quote|Proposal) PDF:\s*(.+\.pdf)", text)
    return match.group(1).strip() if match else ""

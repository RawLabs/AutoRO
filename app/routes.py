from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app import database
from app.bg_rules import bg_lookup, bg_service_options
from app.config import settings
from app.estimate_conversion import conversion_paths, get_conversion_status, preflight_estimate_conversion, resolve_output_pdf, run_estimate_conversion, save_estimate_upload_stream
from app.estimate_naming import estimate_output_stem
from app.upload_security import stream_pdf_upload
from app.model_client import ModelError, generate
from app.note_quality import analyze_note_quality
from app.intake_quality import analyze_intake_quality
from app.normalizer import normalize_translation_response
from app.operations_reports import build_month_digest, manager_answer, valid_code
from app.prompt_templates import build_advisor_queue_prompt, build_translation_prompt, build_intake_translation_prompt
from app.schemas import BGLookupRequest, CaseUpdateRequest, CorrectionRequest, EstimateConversionRequest, NoteQualityRequest, TranslationRequest, InShopUploadResponse, InShopMetadata, InShopGenerateResponse, BGServicesResponse, BGLookupResponse, NoteQualityResponse, TranslationResponse, EstimateConversionResponse, IntakeQualityRequest, IntakeQualityResponse, IntakeTranslateRequest, IntakeTranslateResponse


logger = logging.getLogger("autoro.routes")



router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
RELEASE_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "RELEASE_MANIFEST.json"

_queue_lock = threading.Lock()
_queue_is_processing = False
_inshop_parse_slot = threading.BoundedSemaphore(value=1)

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard.html")

@router.get("/api/diag")
def diag_endpoint():
    import subprocess
    import urllib.request
    import time
    try:
        ps = subprocess.check_output(["ps", "aux"]).decode()
        llama_procs = [line for line in ps.splitlines() if "llamafile" in line]
        
        # Try to ping the model directly
        started = time.time()
        try:
            req = urllib.request.Request(f"{settings.llamafile_url}/v1/models", method="GET")
            with urllib.request.urlopen(req, timeout=5) as r:
                models_resp = r.read().decode()
        except Exception as e:
            logger.warning(f"Failed to reach model server for diagnostics: {e}")
            models_resp = str(e)
            
        return {
            "llama_processes": llama_procs,
            "models_ping": models_resp,
            "ping_time": time.time() - started
        }
    except Exception as e:
        logger.exception("Diag endpoint failed")
        return {"error": str(e)}


@router.get("/translate", response_class=HTMLResponse)
def translator(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "translator.html")


@router.get("/advisor-queue", response_class=HTMLResponse)
@router.get("/advisor-translator", response_class=HTMLResponse)
def advisor_queue_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "advisor_queue.html")


@router.get("/cases", response_class=HTMLResponse)
def cases_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "cases.html")


@router.get("/bg", response_class=HTMLResponse)
def bg_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "bg_lookup.html")


@router.get("/management", response_class=HTMLResponse)
@router.get("/reports", response_class=HTMLResponse)
def management_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "management.html")


@router.get("/manage", response_class=HTMLResponse)
@router.get("/operations", response_class=HTMLResponse)
def operations_manager_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "manager.html")


@router.get("/estimate-conversion", response_class=HTMLResponse)
def estimate_conversion_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "estimate_conversion.html")


@router.get("/knowledge", response_class=HTMLResponse)
@router.get("/search", response_class=HTMLResponse)
def knowledge_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "cases.html")


@router.get("/cases/{case_id}", response_class=HTMLResponse)
def case_detail_page(request: Request, case_id: int) -> HTMLResponse:
    return templates.TemplateResponse(request, "case_detail.html", {"case_id": case_id})


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@router.get("/api/release")
def release_info() -> dict[str, Any]:
    try:
        manifest = json.loads(RELEASE_MANIFEST_PATH.read_text(encoding="utf-8"))
        release_id = str(manifest.get("release_id") or "").strip()
        if release_id:
            return {"release_id": release_id, "verified": True}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {"release_id": "UNVERIFIED", "verified": False}


@router.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": settings.model_name,
        "model_provider": settings.model_provider,
        "ollama_url": settings.ollama_url,
        "llamafile_url": settings.llamafile_url,
        "database": str(database.DB_PATH),
        "estimate_conversion": get_conversion_status(),
    }


@router.get("/api/stats")
def stats() -> dict[str, int]:
    return database.get_stats()


@router.get("/api/management/report")
def management_report() -> dict[str, Any]:
    report = database.get_management_report()
    report["estimate_conversion"] = get_conversion_status()
    return report


@router.get("/api/operations/digest")
def operations_digest(
    month: str | None = Query(default=None),
    x_manager_code: str | None = Header(default=None),
) -> dict[str, Any]:
    require_manager_code(x_manager_code)
    try:
        return build_month_digest(month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/operations/ask")
async def operations_ask(request: Request, x_manager_code: str | None = Header(default=None)) -> dict[str, Any]:
    require_manager_code(x_manager_code)
    payload = await request.json()
    try:
        digest = build_month_digest(payload.get("month"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"answer": manager_answer(str(payload.get("question") or ""), digest)}


@router.get("/api/cases")
def list_cases(
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    return {"cases": database.list_cases(search=search, limit=limit)}


@router.get("/api/cases/{case_id}")
def get_case(case_id: int) -> dict[str, Any]:
    case = database.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return {"case": case}


@router.post("/api/bg/lookup", response_model=BGLookupResponse)
def lookup_bg_rules(payload: BGLookupRequest) -> dict[str, Any]:
    raw_payload = payload_to_dict(payload)
    if raw_payload.get("service_id") is None:
        raise HTTPException(status_code=400, detail="Select the BG service proposed or performed.")
    if raw_payload.get("mileage_km") is None:
        raise HTTPException(status_code=400, detail="Mileage in km is required.")
    return {"summary": bg_lookup(raw_payload)}


@router.get("/api/bg/services", response_model=BGServicesResponse)
def bg_services() -> dict[str, Any]:
    return {"services": bg_service_options()}


@router.post("/api/note-quality", response_model=NoteQualityResponse)
def note_quality(payload: NoteQualityRequest) -> dict[str, Any]:
    return analyze_note_quality(payload_to_dict(payload))


@router.post("/api/intake/analyze", response_model=IntakeQualityResponse)
def intake_analyze(payload: IntakeQualityRequest) -> dict[str, Any]:
    return analyze_intake_quality(payload.dict())


@router.post("/api/intake/translate", response_model=IntakeTranslateResponse)
def intake_translate(payload: IntakeTranslateRequest) -> dict[str, Any]:
    if not payload.raw_text:
        raise HTTPException(status_code=400, detail="Enter a symptom or concern.")
    prompt = build_intake_translation_prompt(payload.raw_text, payload.qualifier_answers)
    try:
        result = generate(prompt, model_name=settings.model_name)
    except ModelError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    parsed_output = normalize_translation_response(result.response_text)
    translated = parsed_output.get("customer_explanation") or str(result.response_text or "").strip()
    return {"translated_text": translated}



@router.get("/api/advisor-queue/items")
def advisor_queue_items(limit: int = Query(default=100, ge=1, le=250)) -> dict[str, Any]:
    return {"items": database.list_advisor_queue_items(limit=limit)}


@router.post("/api/advisor-queue/items")
async def create_advisor_queue_item(request: Request) -> dict[str, Any]:
    payload = await request.json()
    raw_text = str(payload.get("raw_text") or "").strip()
    try:
        item = database.create_advisor_queue_item(raw_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.post("/api/advisor-queue/process-next")
def process_next_advisor_queue_item(background_tasks: BackgroundTasks) -> dict[str, Any]:
    global _queue_is_processing
    with _queue_lock:
        if not _queue_is_processing:
            _queue_is_processing = True
            background_tasks.add_task(process_advisor_queue_worker)
            return {"status": "started"}
        return {"status": "already_running"}


def process_advisor_queue_worker():
    global _queue_is_processing
    try:
        while True:
            with _queue_lock:
                item = database.claim_next_advisor_queue_item()
                if item is None:
                    _queue_is_processing = False
                    break

            try:
                prompt = build_advisor_queue_prompt(item["raw_text"])
                result = generate(prompt, model_name=settings.model_name, timeout=60)
                output = normalize_translation_response(result.response_text)
                translated = output.get("customer_explanation") or str(result.response_text or "").strip()
                database.complete_advisor_queue_item(
                    item_id=int(item["id"]),
                    translated_text=translated,
                    model_name=settings.model_name,
                    model_provider=settings.model_provider,
                    duration_ms=result.duration_ms,
                )
            except Exception as exc:
                try:
                    database.fail_advisor_queue_item(
                        item_id=int(item["id"]),
                        error=str(exc) or type(exc).__name__,
                        model_name=settings.model_name,
                        model_provider=settings.model_provider,
                    )
                except Exception:
                    pass
                continue
    finally:
        with _queue_lock:
            _queue_is_processing = False


@router.post("/api/advisor-queue/items/{item_id}/retry")
def retry_advisor_queue_item(item_id: int) -> dict[str, Any]:
    item = database.retry_advisor_queue_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return {"item": item}


@router.post("/api/advisor-queue/items/{item_id}/copied")
def copied_advisor_queue_item(item_id: int) -> dict[str, Any]:
    item = database.mark_advisor_queue_item_copied(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return {"item": item}


@router.post("/api/advisor-queue/items/{item_id}/translation")
async def update_advisor_queue_translation(item_id: int, request: Request) -> dict[str, Any]:
    payload = await request.json()
    translated_text = str(payload.get("translated_text") or "").strip()
    try:
        item = database.update_advisor_queue_translation(item_id, translated_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return {"item": item}


@router.post("/api/advisor-queue/clear")
def clear_advisor_queue_items() -> dict[str, Any]:
    return {"deleted": database.clear_advisor_queue_items()}


@router.get("/api/estimate-conversion/status")
def estimate_conversion_status() -> dict[str, Any]:
    return get_conversion_status()


@router.post("/api/estimate-conversion/upload")
async def upload_estimate_pdf(
    request: Request,
    filename: str = Query(default="estimate.pdf"),
) -> dict[str, Any]:
    try:
        return await save_estimate_upload_stream(request, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/estimate-conversion/run", response_model=EstimateConversionResponse)
def run_estimate_conversion_api(payload: EstimateConversionRequest) -> dict[str, Any]:
    raw_payload = payload_to_dict(payload)
    if not raw_payload.get("input_pdf"):
        raise HTTPException(status_code=400, detail="Enter the estimate PDF path.")
    if raw_payload.get("mode") == "proposal":
        raise HTTPException(
            status_code=409,
            detail="Custom Build has moved to its dedicated workflow. Refresh this page and try again.",
        )
    try:
        return run_estimate_conversion(raw_payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Estimate conversion timed out.") from exc


@router.get("/api/estimate-conversion/pdf")
def estimate_conversion_pdf(path: str = Query(...)) -> FileResponse:
    try:
        pdf_path = resolve_output_pdf(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name,
        content_disposition_type="inline",
    )


@router.post("/api/estimate-conversion/preflight")
def preflight_estimate_conversion_api(payload: EstimateConversionRequest) -> dict[str, Any]:
    raw_payload = payload_to_dict(payload)
    if not raw_payload.get("input_pdf"):
        raise HTTPException(status_code=400, detail="Enter the estimate PDF path.")
    try:
        return preflight_estimate_conversion(raw_payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/translate", response_model=TranslationResponse)
def translate(payload: TranslationRequest) -> dict[str, Any]:
    raw_payload = payload_to_dict(payload)
    if not any(
        [
            raw_payload.get("technician_note"),
        ]
    ):
        raise HTTPException(status_code=400, detail="Enter a technician note.")

    note_quality_result = analyze_note_quality(raw_payload)
    raw_payload["note_quality"] = note_quality_result
    case_id = database.create_case(raw_payload)
    database.log_note_quality_event(case_id, raw_payload, note_quality_result)
    approved_examples = database.find_approved_examples(
        raw_payload.get("technician_note", ""),
        category=raw_payload.get("category") or None,
    )
    prompt = build_translation_prompt(raw_payload, approved_examples=approved_examples)

    try:
        result = generate(prompt, model_name=settings.model_name)
    except ModelError as exc:
        database.create_model_run(
            case_id=case_id,
            model_name=settings.model_name,
            prompt=prompt,
            status="error",
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    parsed_output = normalize_translation_response(result.response_text)
    database.create_model_run(
        case_id=case_id,
        model_name=settings.model_name,
        prompt=prompt,
        response_text=result.response_text,
        parsed_output=parsed_output,
        status="completed",
        duration_ms=result.duration_ms,
    )
    database.update_case_translation(case_id, parsed_output, settings.model_name)

    return {
        "case_id": case_id,
        "output": parsed_output,
        "note_quality": note_quality_result,
    }


@router.post("/api/cases/{case_id}/corrections")
def save_case_correction(case_id: int, payload: CorrectionRequest) -> dict[str, Any]:
    case = database.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    if payload.status not in {"logged_only", "approved", "rejected"}:
        raise HTTPException(
            status_code=400,
            detail="Status must be logged_only, approved, or rejected.",
        )

    correction_id = database.save_correction(
        case_id=case_id,
        model_run_id=payload.model_run_id or (case.get("latest_model_run") or {}).get("id"),
        before_output=case.get("normalized_output"),
        after_output=normalize_translation_response(payload.after_output),
        approval_status=payload.status,
        correction_notes=payload.correction_notes,
    )
    return {"correction_id": correction_id}


@router.patch("/api/cases/{case_id}")
def update_case(case_id: int, payload: CaseUpdateRequest) -> dict[str, str]:
    if database.get_case(case_id) is None:
        raise HTTPException(status_code=404, detail="Case not found")
    with database.get_db() as conn:
        conn.execute(
            """
            UPDATE cases
            SET confirmed_repair = COALESCE(?, confirmed_repair),
                parts_used = COALESCE(?, parts_used),
                notes = COALESCE(?, notes),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (payload.confirmed_repair, payload.parts_used, payload.notes, case_id),
        )
    return {"status": "ok"}


def payload_to_dict(payload: TranslationRequest) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    return payload.dict()


# --- In-Shop Estimate Endpoints ---

def extract_json_object(raw: str) -> dict[str, Any]:
    import json, re
    from json import JSONDecoder
    decoder = JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            obj, _ = decoder.raw_decode(raw[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("No valid JSON object found in LLM output.")

@router.post("/api/inshop/estimate/upload")
async def upload_inshop_estimate(request: Request) -> InShopUploadResponse:
    """Upload a Mitchell ASR PDF, parse it, and create an estimate record."""
    import uuid, json
    from pathlib import Path
    upload_dir = Path(__file__).resolve().parents[1] / "app" / "static" / "inshop_temp"
    upload_dir.mkdir(parents=True, exist_ok=True)
    source_filename = Path(request.query_params.get("filename") or "estimate.pdf").name
    if not source_filename.lower().endswith(".pdf"):
        source_filename = "estimate.pdf"
    stored_filename = f"{uuid.uuid4()}.pdf"
    file_path = upload_dir / stored_filename
    from app.parse_asr_pdf import parse_asr_pdf
    if not _inshop_parse_slot.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Another PDF is being parsed. Please retry shortly.")
    try:
        await stream_pdf_upload(request, file_path)
        manifest = await run_in_threadpool(parse_asr_pdf, str(file_path))
        manifest["source_filename"] = source_filename
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse ASR PDF: {exc}")
    finally:
        _inshop_parse_slot.release()
        file_path.unlink(missing_ok=True)
    from app.database import get_db
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO inshop_estimates (asr_filename, asr_manifest, story_mappings, advisor_edits, status_flags, pdf_path) VALUES (?, ?, ?, ?, ?, ?)",
            (source_filename, json.dumps(manifest), None, None, None, None),
        )
        estimate_id = int(cursor.lastrowid)
        for idx, job in enumerate(manifest.get("jobs", [])):
            conn.execute(
                "INSERT INTO inshop_jobs (estimate_id, job_index, data) VALUES (?, ?, ?)",
                (estimate_id, idx, json.dumps(job)),
            )
    return InShopUploadResponse(estimate_id=estimate_id, manifest=manifest)

@router.post("/api/inshop/estimate/{estimate_id}/metadata")
def set_inshop_metadata(estimate_id: int, metadata: InShopMetadata) -> dict[str, str]:
    """Store advisor‑provided concern and findings for an in‑shop estimate."""
    import json
    from app.database import get_db
    edits = {"customer_concern": metadata.customer_concern, "technician_findings": metadata.technician_findings}
    with get_db() as conn:
        conn.execute(
            "UPDATE inshop_estimates SET advisor_edits = ? WHERE id = ?",
            (json.dumps(edits), estimate_id),
        )
    return {"status": "ok"}

@router.get("/api/inshop/estimate/{estimate_id}")
def get_inshop_estimate(estimate_id: int) -> dict[str, Any]:
    """Retrieve full manifest and any advisor edits for an estimate."""
    import json
    from app.database import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT asr_manifest, advisor_edits, story_mappings, pdf_path FROM inshop_estimates WHERE id = ?",
            (estimate_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Estimate not found")
    manifest = json.loads(row["asr_manifest"]) if row["asr_manifest"] else {}
    edits = json.loads(row["advisor_edits"]) if row["advisor_edits"] else {}
    mappings = json.loads(row["story_mappings"]) if row["story_mappings"] else {}
    return {
        "estimate_id": estimate_id,
        "manifest": manifest,
        "metadata": edits,
        "story_mappings": mappings,
        "pdf_path": row["pdf_path"]
    }

@router.post("/api/inshop/estimate/{estimate_id}/analyze")
async def analyze_inshop_estimate(estimate_id: int, request: Request) -> dict[str, Any]:
    """Analyze technician findings and map them to ASR jobs using the LLM."""
    import json
    from app.database import get_db
    from app.model_client import generate
    
    payload = await request.json()
    document_type = "custom_build" if payload.get("document_type") == "custom_build" else "inshop"
    raw_text = str(payload.get("raw_text") or "").strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="Pasted technician/complaint text is required.")
        
    if "--------" in raw_text:
        complaint, findings = raw_text.split("--------", 1)
    else:
        complaint = raw_text
        findings = ""
    complaint = complaint.strip()
    findings = findings.strip()
    if not complaint and not findings:
        raise HTTPException(
            status_code=400,
            detail="Enter a customer concern or technician findings before analyzing.",
        )

    with get_db() as conn:
        row = conn.execute(
            "SELECT asr_manifest FROM inshop_estimates WHERE id = ?",
            (estimate_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Estimate not found")
    manifest = json.loads(row["asr_manifest"])
    jobs = manifest.get("jobs", [])

    job_titles = [f"Job {idx}: {job['title']}" for idx, job in enumerate(jobs)]
    document_guidance = (
        "This is a custom vehicle build plan. Correct obvious spelling and capitalization in display titles "
        "and describe how each component supports the customer's intended build."
        if document_type == "custom_build"
        else "This is an in-shop service estimate based on technician findings."
    )
    priority_guidance = (
        'Use "Core Build Component", "Supporting Build Component", or "Optional Accessory".'
        if document_type == "custom_build"
        else 'Use "Severe - Repair Promptly", "Maintenance - Recommended", or "Nice to Do - Suggested".'
    )
    prompt = f"""/no_think
You are an automotive service advisor assistant. Be extremely concise.
{document_guidance}
We have these recommended services (ASR jobs) from the shop estimate:
{json.dumps(job_titles, indent=2)}

Customer request or build goal:
{complaint}

We have these technician inspection findings:
{findings}

Match the technician findings to the ASR jobs and add a short customer-friendly explanation.
Use service advisor psychology principles to build informative, professional, and reassuring explanations:
- State clearly and objectively what was found (condition).
- Explain "Why this service matters" in a constructive, reassuring, and confidence-building way. Avoid using unnecessarily scary or alarmist wording. For example:
  - Instead of "can lead to engine damage", say "protects critical internal components and prevents premature engine wear".
  - Instead of "can lead to brake failure", say "maintains responsive braking control and ensures safety on the road".
  - Instead of "dangerous", say "helps prevent potential secondary component concerns".
- Determine the priority:
  - "Severe - Repair Promptly" (for safety hazards, active severe leaks, starting/braking failures)
  - "Maintenance - Recommended" (for scheduled fluid services, mileage interval items, preventive wear replacements)
  - "Nice to Do - Suggested" (for minor concerns, non-critical/aesthetic adjustments)
For this document: {priority_guidance}

Return a JSON object in this exact shape (do not include markdown formatting or extra text outside the JSON).
Correct obvious spelling and grammar in the two summary fields without changing their meaning:
{{
  "customer_summary": "<polished customer concern or build goal>",
  "technician_summary": "<polished technician findings or build notes>",
  "jobs": [
    {{
      "job_index": <integer job index, e.g., 0, 1, etc.>,
      "display_title": "<spell-checked customer-facing job title>",
      "priority": "<document-appropriate priority>",
      "tech_found": "<one short condition sentence grounded in the supplied findings>",
      "recommendation": "<one short recommendation grounded in the estimate>",
      "why_matters": "<one short sentence explaining why this service matters>"
    }}
  ]
}}
"""
    model_timeout = 45
    model_max_tokens = 768
    if document_type == "custom_build":
        # The custom-build document gets its technical explanations from the
        # deterministic rules below. Keep AI focused on the small task it does
        # well on CPU: spelling, grammar, and customer-facing display titles.
        prompt = f"""/no_think
Correct obvious spelling, grammar, and capitalization without changing meaning.
Preserve automotive acronyms, brand names, part numbers, job order, and pricing.
Return JSON only in this exact shape:
{{"customer_summary":"<polished build goal>","technician_summary":"<polished build notes>","jobs":[{{"job_index":0,"display_title":"<clean title>"}}]}}
Build goal: {complaint}
Build notes: {findings}
Job titles: {json.dumps(job_titles, separators=(',', ':'))}
"""
        model_timeout = 15
        model_max_tokens = 256
    # Build a complete source-grounded result first. AI may improve the
    # matching and explanation, but it never has to recreate the estimate.
    story_mappings = {}
    for idx, job in enumerate(jobs):
        title = str(job.get("title") or "recommended service").strip()
        title_upper = title.upper()
        priority = "Maintenance - Recommended"
        if any(word in title_upper for word in ("BRAKE", "STEERING", "CONTROL ARM", "BALL JOINT", "SHOCK", "SUSPENSION")):
            priority = "Severe - Repair Promptly"
        elif any(word in title_upper for word in ("ROOF RACK", "TENT", "COSMETIC")):
            priority = "Nice to Do - Suggested"
        if document_type == "custom_build":
            priority = "Optional Accessory" if any(word in title_upper for word in ("ROOF RACK", "TENT", "COSMETIC")) else "Core Build Component"
        included = list(job.get("labour_lines") or job.get("part_lines") or [])[:4]
        if not included:
            included = [f"Complete the quoted {title.lower()} work"]
        fallback_why = "Helps complete the requested work with the scope reviewed before authorization."
        if document_type == "custom_build":
            try:
                from estimate_conversion.workspace.estimates.build_preestimate_pdf import value_text
                fallback_why = value_text(job)
            except Exception:
                fallback_why = "Supports the requested build while keeping fitment and final scope reviewable."
        story_mappings[str(idx)] = {
            "job_index": idx,
            "display_title": title.title() if title.isupper() else title,
            "priority": priority,
            "tech_found": "Selected as part of the customer's requested custom build." if document_type == "custom_build" else (findings or "Requested estimate item; confirm condition with the customer and technician."),
            "recommendation": f"Complete {title.lower()} as outlined in the estimate.",
            "why_matters": fallback_why,
            "repair_includes": included,
        }

    try:
        result = await run_in_threadpool(
            generate,
            prompt,
            model_name=settings.model_name,
            timeout=model_timeout,
            max_tokens=model_max_tokens,
        )
        ai_output = extract_json_object(result.response_text)
    except Exception as exc:
        logger.warning("In-shop AI enrichment unavailable; using source-grounded fallback: %s", exc)
        ai_output = {"jobs": []}

    generated_jobs = ai_output.get("jobs", [])
    polished_customer = ai_output.get("customer_summary")
    polished_findings = ai_output.get("technician_summary")
    if isinstance(polished_customer, str) and polished_customer.strip():
        complaint = polished_customer.strip()
    if isinstance(polished_findings, str) and polished_findings.strip():
        findings = polished_findings.strip()
    for gj in generated_jobs:
        idx = gj.get("job_index")
        if isinstance(idx, int) and 0 <= idx < len(jobs):
            mapping = story_mappings[str(idx)]
            for key in ("display_title", "priority", "tech_found", "recommendation", "why_matters"):
                value = gj.get(key)
                if isinstance(value, str) and value.strip():
                    mapping[key] = value.strip()

    adviser_edits = {
        "customer_concern": complaint,
        "technician_findings": findings,
        "document_type": document_type,
    }
    with get_db() as conn:
        conn.execute(
            "UPDATE inshop_estimates SET story_mappings = ?, advisor_edits = ? WHERE id = ?",
            (json.dumps(story_mappings), json.dumps(adviser_edits), estimate_id),
        )
        conn.execute("DELETE FROM inshop_stories WHERE estimate_id = ?", (estimate_id,))
        for idx_str, mapping in story_mappings.items():
            conn.execute(
                "INSERT INTO inshop_stories (estimate_id, job_index, condition, correction, flags) VALUES (?, ?, ?, ?, ?)",
                (estimate_id, int(idx_str), mapping.get("tech_found"), mapping.get("recommendation"), json.dumps(mapping)),
            )

    return {
        "customer_concern": complaint,
        "technician_findings": findings,
        "jobs": story_mappings
    }

@router.post("/api/inshop/estimate/{estimate_id}/save")
async def save_inshop_estimate(estimate_id: int, request: Request) -> dict[str, str]:
    """Save finalized stories, concern, and findings to DB."""
    import json
    from app.database import get_db
    payload = await request.json()
    customer_concern = str(payload.get("customer_concern") or "").strip()
    technician_findings = str(payload.get("technician_findings") or "").strip()
    current_ro_total = payload.get("current_ro_total")
    story_mappings = payload.get("story_mappings") or {}

    adviser_edits = {
        "customer_concern": customer_concern,
        "technician_findings": technician_findings,
        "current_ro_total": current_ro_total
    }
    with get_db() as conn:
        conn.execute(
            "UPDATE inshop_estimates SET story_mappings = ?, advisor_edits = ? WHERE id = ?",
            (json.dumps(story_mappings), json.dumps(adviser_edits), estimate_id),
        )
        conn.execute("DELETE FROM inshop_stories WHERE estimate_id = ?", (estimate_id,))
        for idx_str, mapping in story_mappings.items():
            conn.execute(
                "INSERT INTO inshop_stories (estimate_id, job_index, condition, correction, flags) VALUES (?, ?, ?, ?, ?)",
                (estimate_id, int(idx_str), mapping.get("tech_found"), mapping.get("recommendation"), json.dumps(mapping)),
            )
    return {"status": "ok"}

@router.post("/api/inshop/estimate/{estimate_id}/generate-pdf")
def generate_inshop_pdf(estimate_id: int) -> InShopGenerateResponse:
    """Generate a landscape PDF for the estimate using the real builder."""
    import json, sys
    from pathlib import Path
    from app.database import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT asr_manifest, story_mappings, advisor_edits FROM inshop_estimates WHERE id = ?",
            (estimate_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Estimate not found")
        
    manifest = json.loads(row["asr_manifest"])
    story_mappings = json.loads(row["story_mappings"]) if row["story_mappings"] else {}
    advisor_edits = json.loads(row["advisor_edits"]) if row["advisor_edits"] else {}
    
    # Import build_inshop_pdf from workspace script dir
    builder_dir = Path(__file__).resolve().parents[1] / "estimate_conversion" / "workspace" / "estimates"
    sys.path.insert(0, str(builder_dir))
    try:
        from build_inshop_pdf import build_inshop_pdf
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"PDF builder script not found: {exc}")
        
    output_dir = conversion_paths()["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    
    document_type = "custom_build" if advisor_edits.get("document_type") == "custom_build" else "inshop"
    out_name = f"{estimate_output_stem(manifest, document_type)}.pdf"
    out_path = output_dir / out_name
    
    try:
        build_inshop_pdf(manifest, story_mappings, advisor_edits, out_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}")
        
    with get_db() as conn:
        conn.execute(
            "UPDATE inshop_estimates SET pdf_path = ? WHERE id = ?",
            (str(out_path), estimate_id),
        )
    return InShopGenerateResponse(pdf_path=str(out_path))

@router.get("/api/inshop/estimate/{estimate_id}/pdf")
def stream_inshop_pdf(estimate_id: int) -> FileResponse:
    """Stream the generated PDF for an estimate."""
    from app.database import get_db
    from pathlib import Path
    with get_db() as conn:
        row = conn.execute(
            "SELECT pdf_path FROM inshop_estimates WHERE id = ?",
            (estimate_id,),
        ).fetchone()
    if row is None or not row["pdf_path"]:
        raise HTTPException(status_code=404, detail="PDF not generated yet")
    pdf_path = Path(row["pdf_path"]).resolve()
    if not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="PDF file missing")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name,
        content_disposition_type="inline",
    )

@router.get("/inshop-estimate", response_class=HTMLResponse)
def inshop_estimate_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "estimate_inshop.html")

def require_manager_code(code: str | None) -> None:
    if not valid_code(code):
        raise HTTPException(status_code=403, detail="Management security code required.")

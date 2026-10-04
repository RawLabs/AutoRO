from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TranslationRequest(BaseModel):
    technician_name: str = Field(default="")
    customer_complaint: str = Field(default="")
    advisor_note: str = Field(default="")
    technician_note: str = Field(default="")
    category: str = Field(default="")
    vehicle_year: int | None = None
    vehicle_make: str = Field(default="")
    vehicle_model: str = Field(default="")
    vehicle_engine: str = Field(default="")
    mileage: int | None = None
    symptoms_tags: str = Field(default="")
    qualifier_answers: dict[str, str] = Field(default_factory=dict)


class NoteQualityRequest(BaseModel):
    technician_note: str = Field(default="")
    category: str = Field(default="")
    qualifier_answers: dict[str, str] = Field(default_factory=dict)


class CorrectionRequest(BaseModel):
    after_output: dict[str, Any]
    status: str = Field(default="logged_only")
    correction_notes: str | None = None
    model_run_id: int | None = None


class CaseUpdateRequest(BaseModel):
    confirmed_repair: str | None = None
    parts_used: str | None = None
    notes: str | None = None


class BGLookupRequest(BaseModel):
    service_id: int | None = None
    service_status: str = Field(default="proposed")
    coverage_basis: str = Field(default="initial")
    year: int | None = None
    make: str = Field(default="")
    model: str = Field(default="")
    mileage_km: int | None = None
    fuel_type: str = Field(default="")
    transmission_type: str = Field(default="")


class EstimateConversionRequest(BaseModel):
    input_pdf: str = Field(default="")
    mode: str = Field(default="preestimate")
    prefix: str = Field(default="autoro_estimate")
    model_name: str = Field(default="")
    delete_after_run: bool = Field(default=False)
    sanity_confirmed: bool = Field(default=False)
    include_part_details: bool = Field(default=False)


class InShopUploadResponse(BaseModel):
    estimate_id: int
    manifest: dict

class InShopMetadata(BaseModel):
    customer_concern: str
    technician_findings: str

class InShopGenerateResponse(BaseModel):
    pdf_path: str


# --- Response Models for API Documentation ---

class NoteQualityField(BaseModel):
    key: str
    label: str
    options: list[str] = []
    detected: bool
    selected: str
    missing: bool


class NoteQualityResponse(BaseModel):
    pack: str
    label: str
    fields: list[NoteQualityField] = []
    missing_fields: list[str] = []
    missing_labels: list[str] = []
    quick_options: list[Any] = []
    qualifier_answers: dict[str, Any] = {}
    has_guidance: bool
    message: str | None = None


class NormalizedTranslationOutput(BaseModel):
    customer_explanation: str


class TranslationResponse(BaseModel):
    case_id: int
    output: NormalizedTranslationOutput
    note_quality: NoteQualityResponse


class BGServiceOption(BaseModel):
    id: int
    service_category: str
    service_name: str
    system_coverage: str
    fuel_type: str | None = None
    transmission_applicability: str | None = None
    interval_km: int | None = None


class BGServicesResponse(BaseModel):
    services: list[BGServiceOption]


class BGLookupResult(BaseModel):
    vehicle: dict[str, Any]
    coverage_basis: str
    selected_service_status: str
    selected_service: dict[str, Any] | None = None
    likely_plan_tier: dict[str, Any] | None = None
    advisor_summary: str
    eligible_bg_systems: list[str] = []
    qualifying_services: list[dict[str, Any]] = []
    service_interval_reminders: list[str] = []
    coverage_terms: list[str] = []
    roadside: list[str] = []
    enrollment_card_reminder: str
    verification_notice: str
    rule_log: list[str] = []
    customer_explanation: str


class BGLookupResponse(BaseModel):
    summary: BGLookupResult


class EstimateConversionResponse(BaseModel):
    status: str
    mode: str
    model_provider: str
    model: str
    prefix: str
    pdf: str | None = None
    stdout: str = ""
    stderr: str = ""
    technical_record: str | None = None
    import_cleanup: str | None = None


# --- Intake Quality & Translation Schemas ---

class IntakeQualityRequest(BaseModel):
    raw_text: str = Field(default="")
    qualifier_answers: dict[str, str] = Field(default_factory=dict)


class IntakeQualityResponse(BaseModel):
    pack: str
    label: str
    fields: list[NoteQualityField] = []
    missing_fields: list[str] = []
    missing_labels: list[str] = []
    quick_options: list[Any] = []
    qualifier_answers: dict[str, Any] = {}
    has_guidance: bool
    message: str | None = None


class IntakeTranslateRequest(BaseModel):
    raw_text: str = Field(default="")
    qualifier_answers: dict[str, str] = Field(default_factory=dict)


class IntakeTranslateResponse(BaseModel):
    translated_text: str



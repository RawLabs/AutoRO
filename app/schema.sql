PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER,
    make TEXT,
    model TEXT,
    engine TEXT,
    mileage INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id INTEGER,
    technician_name TEXT,
    raw_customer_complaint TEXT,
    advisor_note TEXT,
    technician_note TEXT,
    technician_note_raw TEXT,
    raw_input_json TEXT NOT NULL,
    normalized_output_json TEXT,
    model_translation TEXT,
    corrected_output_json TEXT,
    corrected_translation TEXT,
    model_name TEXT,
    category TEXT,
    symptoms TEXT,
    likely_system TEXT,
    confirmed_repair TEXT,
    parts_used TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'logged_only',
    approval_status TEXT NOT NULL DEFAULT 'logged_only',
    clarification_category TEXT,
    missing_fields_json TEXT,
    qualifier_answers_json TEXT,
    date_created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
);

CREATE TABLE IF NOT EXISTS note_quality_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER,
    technician_name TEXT,
    category TEXT,
    clarification_category TEXT,
    missing_fields_json TEXT,
    qualifier_answers_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS advisor_translation_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_text TEXT NOT NULL,
    translated_text TEXT,
    status TEXT NOT NULL DEFAULT 'waiting',
    error TEXT,
    model_name TEXT,
    model_provider TEXT,
    copied_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS model_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    prompt TEXT NOT NULL,
    response_text TEXT,
    parsed_output_json TEXT,
    status TEXT NOT NULL,
    error TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    model_run_id INTEGER,
    before_output_json TEXT,
    after_output_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'logged_only',
    correction_notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (model_run_id) REFERENCES model_runs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS case_tags (
    case_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (case_id, tag_id),
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cases_created ON cases(date_created);
CREATE INDEX IF NOT EXISTS idx_cases_likely_system ON cases(likely_system);
CREATE INDEX IF NOT EXISTS idx_vehicles_lookup ON vehicles(make, model, engine);
CREATE INDEX IF NOT EXISTS idx_model_runs_case ON model_runs(case_id);
CREATE INDEX IF NOT EXISTS idx_corrections_case ON corrections(case_id);
CREATE INDEX IF NOT EXISTS idx_note_quality_case ON note_quality_events(case_id);
CREATE INDEX IF NOT EXISTS idx_note_quality_tech ON note_quality_events(technician_name);
CREATE INDEX IF NOT EXISTS idx_advisor_queue_status ON advisor_translation_queue(status, created_at);
CREATE INDEX IF NOT EXISTS idx_advisor_queue_created ON advisor_translation_queue(created_at);
-- Add In‑Shop Estimate tables
CREATE TABLE IF NOT EXISTS inshop_estimates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asr_filename TEXT NOT NULL,
    asr_manifest JSON NOT NULL,
    story_mappings JSON,
    advisor_edits JSON,
    status_flags JSON,
    pdf_path TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inshop_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    estimate_id INTEGER NOT NULL,
    job_index INTEGER NOT NULL,
    data JSON NOT NULL,
    FOREIGN KEY (estimate_id) REFERENCES inshop_estimates(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS inshop_stories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    estimate_id INTEGER NOT NULL,
    job_index INTEGER,
    condition TEXT,
    correction TEXT,
    flags JSON,
    FOREIGN KEY (estimate_id) REFERENCES inshop_estimates(id) ON DELETE CASCADE
);


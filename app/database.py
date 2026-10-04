from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.config import settings
from app.normalizer import normalize_translation_response


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / settings.db_path
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
BACKUP_DIR = DB_PATH.parent / "backups"
logger = logging.getLogger("autoro.database")


def _connect(path: Path | None = None) -> sqlite3.Connection:
    path = DB_PATH if path is None else path
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        ensure_case_columns(conn)
        ensure_note_quality_tables(conn)
        ensure_advisor_queue_table(conn)


def check_and_recover_database() -> str:
    """Verify the database and restore the newest healthy backup if needed."""
    if not DB_PATH.exists():
        return "new"
    try:
        with closing(_connect()) as conn:
            result = conn.execute("PRAGMA quick_check").fetchone()[0]
        if result == "ok":
            return "healthy"
    except sqlite3.Error as exc:
        logger.error("Database integrity check failed: %s", exc)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    candidates = sorted(BACKUP_DIR.glob("autoro-*.db"), reverse=True)
    for backup in candidates:
        try:
            with closing(_connect(backup)) as conn:
                if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    continue
            quarantined = DB_PATH.with_name(f"{DB_PATH.name}.corrupt")
            counter = 1
            while quarantined.exists():
                quarantined = DB_PATH.with_name(f"{DB_PATH.name}.corrupt.{counter}")
                counter += 1
            DB_PATH.replace(quarantined)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{DB_PATH}{suffix}")
                if sidecar.exists():
                    sidecar.replace(Path(f"{quarantined}{suffix}"))
            shutil.copy2(backup, DB_PATH)
            logger.warning("Recovered database from %s; damaged copy kept at %s", backup, quarantined)
            return "recovered"
        except (OSError, sqlite3.Error) as exc:
            logger.warning("Backup %s was not usable: %s", backup, exc)
    raise RuntimeError("Database is damaged and no healthy backup is available; original file was preserved")


def create_daily_backup() -> Path | None:
    """Create one transactionally consistent SQLite backup per UTC day."""
    if not DB_PATH.exists():
        return None
    from datetime import datetime, timezone

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"autoro-{datetime.now(timezone.utc):%Y-%m-%d}.db"
    if target.exists():
        return target
    temporary = target.with_suffix(".db.part")
    try:
        with closing(_connect()) as source, closing(_connect(temporary)) as destination:
            source.backup(destination)
        temporary.replace(target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def ensure_case_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(cases)").fetchall()
    }
    if "approval_status" not in columns:
        conn.execute(
            "ALTER TABLE cases ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'logged_only'"
        )
    add_case_text_column(conn, columns, "technician_note_raw")
    add_case_text_column(conn, columns, "model_translation")
    add_case_text_column(conn, columns, "corrected_translation")
    add_case_text_column(conn, columns, "model_name")
    add_case_text_column(conn, columns, "category")
    add_case_text_column(conn, columns, "technician_name")
    add_case_text_column(conn, columns, "clarification_category")
    add_case_text_column(conn, columns, "missing_fields_json")
    add_case_text_column(conn, columns, "qualifier_answers_json")
    conn.execute(
        """
        UPDATE cases
        SET approval_status = CASE
            WHEN status IN ('approved', 'rejected', 'logged_only') THEN status
            WHEN status IN ('accepted', 'edited', 'saved') THEN 'approved'
            ELSE 'logged_only'
        END
        WHERE approval_status IS NULL
           OR approval_status = ''
           OR approval_status NOT IN ('logged_only', 'approved', 'rejected')
           OR (approval_status = 'logged_only' AND status IN ('accepted', 'edited', 'saved'))
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cases_approval_status ON cases(approval_status)"
    )
    conn.execute(
        """
        UPDATE cases
        SET technician_note_raw = COALESCE(NULLIF(technician_note_raw, ''), technician_note)
        WHERE technician_note IS NOT NULL
        """
    )
    conn.execute(
        """
        UPDATE cases
        SET model_name = (
            SELECT mr.model_name
            FROM model_runs mr
            WHERE mr.case_id = cases.id
            ORDER BY mr.created_at DESC, mr.id DESC
            LIMIT 1
        )
        WHERE model_name IS NULL OR model_name = ''
        """
    )
    backfill_translation_columns(conn)


def backfill_translation_columns(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, normalized_output_json, corrected_output_json,
               model_translation, corrected_translation
        FROM cases
        """
    ).fetchall()
    for row in rows:
        model_translation = row["model_translation"]
        corrected_translation = row["corrected_translation"]
        if not model_translation:
            normalized_output = normalize_translation_response(
                loads(row["normalized_output_json"], {})
            )
            model_translation = normalized_output.get("customer_explanation", "")
        if not corrected_translation:
            corrected_output = normalize_translation_response(
                loads(row["corrected_output_json"], {})
            )
            corrected_translation = corrected_output.get("customer_explanation", "")
        if model_translation or corrected_translation:
            conn.execute(
                """
                UPDATE cases
                SET model_translation = COALESCE(NULLIF(model_translation, ''), ?),
                    corrected_translation = COALESCE(NULLIF(corrected_translation, ''), ?)
                WHERE id = ?
                """,
                (model_translation, corrected_translation, row["id"]),
            )


def add_case_text_column(conn: sqlite3.Connection, columns: set[str], name: str) -> None:
    if name not in columns:
        conn.execute(f"ALTER TABLE cases ADD COLUMN {name} TEXT")


def ensure_note_quality_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
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
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_note_quality_case ON note_quality_events(case_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_note_quality_tech ON note_quality_events(technician_name)")


def ensure_advisor_queue_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
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
        )
        """
    )
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(advisor_translation_queue)").fetchall()
    }
    for name in ("translated_text", "error", "model_name", "model_provider", "copied_at", "completed_at", "duration_ms"):
        if name not in columns:
            col_type = "INTEGER" if name == "duration_ms" else "TEXT"
            conn.execute(f"ALTER TABLE advisor_translation_queue ADD COLUMN {name} {col_type}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_advisor_queue_status ON advisor_translation_queue(status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_advisor_queue_created ON advisor_translation_queue(created_at)")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def create_advisor_queue_item(raw_text: str) -> dict[str, Any]:
    text = " ".join(str(raw_text or "").split())
    if not text:
        raise ValueError("Advisor line is required.")
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO advisor_translation_queue (raw_text, status)
            VALUES (?, 'waiting')
            """,
            (text,),
        )
        item_id = int(cursor.lastrowid)
        return get_advisor_queue_item_conn(conn, item_id)


def list_advisor_queue_items(limit: int = 100) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM advisor_translation_queue
            ORDER BY
                CASE status
                    WHEN 'translating' THEN 0
                    WHEN 'waiting' THEN 1
                    WHEN 'failed' THEN 2
                    ELSE 3
                END,
                created_at DESC,
                id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_advisor_queue_item(item_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM advisor_translation_queue WHERE id = ?",
            (item_id,),
        ).fetchone()
        return row_to_dict(row)


def get_advisor_queue_item_conn(conn: sqlite3.Connection, item_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM advisor_translation_queue WHERE id = ?",
        (item_id,),
    ).fetchone()
    return dict(row)


def claim_next_advisor_queue_item() -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM advisor_translation_queue
            WHERE status = 'waiting'
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        item_id = int(row["id"])
        conn.execute(
            """
            UPDATE advisor_translation_queue
            SET status = 'translating',
                error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (item_id,),
        )
        return get_advisor_queue_item_conn(conn, item_id)


def complete_advisor_queue_item(
    item_id: int,
    translated_text: str,
    model_name: str,
    model_provider: str,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE advisor_translation_queue
            SET translated_text = ?,
                status = 'done',
                error = NULL,
                model_name = ?,
                model_provider = ?,
                duration_ms = ?,
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (translated_text, model_name, model_provider, duration_ms, item_id),
        )
        return get_advisor_queue_item_conn(conn, item_id)


def fail_advisor_queue_item(
    item_id: int,
    error: str,
    model_name: str | None = None,
    model_provider: str | None = None,
) -> dict[str, Any]:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE advisor_translation_queue
            SET status = 'failed',
                error = ?,
                model_name = COALESCE(?, model_name),
                model_provider = COALESCE(?, model_provider),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (error, model_name, model_provider, item_id),
        )
        return get_advisor_queue_item_conn(conn, item_id)


def retry_advisor_queue_item(item_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM advisor_translation_queue WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            """
            UPDATE advisor_translation_queue
            SET status = 'waiting',
                error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (item_id,),
        )
        return get_advisor_queue_item_conn(conn, item_id)


def mark_advisor_queue_item_copied(item_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM advisor_translation_queue WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            """
            UPDATE advisor_translation_queue
            SET copied_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (item_id,),
        )
        return get_advisor_queue_item_conn(conn, item_id)


def update_advisor_queue_translation(item_id: int, translated_text: str) -> dict[str, Any] | None:
    text = str(translated_text or "").strip()
    if not text:
        raise ValueError("Translated text is required.")
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM advisor_translation_queue WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            """
            UPDATE advisor_translation_queue
            SET translated_text = ?,
                status = 'done',
                error = NULL,
                updated_at = CURRENT_TIMESTAMP,
                completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)
            WHERE id = ?
            """,
            (text, item_id),
        )
        return get_advisor_queue_item_conn(conn, item_id)


def clear_advisor_queue_items() -> int:
    with get_db() as conn:
        cursor = conn.execute(
            """
            DELETE FROM advisor_translation_queue
            WHERE status != 'translating'
            """
        )
        return int(cursor.rowcount or 0)


def create_case(payload: dict[str, Any]) -> int:
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO vehicles (year, make, model, engine, mileage)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload.get("vehicle_year"),
                payload.get("vehicle_make"),
                payload.get("vehicle_model"),
                payload.get("vehicle_engine"),
                payload.get("mileage"),
            ),
        )
        vehicle_id = cursor.lastrowid
        cursor = conn.execute(
            """
            INSERT INTO cases (
                vehicle_id, technician_name, raw_customer_complaint, advisor_note, technician_note,
                technician_note_raw, raw_input_json, symptoms, category, status, approval_status
                , clarification_category, missing_fields_json, qualifier_answers_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'logged_only', 'logged_only', ?, ?, ?)
            """,
            (
                vehicle_id,
                payload.get("technician_name"),
                payload.get("customer_complaint"),
                payload.get("advisor_note"),
                payload.get("technician_note"),
                payload.get("technician_note"),
                dumps(payload),
                payload.get("symptoms_tags"),
                payload.get("category"),
                (payload.get("note_quality") or {}).get("pack"),
                dumps((payload.get("note_quality") or {}).get("missing_fields", [])),
                dumps(payload.get("qualifier_answers", {})),
            ),
        )
        case_id = cursor.lastrowid
        upsert_case_tags(conn, case_id, payload.get("symptoms_tags", ""))
        return int(case_id)


def update_case_translation(case_id: int, output: dict[str, Any], model_name: str) -> None:
    model_translation = output.get("customer_explanation", "")
    with get_db() as conn:
        conn.execute(
            """
            UPDATE cases
            SET normalized_output_json = ?, model_translation = ?, model_name = ?,
                likely_system = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (dumps(output), model_translation, model_name, "", case_id),
        )


def log_note_quality_event(case_id: int, payload: dict[str, Any], note_quality: dict[str, Any]) -> None:
    answers = payload.get("qualifier_answers", {})
    if not isinstance(answers, dict):
        answers = {}
    if not note_quality.get("has_guidance") and not answers.get("__nudge_action"):
        return
    missing_fields = note_quality.get("missing_fields", [])
    if not missing_fields and answers.get("__nudge_missing_fields"):
        missing_fields = [
            field.strip()
            for field in str(answers.get("__nudge_missing_fields", "")).split(",")
            if field.strip()
        ]
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO note_quality_events (
                case_id, technician_name, category, clarification_category,
                missing_fields_json, qualifier_answers_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                payload.get("technician_name"),
                payload.get("category"),
                note_quality.get("pack") or answers.get("__nudge_pack"),
                dumps(missing_fields),
                dumps(answers),
            ),
        )


def create_model_run(
    case_id: int,
    model_name: str,
    prompt: str,
    status: str,
    response_text: str | None = None,
    parsed_output: dict[str, Any] | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
) -> int:
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO model_runs (
                case_id, model_name, prompt, response_text, parsed_output_json,
                status, error, duration_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                model_name,
                prompt,
                response_text,
                dumps(parsed_output) if parsed_output is not None else None,
                status,
                error,
                duration_ms,
            ),
        )
        return int(cursor.lastrowid)


def save_correction(
    case_id: int,
    model_run_id: int | None,
    before_output: dict[str, Any] | None,
    after_output: dict[str, Any],
    approval_status: str,
    correction_notes: str | None,
) -> int:
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO corrections (
                case_id, model_run_id, before_output_json, after_output_json,
                status, correction_notes
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                model_run_id,
                dumps(before_output) if before_output is not None else None,
                dumps(after_output),
                approval_status,
                correction_notes,
            ),
        )
        conn.execute(
            """
            UPDATE cases
            SET corrected_output_json = ?, status = ?, approval_status = ?,
                corrected_translation = ?,
                notes = COALESCE(?, notes),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                dumps(after_output),
                approval_status,
                approval_status,
                after_output.get("customer_explanation", ""),
                correction_notes,
                case_id,
            ),
        )
        return int(cursor.lastrowid)


def get_case(case_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        case = row_to_dict(
            conn.execute(
                """
                SELECT c.*, v.year, v.make, v.model, v.engine, v.mileage
                FROM cases c
                LEFT JOIN vehicles v ON v.id = c.vehicle_id
                WHERE c.id = ?
                """,
                (case_id,),
            ).fetchone()
        )
        if case is None:
            return None

        latest_run = row_to_dict(
            conn.execute(
                """
                SELECT * FROM model_runs
                WHERE case_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (case_id,),
            ).fetchone()
        )
        corrections = [
            row_to_dict(row)
            for row in conn.execute(
                """
                SELECT * FROM corrections
                WHERE case_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (case_id,),
            ).fetchall()
        ]

    case["raw_input"] = loads(case.pop("raw_input_json"), {})
    normalized_output = loads(case.pop("normalized_output_json"), {})
    corrected_output = loads(case.pop("corrected_output_json"), {})
    case["normalized_output"] = normalize_translation_response(normalized_output) if normalized_output else {}
    case["corrected_output"] = normalize_translation_response(corrected_output) if corrected_output else {}
    if latest_run:
        parsed_output = loads(latest_run.pop("parsed_output_json"), {})
        latest_run["parsed_output"] = (
            normalize_translation_response(parsed_output) if parsed_output else {}
        )
    case["latest_model_run"] = latest_run
    for correction in corrections:
        before_output = loads(correction.pop("before_output_json"), {})
        after_output = loads(correction.pop("after_output_json"), {})
        correction["before_output"] = (
            normalize_translation_response(before_output) if before_output else {}
        )
        correction["after_output"] = normalize_translation_response(after_output) if after_output else {}
    case["corrections"] = corrections
    return case


def list_cases(search: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if search:
        needle = f"%{search.lower()}%"
        params.extend([needle] * 14)
        where = """
        WHERE lower(COALESCE(c.raw_customer_complaint, '')) LIKE ?
           OR lower(COALESCE(c.advisor_note, '')) LIKE ?
           OR lower(COALESCE(c.technician_note, '')) LIKE ?
           OR lower(COALESCE(c.technician_note_raw, '')) LIKE ?
           OR lower(COALESCE(c.model_translation, '')) LIKE ?
           OR lower(COALESCE(c.corrected_translation, '')) LIKE ?
           OR lower(COALESCE(c.category, '')) LIKE ?
           OR lower(COALESCE(c.normalized_output_json, '')) LIKE ?
           OR lower(COALESCE(c.corrected_output_json, '')) LIKE ?
           OR lower(COALESCE(c.symptoms, '')) LIKE ?
           OR lower(COALESCE(c.likely_system, '')) LIKE ?
           OR lower(COALESCE(v.make, '')) LIKE ?
           OR lower(COALESCE(v.model, '')) LIKE ?
           OR lower(COALESCE(v.engine, '')) LIKE ?
        """

    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT c.id, c.raw_customer_complaint, c.technician_note, c.technician_note_raw,
                   c.model_translation, c.corrected_translation, c.model_name,
                   c.category, c.symptoms, c.likely_system,
                   c.status, c.approval_status, c.date_created, c.updated_at,
                   v.year, v.make, v.model, v.engine, v.mileage
            FROM cases c
            LEFT JOIN vehicles v ON v.id = c.vehicle_id
            {where}
            ORDER BY c.date_created DESC, c.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def find_approved_examples(
    technician_note: str,
    category: str | None = None,
    limit: int = 2,
) -> list[dict[str, str]]:
    tokens = tokenize_search_text(technician_note)
    with get_db() as conn:
        rows = fetch_approved_example_rows(conn, category)
        if category and len(rows) < limit:
            seen_notes = {row["technician_note_raw"] for row in rows}
            fallback_rows = fetch_approved_example_rows(conn, None)
            rows.extend(
                row for row in fallback_rows if row["technician_note_raw"] not in seen_notes
            )

    scored: list[tuple[int, str, dict[str, str]]] = []
    for row in rows:
        note = row["technician_note_raw"]
        correction = row["corrected_translation"]
        example_tokens = tokenize_search_text(note)
        score = len(tokens.intersection(example_tokens)) if tokens else 0
        scored.append(
            (
                score,
                row["date_created"],
                {
                    "technician_note_raw": note,
                    "corrected_translation": correction,
                },
            )
        )

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if any(score > 0 for score, _date, _example in scored):
        return [example for score, _date, example in scored if score > 0][:limit]
    return [example for _score, _date, example in scored[:limit]]


def fetch_approved_example_rows(
    conn: sqlite3.Connection,
    category: str | None,
) -> list[sqlite3.Row]:
    params: list[Any] = []
    category_clause = ""
    if category:
        category_clause = "AND category = ?"
        params.append(category)

    return conn.execute(
        f"""
        SELECT technician_note_raw, corrected_translation, date_created
        FROM cases
        WHERE approval_status = 'approved'
          AND COALESCE(technician_note_raw, '') != ''
          AND COALESCE(corrected_translation, '') != ''
          {category_clause}
        ORDER BY date_created DESC, id DESC
        LIMIT 100
        """,
        params,
    ).fetchall()


def tokenize_search_text(text: str | None) -> set[str]:
    if not text:
        return set()
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1
    }


def get_stats() -> dict[str, int]:
    with get_db() as conn:
        cases_count = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        approved_cases = conn.execute(
            "SELECT COUNT(*) FROM cases WHERE approval_status = 'approved'"
        ).fetchone()[0]
        return {
            "cases": int(cases_count),
            "approved_training_examples": int(approved_cases),
        }


def get_management_report() -> dict[str, Any]:
    with get_db() as conn:
        totals = {
            "cases": int(conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]),
            "approved": int(conn.execute("SELECT COUNT(*) FROM cases WHERE approval_status = 'approved'").fetchone()[0]),
            "logged_only": int(conn.execute("SELECT COUNT(*) FROM cases WHERE approval_status = 'logged_only'").fetchone()[0]),
            "rejected": int(conn.execute("SELECT COUNT(*) FROM cases WHERE approval_status = 'rejected'").fetchone()[0]),
            "model_runs": int(conn.execute("SELECT COUNT(*) FROM model_runs").fetchone()[0]),
            "corrections": int(conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]),
        }
        approval_breakdown = [
            dict(row)
            for row in conn.execute(
                """
                SELECT approval_status AS label, COUNT(*) AS count
                FROM cases
                GROUP BY approval_status
                ORDER BY count DESC, label ASC
                """
            ).fetchall()
        ]
        category_breakdown = [
            dict(row)
            for row in conn.execute(
                """
                SELECT COALESCE(NULLIF(category, ''), 'uncategorized') AS label, COUNT(*) AS count
                FROM cases
                GROUP BY COALESCE(NULLIF(category, ''), 'uncategorized')
                ORDER BY count DESC, label ASC
                LIMIT 12
                """
            ).fetchall()
        ]
        model_run_breakdown = [
            dict(row)
            for row in conn.execute(
                """
                SELECT status AS label, COUNT(*) AS count
                FROM model_runs
                GROUP BY status
                ORDER BY count DESC, label ASC
                """
            ).fetchall()
        ]
        recent_cases = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, COALESCE(NULLIF(category, ''), 'uncategorized') AS category,
                       approval_status, technician_note_raw, corrected_translation,
                       model_name, date_created
                FROM cases
                ORDER BY date_created DESC, id DESC
                LIMIT 10
                """
            ).fetchall()
        ]
        recent_model_runs = [
            dict(row)
            for row in conn.execute(
                """
                SELECT model_name, status, duration_ms, created_at
                FROM model_runs
                ORDER BY created_at DESC, id DESC
                LIMIT 10
                """
            ).fetchall()
        ]
        quality_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT technician_name, category, clarification_category,
                       missing_fields_json, qualifier_answers_json, created_at
                FROM note_quality_events
                ORDER BY created_at DESC, id DESC
                LIMIT 500
                """
            ).fetchall()
        ]
        missing_counter: dict[str, int] = {}
        tech_counter: dict[str, int] = {}
        pack_counter: dict[str, int] = {}
        for row in quality_rows:
            tech = row.get("technician_name") or "Unassigned"
            tech_counter[tech] = tech_counter.get(tech, 0) + 1
            pack = row.get("clarification_category") or "uncategorized"
            pack_counter[pack] = pack_counter.get(pack, 0) + 1
            for field in loads(row.get("missing_fields_json"), []):
                label = str(field or "").strip() or "unknown"
                missing_counter[label] = missing_counter.get(label, 0) + 1
        common_missing_fields = [
            {"label": label, "count": count}
            for label, count in sorted(missing_counter.items(), key=lambda item: (-item[1], item[0]))[:12]
        ]
        misses_by_tech = [
            {"label": label, "count": count}
            for label, count in sorted(tech_counter.items(), key=lambda item: (-item[1], item[0]))[:12]
        ]
        clarifier_pack_breakdown = [
            {"label": label, "count": count}
            for label, count in sorted(pack_counter.items(), key=lambda item: (-item[1], item[0]))[:12]
        ]
        return {
            "totals": totals,
            "approval_breakdown": approval_breakdown,
            "category_breakdown": category_breakdown,
            "model_run_breakdown": model_run_breakdown,
            "common_missing_fields": common_missing_fields,
            "misses_by_tech": misses_by_tech,
            "clarifier_pack_breakdown": clarifier_pack_breakdown,
            "recent_cases": recent_cases,
            "recent_model_runs": recent_model_runs,
        }


def upsert_case_tags(conn: sqlite3.Connection, case_id: int, raw_tags: str | None) -> None:
    if not raw_tags:
        return
    tags = [tag.strip().lower() for tag in raw_tags.replace("\n", ",").split(",")]
    for tag in [tag for tag in tags if tag]:
        cursor = conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
        tag_id = cursor.lastrowid
        if not tag_id:
            tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (tag,)).fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO case_tags (case_id, tag_id) VALUES (?, ?)",
            (case_id, tag_id),
        )

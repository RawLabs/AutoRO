from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_dotenv()

PORTABLE_ROOT = Path(__file__).resolve().parents[1]
DRIVE_ROOT = PORTABLE_ROOT
DEFAULT_ESTIMATE_CONVERSION_ROOT = PORTABLE_ROOT / "estimate_conversion"
DEFAULT_REPORTS_ROOT = DRIVE_ROOT / "runtime" / "reports"


@dataclass(frozen=True)
class Settings:
    model_provider: str = os.getenv("MODEL_PROVIDER", "llamafile").strip().lower()
    model_name: str = os.getenv("AUTORO_MODEL", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf")
    ollama_url: str = os.getenv("AUTORO_OLLAMA_URL", "http://localhost:11434").rstrip("/")
    llamafile_url: str = os.getenv("LLAMAFILE_BASE_URL", "http://localhost:8080").rstrip("/")
    db_path: str = os.getenv("AUTORO_DB_PATH", "runtime/Database/autoro.db")
    db_backup_days: int = int(os.getenv("AUTORO_DB_BACKUP_DAYS", "14"))
    request_timeout: int = int(os.getenv("AUTORO_REQUEST_TIMEOUT", "60"))
    max_response_tokens: int = int(os.getenv("AUTORO_MAX_RESPONSE_TOKENS", "512"))
    estimate_conversion_root: str = os.getenv(
        "AUTORO_ESTIMATE_CONVERSION_ROOT",
        str(DEFAULT_ESTIMATE_CONVERSION_ROOT),
    )
    estimate_conversion_script: str = os.getenv(
        "AUTORO_ESTIMATE_CONVERSION_SCRIPT",
        str(DEFAULT_ESTIMATE_CONVERSION_ROOT / "workspace" / "estimates" / "decision_pipeline.py"),
    )
    estimate_conversion_output_dir: str = os.getenv(
        "AUTORO_ESTIMATE_OUTPUT_DIR",
        str(DEFAULT_ESTIMATE_CONVERSION_ROOT / "workspace" / "autoro_outbox"),
    )
    estimate_conversion_provider: str = os.getenv("AUTORO_ESTIMATE_PROVIDER", "llamafile").strip().lower()
    estimate_conversion_model: str = os.getenv(
        "AUTORO_ESTIMATE_MODEL",
        "Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
    )
    estimate_conversion_llamafile_url: str = os.getenv(
        "AUTORO_ESTIMATE_LLAMAFILE_URL",
        "http://localhost:8080",
    ).rstrip("/")
    reports_root: str = os.getenv("AUTORO_REPORTS_ROOT", str(DEFAULT_REPORTS_ROOT))
    management_code: str = os.getenv("AUTORO_MANAGEMENT_CODE", "2470")


settings = Settings()

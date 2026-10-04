from __future__ import annotations
import os
import time
from pathlib import Path
import logging
from app.config import PORTABLE_ROOT, settings

# Setup standard logging to match the app
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("autoro.cleanup")

def clean_directory(directory: Path, max_age_seconds: float, extension: str | None = None) -> int:
    """Deletes files in the given directory that are older than max_age_seconds."""
    if not directory.exists() or not directory.is_dir():
        return 0
    
    deleted_count = 0
    now = time.time()
    
    for file_path in directory.iterdir():
        if file_path.is_file():
            # Check extension if specified
            if extension and file_path.suffix.lower() != extension.lower():
                continue
            
            try:
                file_mtime = file_path.stat().st_mtime
                age = now - file_mtime
                if age > max_age_seconds:
                    file_path.unlink()
                    deleted_count += 1
                    logger.info(f"Deleted old file: {file_path}")
            except Exception as e:
                logger.error(f"Failed to delete {file_path}: {e}")
                
    return deleted_count

def run_auto_cleanup() -> None:
    logger.info("Starting automatic storage cleanup...")
    
    # 1. Clean logs (older than 14 days)
    logs_dir = PORTABLE_ROOT / "runtime" / "logs"
    logs_deleted = clean_directory(logs_dir, 14 * 24 * 60 * 60, extension=".log")
    
    # 2. Clean temporary PDF uploads (older than 1 day)
    uploads_dir = PORTABLE_ROOT / "estimate_conversion" / "workspace" / "uploads"
    # This directory contains only temporary uploads; include interrupted .part files.
    uploads_deleted = clean_directory(uploads_dir, 1 * 24 * 60 * 60)
    
    # 3. Clean import records (older than 30 days)
    imports_dir = PORTABLE_ROOT / "estimate_conversion" / "workspace" / "import_records"
    imports_deleted = clean_directory(imports_dir, 30 * 24 * 60 * 60, extension=".json")

    # Keep enough transactionally consistent database snapshots for recovery.
    backups_dir = PORTABLE_ROOT / "runtime" / "Database" / "backups"
    backups_deleted = clean_directory(
        backups_dir, settings.db_backup_days * 24 * 60 * 60, extension=".db"
    )

    # Normal in-shop requests delete immediately; this catches interrupted runs.
    inshop_uploads_dir = PORTABLE_ROOT / "app" / "static" / "inshop_temp"
    inshop_deleted = clean_directory(inshop_uploads_dir, 1 * 24 * 60 * 60)
    
    logger.info(
        f"Cleanup finished. Deleted {logs_deleted} logs, "
        f"{uploads_deleted} conversion uploads, {inshop_deleted} in-shop uploads, "
        f"{imports_deleted} import records, and {backups_deleted} database backups."
    )

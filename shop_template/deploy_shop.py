#!/usr/bin/env python3
"""
AutoRO Shop Deployment and Configuration Script
This script helps copy the AutoRO application framework to a new drive/target directory,
substituting the active shop's runtime database/data with the clean "AutoRO Shop Demo" template.
It also allows rapid configuration of the new shop's environment parameters.
"""

import sys
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

# Paths relative to the drive root
DRIVE_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = DRIVE_ROOT / "shop_template" / "AutoRO_shop_demo"

# Immutable application paths copied verbatim. Runtime-bearing trees are handled
# separately below with explicit allowlists.
CORE_PATHS = [
    "app",
    "Llamafile",
    "Models",
    "Tools",
    "dev_tools",
    "docs",
    "requirements.txt",
    "start_autoro_linux.sh",
    "Double Click to Start AutoRO Windows Useres .bat",
    "Launch AutoRO (PowerShell).ps1",
    "install_linux_dependencies.sh",
    "README.md",
    "Modelfile",
    "RELEASE_MANIFEST.json",
]

APP_EXCLUDES = {
    "__pycache__",
    "inshop_temp",
}

ESTIMATE_IMMUTABLE_PATHS = [
    "images",
    "scripts",
    "workspace/estimates",
]

RUNTIME_DIRS = [
    "runtime/Database",
    "runtime/logs",
    "runtime/reports",
    "estimate_conversion/workspace/uploads",
    "estimate_conversion/workspace/autoro_outbox",
    "estimate_conversion/workspace/import_records",
    "app/static/inshop_temp",
]

BUSINESS_TABLES = {
    "vehicles",
    "cases",
    "note_quality_events",
    "advisor_translation_queue",
    "model_runs",
    "corrections",
    "tags",
    "case_tags",
    "inshop_estimates",
    "inshop_jobs",
    "inshop_stories",
}


def copy_ignore(_directory: str, names: list[str]) -> set[str]:
    """Exclude generated/runtime content from otherwise immutable trees."""
    ignored = set()
    for name in names:
        if name in APP_EXCLUDES or name == ".env" or name.endswith((".pyc", ".log")):
            ignored.add(name)
    return ignored


def require_empty_target(target_path: Path) -> None:
    """Never merge a clean deployment into an existing shop or partial copy."""
    if not target_path.exists():
        return
    entries = list(target_path.iterdir())
    if entries:
        sample = ", ".join(entry.name for entry in entries[:5])
        raise ValueError(
            f"Target directory must be empty; found {len(entries)} item(s): {sample}"
        )


def validate_clean_template(template_dir: Path) -> Path:
    """Prove the deployment template contains reference data but no shop records."""
    runtime = template_dir / "runtime"
    database_path = runtime / "Database" / "autoro.db"
    if not database_path.is_file():
        raise ValueError(f"Clean template database is missing: {database_path}")

    forbidden_files: list[Path] = []
    for relative in ("logs", "reports"):
        folder = runtime / relative
        if folder.exists():
            forbidden_files.extend(path for path in folder.rglob("*") if path.is_file())
    if forbidden_files:
        names = ", ".join(str(path.relative_to(template_dir)) for path in forbidden_files[:5])
        raise ValueError(f"Clean template contains runtime output: {names}")

    with closing(sqlite3.connect(database_path)) as connection:
        existing_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        for table in sorted(BUSINESS_TABLES & existing_tables):
            count = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if count:
                raise ValueError(
                    f"Clean template database is contaminated: table {table} has {count} row(s)"
                )
    return database_path


def copy_immutable_application(source_root: Path, target_path: Path) -> None:
    for path_name in CORE_PATHS:
        src = source_root / path_name
        dest = target_path / path_name
        if not src.exists():
            print(f"Warning: Source path {src} does not exist. Skipping.")
            continue
        print(f"Copying {path_name}...")
        if src.is_dir():
            shutil.copytree(src, dest, ignore=copy_ignore, dirs_exist_ok=False)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    estimate_root = source_root / "estimate_conversion"
    for relative in ESTIMATE_IMMUTABLE_PATHS:
        src = estimate_root / relative
        dest = target_path / "estimate_conversion" / relative
        if not src.exists():
            raise ValueError(f"Required estimate application path is missing: {src}")
        print(f"Copying estimate_conversion/{relative}...")
        shutil.copytree(src, dest, ignore=copy_ignore, dirs_exist_ok=False)


def create_clean_runtime(template_dir: Path, target_path: Path) -> None:
    database_path = validate_clean_template(template_dir)
    runtime = template_dir / "runtime"
    shutil.copytree(runtime / "data", target_path / "runtime" / "data")
    destination_db = target_path / "runtime" / "Database" / "autoro.db"
    destination_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(database_path, destination_db)
    for relative in RUNTIME_DIRS:
        (target_path / relative).mkdir(parents=True, exist_ok=True)

def get_input(prompt: str, default: str) -> str:
    try:
        val = input(f"{prompt} [{default}]: ").strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        print("\nDeployment cancelled.")
        sys.exit(1)

def main():
    print("=" * 60)
    print("          AutoRO New Shop Deployment Wizard")
    print("=" * 60)
    print(f"Detecting source drive root: {DRIVE_ROOT}")
    print(f"Detecting template directory: {TEMPLATE_DIR}\n")

    if not TEMPLATE_DIR.exists():
        print(f"Error: Template directory not found at {TEMPLATE_DIR}")
        print("Please ensure you are running this from the correct drive layout.")
        sys.exit(1)

    # 1. Ask for target deployment directory
    print("Enter the target directory for the new shop deployment.")
    print("For example, this could be the mount point of a new USB drive (e.g. /media/user/NEW_DRIVE or D:\\)")
    target_dir_raw = get_input("Target directory", "")
    if not target_dir_raw:
        print("Error: Target directory cannot be empty.")
        sys.exit(1)
        
    target_path = Path(target_dir_raw).resolve()
    print(f"Target path resolved to: {target_path}\n")

    if target_path == DRIVE_ROOT:
        print("Error: Target path cannot be the same as the active source drive root.")
        sys.exit(1)

    try:
        require_empty_target(target_path)
        validate_clean_template(TEMPLATE_DIR)
    except ValueError as exc:
        print(f"Deployment preflight failed: {exc}")
        sys.exit(1)

    # 2. Ask for new shop configurations
    print("--- Configure Shop Environment ---")
    shop_name = get_input("Shop Name/Identifier", "AutoRO Shop Demo")
    management_code = get_input("Operations Management PIN (4 digits)", "2470")
    server_port = get_input("AutoRO Server Port", "8000")
    model_port = get_input("Qwen Model Port (handles Translation & Estimate)", "8080")
    model_provider = get_input("Model Provider (llamafile/ollama)", "llamafile")

    print("\n--- Summary of New Deployment ---")
    print(f"Target: {target_path}")
    print(f"Shop Name: {shop_name}")
    print(f"Server Port: {server_port}")
    print(f"PIN Code: {management_code}")
    print(f"LLM Port: {model_port}")
    print("-" * 30)
    
    confirm = get_input("Proceed with deployment? (yes/no)", "no").lower()
    if confirm not in ("y", "yes"):
        print("Deployment aborted.")
        sys.exit(0)

    # 3. Create target directory
    print(f"\nCreating directory: {target_path}...")
    target_path.mkdir(parents=True, exist_ok=True)

    # 4. Copy immutable application paths only. This intentionally does not
    # copy the source drive's estimate workspace, reports, uploads, or logs.
    copy_immutable_application(DRIVE_ROOT, target_path)

    # 5. Copy clean runtime template (database, rule maps)
    print("Copying clean template runtime folder (database, rules, canned jobs)...")
    create_clean_runtime(TEMPLATE_DIR, target_path)

    # 6. Generate custom .env file
    print("Generating custom .env config...")
    env_content = f"""# AutoRO Shop Environment Configuration for {shop_name}
# Generated automatically by deploy_shop.py

MODEL_PROVIDER={model_provider}
AUTORO_MODEL=Qwen3-4B-Instruct-2507-Q4_K_M.gguf
LLAMAFILE_BASE_URL=http://localhost:{model_port}

AUTORO_ESTIMATE_PROVIDER={model_provider}
AUTORO_ESTIMATE_MODEL=Qwen3-4B-Instruct-2507-Q4_K_M.gguf
AUTORO_ESTIMATE_LLAMAFILE_URL=http://localhost:{model_port}

AUTORO_DB_PATH=runtime/Database/autoro.db
AUTORO_REPORTS_ROOT=runtime/reports
AUTORO_ESTIMATE_CONVERSION_ROOT=estimate_conversion
AUTORO_ESTIMATE_OUTPUT_DIR=estimate_conversion/workspace/autoro_outbox

AUTORO_MANAGEMENT_CODE={management_code}
AUTORO_REQUEST_TIMEOUT=60
AUTORO_MAX_RESPONSE_TOKENS=512
"""

    with open(target_path / ".env", "w", encoding="utf-8") as f:
        f.write(env_content)

    # 7. Customize Windows startup script for the port
    # Edit the port parameter in the copied batch script
    bat_file = target_path / "Double Click to Start AutoRO Windows Useres .bat"
    if bat_file.exists():
        content = bat_file.read_text(encoding="utf-8", errors="ignore")
        # Replace default port 8000 and url port
        content = content.replace("set \"URL=http://127.0.0.1:8000\"", f"set \"URL=http://127.0.0.1:{server_port}\"")
        content = content.replace("s.connect_ex(('127.0.0.1',8000))", f"s.connect_ex(('127.0.0.1',{server_port}))")
        content = content.replace("http://127.0.0.1:8080/v1/models", f"http://127.0.0.1:{model_port}/v1/models")
        content = content.replace("--port 8000", f"--port {server_port}")
        content = content.replace("port 8000", f"port {server_port}")
        bat_file.write_text(content, encoding="utf-8")

    # Customize PowerShell script
    ps_file = target_path / "Launch AutoRO (PowerShell).ps1"
    if ps_file.exists():
        content = ps_file.read_text(encoding="utf-8", errors="ignore")
        content = content.replace("$Port = 8000", f"$Port = {server_port}")
        content = content.replace("$ModelPort = 8080", f"$ModelPort = {model_port}")
        ps_file.write_text(content, encoding="utf-8")

    # Customize Linux script default ports if necessary
    sh_file = target_path / "start_autoro_linux.sh"
    if sh_file.exists():
        content = sh_file.read_text(encoding="utf-8")
        content = content.replace("PORT=\"${AUTORO_PORT:-8000}\"", f"PORT=\"${{AUTORO_PORT:-{server_port}}}\"")
        content = content.replace("http://127.0.0.1:8080/v1/models", f"http://127.0.0.1:{model_port}/v1/models")
        sh_file.write_text(content, encoding="utf-8")

    model_bat = target_path / "Llamafile" / "start_model.bat"
    if model_bat.exists():
        content = model_bat.read_text(encoding="utf-8", errors="ignore")
        content = content.replace('set "PORT=8080"', f'set "PORT={model_port}"')
        model_bat.write_text(content, encoding="utf-8")

    model_sh = target_path / "Llamafile" / "start_model_linux.sh"
    if model_sh.exists():
        content = model_sh.read_text(encoding="utf-8")
        content = content.replace('PORT="8080"', f'PORT="{model_port}"')
        model_sh.write_text(content, encoding="utf-8")

    print("\n" + "=" * 60)
    print("                    Deployment Complete!")
    print("=" * 60)
    print(f"Shop '{shop_name}' is fully deployed to:")
    print(f"  {target_path}")
    print("\nHow to start:")
    print("  Windows: Double click the '.bat' launcher at the new drive root.")
    print("  Linux:   Run './start_autoro_linux.sh' at the new drive root.")
    print("=" * 60)

if __name__ == "__main__":
    main()

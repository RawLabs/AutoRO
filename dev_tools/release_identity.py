#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "RELEASE_MANIFEST.json"

DEFAULT_INCLUDE_GLOBS = [
    "app/*.py",
    "app/**/*.py",
    "app/schema.sql",
    "app/static/**/*.js",
    "app/static/**/*.css",
    "app/static/img/*",
    "app/templates/**/*.html",
    "dev_tools/*.py",
    "dev_tools/**/*.py",
    "docs/*.md",
    "estimate_conversion/images/*",
    "estimate_conversion/scripts/**/*.py",
    "estimate_conversion/workspace/estimates/**/*.py",
    "html_presentation/autoro_presentation.html",
    "html_presentation/autoro_logo.png",
    "Llamafile/*.bat",
    "Llamafile/*.ps1",
    "Llamafile/*.sh",
    "shop_template/*.py",
    "shop_template/*.md",
    "shop_template/.env.template",
    "Double Click to Start AutoRO Windows Useres .bat",
    "Launch AutoRO (PowerShell).ps1",
    "Modelfile",
    "README.md",
    "requirements.txt",
    "install_linux_dependencies.sh",
    "start_autoro_linux.sh",
]

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "logs",
    "uploads",
    "import_records",
    "autoro_outbox",
    ".mypy_cache",
    ".pytest_cache",
    "Tools",
    "Database",
    ".Trash-1000",
}

KEY_FILES = [
    "app/main.py",
    "app/config.py",
    "app/routes.py",
    "app/database.py",
    "app/schemas.py",
    "app/estimate_conversion.py",
    "app/note_quality.py",
    "app/bg_rules.py",
    "app/static/js/estimates.js",
    "app/static/js/translator.js",
    "app/static/js/advisor_queue.js",
    "app/schema.sql",
    "Double Click to Start AutoRO Windows Useres .bat",
    "Launch AutoRO (PowerShell).ps1",
    "Llamafile/start_model.bat",
    "Llamafile/start_model_linux.sh",
    "shop_template/deploy_shop.py",
    "shop_template/.env.template",
    "README.md",
    "requirements.txt",
    "start_autoro_linux.sh",
]


def sanitize_release_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", value.strip())
    return cleaned or "unknown-release"


def unique_archive_path(base_path: Path) -> Path:
    if not base_path.exists():
        return base_path

    stem = base_path.stem
    suffix = base_path.suffix or ".json"
    parent = base_path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}__{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def archive_existing_manifest_if_present(manifest_path: Path) -> dict | None:
    if not manifest_path.exists():
        return None

    prior = json.loads(manifest_path.read_text(encoding="utf-8"))
    prior_release_id = sanitize_release_id(str(prior.get("release_id") or "unknown-release"))

    archive_dir = ROOT / "release_history"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = unique_archive_path(archive_dir / f"{prior_release_id}.json")

    shutil.copy2(manifest_path, archive_path)
    return {
        "prior_release_id": prior.get("release_id"),
        "archived_to": str(archive_path),
    }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def should_include(rel_path: str, include_globs: list[str]) -> bool:
    rel_path = rel_path.replace("\\", "/")
    return any(fnmatch.fnmatch(rel_path, pat) for pat in include_globs)


def snapshot(include_globs: list[str], exclude_dirs: set[str]) -> dict:
    entries: list[dict] = []
    tree_hasher = hashlib.sha256()
    newest_mtime = 0.0

    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        base = Path(dirpath)

        for filename in filenames:
            path = base / filename
            rel = path.relative_to(ROOT).as_posix()
            if not should_include(rel, include_globs):
                continue

            stat = path.stat()
            file_hash = sha256_file(path)

            entries.append(
                {
                    "path": rel,
                    "sha256": file_hash,
                    "size_bytes": stat.st_size,
                    "mtime_utc": dt.datetime.fromtimestamp(
                        stat.st_mtime, tz=dt.timezone.utc
                    ).isoformat(),
                }
            )

            newest_mtime = max(newest_mtime, stat.st_mtime)
            tree_hasher.update(rel.encode("utf-8"))
            tree_hasher.update(b"\0")
            tree_hasher.update(file_hash.encode("ascii"))
            tree_hasher.update(b"\n")

    entries.sort(key=lambda x: x["path"])

    key_file_hashes = {}
    by_path = {entry["path"]: entry["sha256"] for entry in entries}
    for key_path in KEY_FILES:
        if key_path in by_path:
            key_file_hashes[key_path] = by_path[key_path]

    return {
        "autoro_root": str(ROOT),
        "tree_fingerprint_sha256": tree_hasher.hexdigest(),
        "file_count": len(entries),
        "newest_file_utc": (
            dt.datetime.fromtimestamp(newest_mtime, tz=dt.timezone.utc).isoformat()
            if newest_mtime
            else None
        ),
        "key_file_hashes": key_file_hashes,
        "files": entries,
    }


def write_manifest(manifest_path: Path, release_id_override: str | None = None) -> dict:
    include_globs = list(DEFAULT_INCLUDE_GLOBS)
    exclude_dirs = set(DEFAULT_EXCLUDE_DIRS)
    snap = snapshot(include_globs, exclude_dirs)
    archive_info = archive_existing_manifest_if_present(manifest_path)

    now = dt.datetime.now(tz=dt.timezone.utc)
    release_id = (
        sanitize_release_id(release_id_override)
        if release_id_override
        else f"{now.strftime('%Y%m%dT%H%M%SZ')}-{snap['tree_fingerprint_sha256'][:12]}"
    )

    manifest = {
        "manifest_version": "1.0",
        "generated_at_utc": now.isoformat(),
        "release_id": release_id,
        "archived_previous_manifest": archive_info,
        "identity_scope": {
            "include_globs": include_globs,
            "exclude_dirs": sorted(exclude_dirs),
        },
        **snap,
    }

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify_manifest(manifest_path: Path) -> tuple[bool, dict]:
    if not manifest_path.exists():
        return False, {"error": f"Manifest not found: {manifest_path}"}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scope = manifest.get("identity_scope", {})
    include_globs = scope.get("include_globs", list(DEFAULT_INCLUDE_GLOBS))
    exclude_dirs = set(scope.get("exclude_dirs", sorted(DEFAULT_EXCLUDE_DIRS)))

    current = snapshot(include_globs, exclude_dirs)

    expected_map = {f["path"]: f["sha256"] for f in manifest.get("files", [])}
    current_map = {f["path"]: f["sha256"] for f in current.get("files", [])}

    expected_paths = set(expected_map)
    current_paths = set(current_map)

    missing_files = sorted(expected_paths - current_paths)
    extra_files = sorted(current_paths - expected_paths)
    changed_files = sorted(
        p for p in (expected_paths & current_paths) if expected_map[p] != current_map[p]
    )

    tree_match = manifest.get("tree_fingerprint_sha256") == current.get("tree_fingerprint_sha256")
    file_count_match = manifest.get("file_count") == current.get("file_count")

    ok = tree_match and file_count_match and not missing_files and not extra_files and not changed_files

    result = {
        "manifest_path": str(manifest_path),
        "release_id": manifest.get("release_id"),
        "tree_match": tree_match,
        "file_count_match": file_count_match,
        "expected_tree": manifest.get("tree_fingerprint_sha256"),
        "current_tree": current.get("tree_fingerprint_sha256"),
        "expected_file_count": manifest.get("file_count"),
        "current_file_count": current.get("file_count"),
        "missing_files_count": len(missing_files),
        "extra_files_count": len(extra_files),
        "changed_files_count": len(changed_files),
        "missing_files": missing_files,
        "extra_files": extra_files,
        "changed_files": changed_files,
    }
    return ok, result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and verify deterministic release identity for AutoRO-Portable."
    )
    parser.add_argument("--manifest-path", default=str(DEFAULT_MANIFEST), help="Path to manifest JSON")
    parser.add_argument("--write-manifest", action="store_true", help="Write RELEASE_MANIFEST.json")
    parser.add_argument(
        "--release-id",
        help="Human-readable release ID, for example 1.3.0-beta.1",
    )
    parser.add_argument("--verify", action="store_true", help="Verify current tree against manifest")
    args = parser.parse_args()

    manifest_path = Path(args.manifest_path).resolve()

    if args.write_manifest:
        manifest = write_manifest(manifest_path, release_id_override=args.release_id)
        print(json.dumps({
            "status": "manifest_written",
            "manifest_path": str(manifest_path),
            "release_id": manifest["release_id"],
            "tree_fingerprint_sha256": manifest["tree_fingerprint_sha256"],
            "file_count": manifest["file_count"],
            "archived_previous_manifest": manifest.get("archived_previous_manifest"),
        }, indent=2))

    if args.verify:
        ok, result = verify_manifest(manifest_path)
        print(json.dumps({
            "status": "ok" if ok else "mismatch",
            **result,
        }, indent=2))
        return 0 if ok else 1

    if not args.write_manifest and not args.verify:
        snap = snapshot(list(DEFAULT_INCLUDE_GLOBS), set(DEFAULT_EXCLUDE_DIRS))
        print(json.dumps({
            "status": "snapshot",
            "autoro_root": snap["autoro_root"],
            "tree_fingerprint_sha256": snap["tree_fingerprint_sha256"],
            "file_count": snap["file_count"],
            "newest_file_utc": snap["newest_file_utc"],
        }, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())

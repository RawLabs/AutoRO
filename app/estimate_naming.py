from __future__ import annotations

import re
from pathlib import Path
from typing import Any


DOCUMENT_PREFIXES = {
    "preestimate": "OUT_OF_SHOP_ESTIMATE",
    "out_of_shop": "OUT_OF_SHOP_ESTIMATE",
    "quote": "IN_SHOP_ESTIMATE",
    "inshop": "IN_SHOP_ESTIMATE",
    "proposal": "CUSTOM_BUILD",
    "custom_build": "CUSTOM_BUILD",
}


def _filename_part(value: Any) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip())
    return cleaned.strip("_").upper()


def _source_identity(source_filename: str) -> str:
    stem = Path(source_filename or "").stem
    # AutoRO upload storage adds a numeric nonce; it is not customer-facing.
    stem = re.sub(r"^\d{10,20}_", "", stem)
    identity = _filename_part(stem)
    if identity in {"", "PDF", "ESTIMATE", "AUTORO_ESTIMATE"}:
        return ""
    if re.fullmatch(r"[0-9A-F]{32}", identity):
        return ""
    return identity


def _customer_identity(parsed: dict[str, Any]) -> str:
    customer = parsed.get("customer") or {}
    vehicle = parsed.get("vehicle") or {}
    name = str(customer.get("name") or "CUSTOMER").strip()
    if "," in name:
        last, first = (part.strip() for part in name.split(",", 1))
        name = " ".join(part for part in (first, last) if part)

    year = vehicle.get("year") or parsed.get("year") or ""
    make = vehicle.get("make") or parsed.get("make") or ""
    model = vehicle.get("model") or parsed.get("model") or "VEHICLE"
    estimate_number = (
        parsed.get("estimate_number")
        or parsed.get("ro_number")
        or parsed.get("order_number")
        or ""
    )
    pieces = [_filename_part(name), _filename_part(year), _filename_part(make), _filename_part(model)]
    if estimate_number:
        pieces.append(f"RO{_filename_part(estimate_number)}")
    return "_".join(piece for piece in pieces if piece)


def estimate_output_stem(parsed: dict[str, Any], document_type: str) -> str:
    """Return the stable customer-facing filename stem for an estimate PDF."""
    prefix = DOCUMENT_PREFIXES.get(document_type, "AUTORO_ESTIMATE")
    identity = _source_identity(str(parsed.get("source_filename") or parsed.get("asr_filename") or ""))
    if not identity:
        identity = _customer_identity(parsed)
    # Keep names readable and below common filesystem/browser limits.
    return f"{prefix}_{identity}"[:180].rstrip("_")

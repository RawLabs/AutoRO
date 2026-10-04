from __future__ import annotations

import re
from typing import Any


SIDE_PATTERNS = [
    r"\blf\b",
    r"\brf\b",
    r"\blr\b",
    r"\brr\b",
    r"\bleft\b",
    r"\bright\b",
    r"\blft\b",
    r"\brt\b",
    r"\bl\b",
    r"\br\b",
    r"\bdriver'?s?\b",
    r"\bpassenger'?s?\b",
    r"\bboth\b",
]


DETAIL_RULES: list[dict[str, Any]] = [
    {
        "pack": "cv_boot",
        "label": "CV boot / axle",
        "triggers": [r"\bc/?v\s+boot\b", r"\bcv\s+boot\b", r"\baxle\s+boot\b", r"\bboot\b.*\bgrease\b"],
        "required": [
            {"key": "side", "label": "side", "patterns": SIDE_PATTERNS},
            {"key": "position", "label": "inner/outer", "patterns": [r"\binner\b", r"\bouter\b", r"\binboard\b", r"\boutboard\b"]},
        ],
        "quick_options": [
            {"label": "LF outer", "append_text": "LF outer"},
            {"label": "RF outer", "append_text": "RF outer"},
            {"label": "LF inner", "append_text": "LF inner"},
            {"label": "RF inner", "append_text": "RF inner"},
        ],
    },
    {
        "pack": "tie_rod",
        "label": "Tie rod",
        "triggers": [r"\bti[er]e?\s*rod\b"],
        "required": [
            {"key": "side", "label": "side", "patterns": SIDE_PATTERNS},
            {"key": "position", "label": "inner/outer", "patterns": [r"\binner\b", r"\bouter\b", r"\binboard\b", r"\boutboard\b"]},
        ],
        "quick_options": [
            {"label": "LF outer", "append_text": "LF outer"},
            {"label": "RF outer", "append_text": "RF outer"},
            {"label": "LF inner", "append_text": "LF inner"},
            {"label": "RF inner", "append_text": "RF inner"},
        ],
    },
    {
        "pack": "ac_line",
        "label": "A/C line",
        "triggers": [r"\ba/?c\s+(line|hose|pipe)\b", r"\bac\s+(line|hose|pipe)\b", r"\brefrigerant\s+(line|hose|pipe)\b"],
        "required": [
            {
                "key": "location",
                "label": "high/low or location",
                "patterns": [
                    r"\bhigh\s*side\b",
                    r"\blow\s*side\b",
                    r"\bevap(orator)?\b",
                    r"\bcondenser\b",
                    r"\bcompressor\b",
                    r"\bdrier\b",
                    r"\bdryer\b",
                ],
            },
        ],
        "quick_options": [
            {"label": "High side", "append_text": "high side"},
            {"label": "Low side", "append_text": "low side"},
            {"label": "Condenser side", "append_text": "condenser side"},
            {"label": "Evap side", "append_text": "evaporator side"},
        ],
    },
    {
        "pack": "side_required",
        "label": "Side-specific part",
        "triggers": [r"\b(ball\s*joint|control\s*arm|wheel\s*bearing|sway\s*(bar\s*)?(link|bushing)|strut|shock)\b"],
        "required": [
            {"key": "side", "label": "side", "patterns": SIDE_PATTERNS + [r"\bfront\b", r"\brear\b"]},
        ],
        "quick_options": [
            {"label": "LF", "append_text": "LF"},
            {"label": "RF", "append_text": "RF"},
            {"label": "LR", "append_text": "LR"},
            {"label": "RR", "append_text": "RR"},
            {"label": "Both", "append_text": "both sides"},
        ],
    },
    {
        "pack": "tire_repair",
        "label": "Tire repair",
        "triggers": [r"\b(tire|wheel)s?\b.*\b(fix|repair|patch|plug)[a-z]*\b", r"\b(fix|repair|patch|plug)[a-z]*\b.*\b(tire|wheel)s?\b"],
        "required": [
            {"key": "side", "label": "location (LF/RF/LR/RR)", "patterns": SIDE_PATTERNS + [r"\bfront\b", r"\brear\b"]},
            {"key": "damage", "label": "damage type", "patterns": [r"\bnail\b", r"\bscrew\b", r"\bpuncture\b", r"\bsplit\b", r"\bhole\b"]},
        ],
        "quick_options": [
            {"label": "LF", "append_text": "LF"},
            {"label": "RF", "append_text": "RF"},
            {"label": "LR", "append_text": "LR"},
            {"label": "RR", "append_text": "RR"},
            {"label": "Nail", "append_text": "nail"},
            {"label": "Screw", "append_text": "screw"},
            {"label": "Puncture", "append_text": "puncture"},
            {"label": "Split", "append_text": "split"},
        ],
    },
]


def analyze_note_quality(payload: dict[str, Any]) -> dict[str, Any]:
    note = str(payload.get("technician_note") or "")
    category = str(payload.get("category") or "")
    answers = payload.get("qualifier_answers") if isinstance(payload.get("qualifier_answers"), dict) else {}
    rule = detect_rule(note, category)
    if not rule:
        return empty_result(answers)

    missing_fields: list[str] = []
    fields: list[dict[str, Any]] = []
    for field in rule["required"]:
        key = field["key"]
        answered = str(answers.get(key) or "").strip()
        detected = bool(answered) or has_any_pattern(note, field.get("patterns", []))
        if not detected:
            missing_fields.append(key)
        fields.append(
            {
                "key": key,
                "label": field["label"],
                "options": [],
                "detected": detected,
                "selected": answered,
                "missing": not detected,
            }
        )

    if not missing_fields:
        return {
            "pack": rule["pack"],
            "label": rule["label"],
            "fields": fields,
            "missing_fields": [],
            "missing_labels": [],
            "quick_options": [],
            "qualifier_answers": answers,
            "has_guidance": False,
        }

    missing_labels = [field["label"] for field in rule["required"] if field["key"] in missing_fields]
    return {
        "pack": rule["pack"],
        "label": rule["label"],
        "fields": fields,
        "missing_fields": missing_fields,
        "missing_labels": missing_labels,
        "quick_options": rule.get("quick_options", []),
        "message": f"Confirm {' and '.join(missing_labels)} before translating, or translate anyway if unknown.",
        "qualifier_answers": answers,
        "has_guidance": True,
    }


def empty_result(answers: dict[str, Any]) -> dict[str, Any]:
    return {
        "pack": "",
        "label": "",
        "fields": [],
        "missing_fields": [],
        "missing_labels": [],
        "quick_options": [],
        "qualifier_answers": answers,
        "has_guidance": False,
    }


def detect_rule(note: str, category: str) -> dict[str, Any] | None:
    text = f"{category} {note}".lower()
    for rule in DETAIL_RULES:
        if has_any_pattern(text, rule["triggers"]):
            return rule
    return None


def has_any_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)

from __future__ import annotations

import re
from typing import Any

# Patterns matching various conditions
SOUND_TYPES = [
    r"\bsqueak\b",
    r"\bgrind\b",
    r"\bclunk\b",
    r"\brattle\b",
    r"\bclick\b",
    r"\bhum\b",
    r"\bwhine\b",
    r"\bpop\b",
    r"\bthump\b",
    r"\bchirp\b",
    r"\bscreech\b",
]

CONDITIONS_PATTERNS = [
    r"\b(when\s+)?brak(e|ing)\b",
    r"\b(when\s+)?turn(ing)?\b",
    r"\b(when\s+)?accelerat(e|ing)\b",
    r"\bover\s+bumps\b",
    r"\b(at\s+)?highway\s*speed\b",
    r"\b(on\s+)?cold\s*start\b",
    r"\bidl(e|ing)\b",
]

FEEL_LOCATIONS = [
    r"\bsteering\s*wheel\b",
    r"\bseat\b",
    r"\b(brake\s+)?pedal\b",
    r"\bfloor\b",
]

FLUID_COLORS = [
    r"\boil\b",
    r"\bcoolant\b",
    r"\bwater\b",
    r"\bred\b",
    r"\bgreen\b",
    r"\borange\b",
    r"\bblue\b",
    r"\byellow\b",
    r"\bbrown\b",
    r"\bamber\b",
    r"\bclear\b",
]

CEL_STATUS_PATTERNS = [
    r"\bflashing\b",
    r"\bsolid\b",
    r"\bon\b",
    r"\boff\b",
]

INTAKE_RULES: list[dict[str, Any]] = [
    {
        "pack": "noise",
        "label": "Noise / Sound concern",
        "triggers": [
            r"\bnoise\b",
            r"\bsqueak\b",
            r"\brattle\b",
            r"\bclunk\b",
            r"\bgrind\b",
            r"\bclick\b",
            r"\bpop\b",
            r"\bthump\b",
            r"\bhum\b",
            r"\bchirp\b",
            r"\bwhine\b",
            r"\bscreech\b",
            r"\bsound\b",
        ],
        "required": [
            {
                "key": "sound_type",
                "label": "type of noise",
                "patterns": SOUND_TYPES,
            },
            {
                "key": "conditions",
                "label": "when it occurs",
                "patterns": CONDITIONS_PATTERNS,
            },
        ],
        "quick_options": [
            {"label": "Squeak when braking", "append_text": "squeaking when braking"},
            {"label": "Clunk over bumps", "append_text": "clunking over bumps"},
            {"label": "Grind when turning", "append_text": "grinding when turning"},
            {"label": "Rattle at highway speeds", "append_text": "rattle at highway speeds"},
            {"label": "Clicking when turning", "append_text": "clicking when turning"},
            {"label": "Whining on acceleration", "append_text": "whining on acceleration"},
        ],
    },
    {
        "pack": "vibration",
        "label": "Vibration / Shake concern",
        "triggers": [
            r"\bvibrat(e|ion)\b",
            r"\bshake\b",
            r"\bshudder\b",
            r"\bwobble\b",
            r"\bshimmy\b",
        ],
        "required": [
            {
                "key": "location",
                "label": "where felt",
                "patterns": FEEL_LOCATIONS,
            },
            {
                "key": "conditions",
                "label": "when it occurs",
                "patterns": CONDITIONS_PATTERNS,
            },
        ],
        "quick_options": [
            {"label": "Steering wheel shake at highway speeds", "append_text": "felt in steering wheel at highway speeds"},
            {"label": "Brake pedal pulsation", "append_text": "felt in brake pedal when braking"},
            {"label": "Vibration at idle", "append_text": "felt at idle"},
            {"label": "Shudder under acceleration", "append_text": "felt under acceleration"},
        ],
    },
    {
        "pack": "leak",
        "label": "Fluid leak concern",
        "triggers": [
            r"\bleak\b",
            r"\bleaking\b",
            r"\bdrip\b",
            r"\bdripping\b",
            r"\bfluid\b",
            r"\bpuddle\b",
        ],
        "required": [
            {
                "key": "fluid_color",
                "label": "fluid type or color",
                "patterns": FLUID_COLORS,
            },
        ],
        "quick_options": [
            {"label": "Oil leak (brown/black)", "append_text": "oil leak"},
            {"label": "Coolant leak (green/orange)", "append_text": "coolant leak"},
            {"label": "Red transmission fluid", "append_text": "red fluid leak"},
            {"label": "Clear water drip", "append_text": "clear water drip"},
        ],
    },
    {
        "pack": "driveability",
        "label": "Engine run / Drivability concern",
        "triggers": [
            r"\b(runs?\s+)?rough\b",
            r"\bmisfir(e|ing)\b",
            r"\bsputter\b",
            r"\bstall(s|ing)?\b",
            r"\bdie(s|ing)?\b",
            r"\bno\s*start\b",
            r"\bwon't\s*start\b",
            r"\bcrank\b",
            r"\bhesitat(es|ion)\b",
            r"\bcel\b",
            r"\bcheck\s*engine\b",
        ],
        "required": [
            {
                "key": "conditions",
                "label": "when it occurs",
                "patterns": CONDITIONS_PATTERNS,
            },
            {
                "key": "cel_status",
                "label": "Check Engine Light status",
                "patterns": CEL_STATUS_PATTERNS,
            },
        ],
        "quick_options": [
            {"label": "CEL is solid", "append_text": "CEL is solid"},
            {"label": "CEL is flashing", "append_text": "CEL is flashing"},
            {"label": "Hesitates when accelerating", "append_text": "hesitates when accelerating"},
            {"label": "Rough idle at cold start", "append_text": "rough idle on cold start"},
            {"label": "Crank no start", "append_text": "engine cranks but will not start"},
        ],
    },
    {
        "pack": "hvac",
        "label": "A/C or Heating concern",
        "triggers": [
            r"\ba/?c\b",
            r"\bac\b",
            r"\bheater\b",
            r"\bheating\b",
            r"\bblows\s+warm\b",
            r"\bblows\s+hot\b",
            r"\bno\s+air\b",
            r"\bblower\b",
        ],
        "required": [
            {
                "key": "symptom",
                "label": "specific symptom",
                "patterns": [
                    r"\bwarm\b",
                    r"\bcold\b",
                    r"\bno\s*airflow\b",
                    r"\bno\s*air\b",
                    r"\bblower\b",
                    r"\bhigh\b",
                    r"\bodor\b",
                    r"\bsmell\b",
                ],
            },
        ],
        "quick_options": [
            {"label": "A/C blows warm", "append_text": "A/C blows warm air"},
            {"label": "No air blowing", "append_text": "no air blowing from vents"},
            {"label": "Only works on high", "append_text": "blower motor only works on high setting"},
            {"label": "Musty odor from vents", "append_text": "musty odor when fan is running"},
        ],
    },
]


def analyze_intake_quality(payload: dict[str, Any]) -> dict[str, Any]:
    note = str(payload.get("raw_text") or "")
    answers = payload.get("qualifier_answers") if isinstance(payload.get("qualifier_answers"), dict) else {}
    
    rule = detect_rule(note)
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
        "message": f"Please clarify {' and '.join(missing_labels)} for this {rule['label'].lower()}.",
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


def detect_rule(note: str) -> dict[str, Any] | None:
    text = note.lower()
    for rule in INTAKE_RULES:
        if has_any_pattern(text, rule["triggers"]):
            return rule
    return None


def has_any_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)

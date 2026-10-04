from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any


EXPECTED_KEYS = [
    "customer_explanation",
]

DEFAULT_OUTPUT = {
    "customer_explanation": "",
}

LEGACY_KEY_MAP = {
    "plain_english_customer_concern": "customer_explanation",
    "shop_lingo_interpretation": "customer_explanation",
}

LEGACY_KEYS = set(LEGACY_KEY_MAP)


def normalize_translation_response(response: Any) -> dict[str, Any]:
    candidate = find_best_translation_object(response)
    if isinstance(candidate, dict) and score_translation_object(candidate) > 0:
        res = normalize_translation_object(candidate)
        res["customer_explanation"] = clean_duplicate_sentences(res["customer_explanation"])
        return res

    fallback = plain_text_fallback(response)
    output = deepcopy(DEFAULT_OUTPUT)
    output["customer_explanation"] = clean_duplicate_sentences(fallback)
    return output


def normalize_translation_object(value: dict[str, Any]) -> dict[str, Any]:
    nested = best_nested_translation_object(value)
    if nested is not None and score_translation_object(nested) >= score_translation_object(value):
        value = nested

    value = migrate_legacy_output(value)
    output = deepcopy(DEFAULT_OUTPUT)
    for key in EXPECTED_KEYS:
        raw_value = value.get(key, output[key])
        output[key] = coerce_text(raw_value)
    return output


def migrate_legacy_output(value: dict[str, Any]) -> dict[str, Any]:
    if any(key in value for key in EXPECTED_KEYS):
        return value

    if not any(key in value for key in LEGACY_KEYS):
        return value

    migrated = deepcopy(DEFAULT_OUTPUT)
    for old_key, new_key in LEGACY_KEY_MAP.items():
        if old_key in value:
            migrated[new_key] = value[old_key]

    if not migrated["customer_explanation"]:
        migrated["customer_explanation"] = value.get("structured_" + "diagnostic_intent", "")
    return migrated


def find_best_translation_object(value: Any) -> dict[str, Any] | None:
    candidates = list(iter_json_candidates(value))
    dict_candidates = [candidate for candidate in candidates if isinstance(candidate, dict)]
    if not dict_candidates:
        return None

    return max(dict_candidates, key=score_translation_object)


def best_nested_translation_object(value: Any) -> dict[str, Any] | None:
    candidates = [
        candidate
        for candidate in iter_json_candidates(value)
        if isinstance(candidate, dict) and candidate is not value
    ]
    if not candidates:
        return None
    return max(candidates, key=score_translation_object)


def iter_json_candidates(value: Any) -> list[Any]:
    candidates: list[Any] = []

    if isinstance(value, dict):
        candidates.append(value)
        for nested_value in value.values():
            candidates.extend(iter_json_candidates(nested_value))
        return candidates

    if isinstance(value, list):
        for item in value:
            candidates.extend(iter_json_candidates(item))
        return candidates

    if isinstance(value, str):
        candidates.extend(parse_json_from_text(value))
        for candidate in list(candidates):
            if isinstance(candidate, str) and candidate != value:
                candidates.extend(iter_json_candidates(candidate))
            elif isinstance(candidate, (dict, list)):
                candidates.extend(iter_json_candidates(candidate))
        return candidates

    return candidates


def parse_json_from_text(text: str) -> list[Any]:
    cleaned = strip_markdown_fence(text.strip())
    parsed_values: list[Any] = []

    try:
        parsed_values.append(json.loads(cleaned))
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\{\[]", cleaned):
        try:
            parsed, _index = decoder.raw_decode(cleaned[match.start() :])
        except json.JSONDecodeError:
            continue
        parsed_values.append(parsed)

    return parsed_values


def strip_markdown_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    return re.sub(r"```$", "", text).strip()


def score_translation_object(value: dict[str, Any]) -> int:
    score = 0
    for key in EXPECTED_KEYS:
        if key in value:
            score += 2
            if value.get(key) not in (None, "", [], {}):
                score += 1
    for key in LEGACY_KEYS:
        if key in value:
            score += 1
    return score


def coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        parsed = find_best_translation_object(value)
        if parsed is not None:
            return ""
        return value.strip()
    if isinstance(value, (dict, list)):
        return ""
    return str(value).strip()


def plain_text_fallback(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = strip_markdown_fence(value.strip())
        if looks_like_json(text) or contains_json_object(text):
            return "Model returned malformed structured data; review the saved raw model run if needed."
        return text
    return ""


def looks_like_json(text: str) -> bool:
    stripped = text.strip()
    return (
        (stripped.startswith("{") and stripped.endswith("}"))
        or (stripped.startswith("[") and stripped.endswith("]"))
    )


def contains_json_object(text: str) -> bool:
    return "{" in text and "}" in text


def clean_duplicate_sentences(text: str) -> str:
    if not text:
        return ""
    
    # Split text into sentences using basic punctuation boundary
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    if not sentences:
        return ""
        
    keep = []
    stop_words = {
        'the', 'were', 'was', 'with', 'that', 'this', 'then', 'they', 
        'from', 'have', 'been', 'ready', 'operating', 'normal', 'normally', 
        'confirmed', 'technician', 'vehicle', 'and', 'for', 'are', 'has'
    }
    action_words = {
        'replace', 'replaced', 'replacement', 'need', 'needs', 'recommend', 
        'recommended', 'repair', 'repaired', 'install', 'installed'
    }
    
    for s in sentences:
        is_dup = False
        s_lower = s.lower()
        
        # If the sentence indicates that something "needs" to be replaced or is "recommended"
        if ('need' in s_lower or 'recommend' in s_lower or 'advis' in s_lower) and ('replac' in s_lower or 'install' in s_lower):
            # Extract subject words of length >= 3
            words = set(re.findall(r'[a-zA-Z]{3,}', s_lower))
            subject_words = words - stop_words - action_words
            
            # Check if we already kept a sentence confirming the replacement/work has been done
            for kept in keep:
                kept_lower = kept.lower()
                if 'replac' in kept_lower or 'install' in kept_lower or 'done' in kept_lower or 'fix' in kept_lower:
                    kept_words = set(re.findall(r'[a-zA-Z]{3,}', kept_lower))
                    kept_subject = kept_words - stop_words - action_words
                    
                    # If they share significant nouns/components (e.g. "tie", "rod", "ends")
                    if subject_words and kept_subject:
                        common = subject_words.intersection(kept_subject)
                        if len(common) >= 2 or subject_words.issubset(kept_subject) or kept_subject.issubset(subject_words):
                            is_dup = True
                            break
        
        if not is_dup:
            keep.append(s)
            
    return " ".join(keep)

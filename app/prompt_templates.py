from __future__ import annotations

import json
from typing import Any


SYSTEM_RULES = """You are AutoRO Communication Layer, a local automotive repair-order translation tool.

Your job is to translate rough technician and shop notes into clear customer-facing repair explanations.
This MVP is not diagnostic support. Do not diagnose, recommend procedures, or replace technician judgment.

Rules:
- Return ONLY valid JSON, no markdown, no explanation.
- Do not wrap the JSON object in a string.
- Do not include vehicle metadata, repair order notes, or any other extra object after the output JSON.
- Use exactly the output keys provided below.
- Do not invent TSBs, torque specs, service procedures, labor times, recalls, measurements, or safety-critical facts.
- Do not blame prior work, the customer, another shop, or a technician.
- Do not overpromise or imply a repair is confirmed unless the note clearly says it is confirmed.
- Use plain English, professional, calm, customer-care focused language.
- Abbreviation Glossary: LF = Left Front, RF = Right Front, LR = Left Rear, RR = Right Rear.
"""


OUTPUT_CONTRACT = {
    "customer_explanation": "Final polished customer-facing invoice wording."
}


def build_translation_prompt(
    payload: dict[str, Any],
    approved_examples: list[dict[str, str]] | None = None,
) -> str:
    vehicle = {
        "year": payload.get("vehicle_year"),
        "make": payload.get("vehicle_make"),
        "model": payload.get("vehicle_model"),
        "engine": payload.get("vehicle_engine"),
        "mileage": payload.get("mileage"),
    }

    notes = {
        "category": payload.get("category", ""),
        "technician_note": payload.get("technician_note", ""),
        "technician_name": payload.get("technician_name", ""),
        "qualifier_answers": payload.get("qualifier_answers", {}),
        "note_quality": payload.get("note_quality", {}),
    }

    sections = [
        SYSTEM_RULES,
        "Shop identity context: Calgary independent automotive shop, established 2004. Toyota experience, master tech background, integrity and quality service focus.",
        "Tone target: calm, clear, concise, professional service-advisor invoice wording. No AI wording. No robotic phrasing. No bullet lists unless absolutely necessary.",
        "Return ONLY valid JSON using exactly this structure:",
        json.dumps(OUTPUT_CONTRACT, indent=2),
        "Example style for 'r&r rr axle seal, cleaned bpads, road test ok': The rear axle seal was replaced and the brake pads were cleaned. The vehicle was road tested after the repair and is operating normally at this time.",
        "If qualifier answers are present, use them as confirmed note context. If a qualifier answer is Unknown or blank, do not invent that detail.",
    ]

    if approved_examples:
        sections.extend(
            [
                "Approved shop examples. Match this wording style, but do not copy details that are not in the new note:",
                json.dumps(approved_examples, indent=2),
            ]
        )

    sections.extend(
        [
            "Vehicle metadata:",
            json.dumps(vehicle, indent=2),
            "Technician note:",
            json.dumps(notes, indent=2),
        ]
    )
    return "\n\n".join(sections)


def build_advisor_queue_prompt(raw_text: str) -> str:
    sections = [
        SYSTEM_RULES,
        "You are converting a rough service-advisor RO/customer communication line into customer-facing wording.",
        "Tone target: short, clear, professional, suitable for a customer text, email, or RO note.",
        "Do not invent inspection findings, diagnoses, parts, prices, safety claims, timelines, or approvals.",
        "Do not add consequence language such as prevent damage, unsafe, stranded, urgent, or failed unless the advisor line states it.",
        "If the line is a plan/request rather than a confirmed finding, phrase it as a recommendation or next step.",
        "Keep vague source terms vague. For example, if the advisor says manifold, do not choose intake or exhaust.",
        "Return ONLY valid JSON using exactly this structure:",
        json.dumps(OUTPUT_CONTRACT, indent=2),
        "Advisor line:",
        json.dumps({"raw_text": raw_text}, indent=2),
    ]
    return "\n\n".join(sections)


def build_intake_translation_prompt(raw_text: str, qualifier_answers: dict[str, str]) -> str:
    sections = [
        SYSTEM_RULES,
        "You are converting a rough customer symptom/concern intake note into a professional, highly descriptive repair order (RO) concern statement.",
        "Use the raw text and any provided qualifier answers/details to construct a concise but detailed symptom description.",
        "Guidelines:",
        "- Start with 'Customer states...' or describe the symptom clearly.",
        "- Include details like the type of noise/vibration, under what specific conditions it occurs (accelerating, braking, etc.), and where it is felt or located.",
        "- Do not make diagnostic claims (e.g., do not say 'needs new brakes' unless the customer explicitly asked to replace them). Keep it strictly to the symptoms.",
        "- Target a clean, professional, service-advisor style phrasing.",
        "Return ONLY valid JSON using exactly this structure:",
        json.dumps(OUTPUT_CONTRACT, indent=2),
        "Intake Note:",
        json.dumps({"raw_text": raw_text, "qualifier_details": qualifier_answers}, indent=2),
    ]
    return "\n\n".join(sections)

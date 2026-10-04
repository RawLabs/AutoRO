from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from app.config import settings
from app.model_client import ModelError, generate


ROOT_DIR = Path(__file__).resolve().parent.parent
BG_DB_NAME = "bg_lpp_rules_official_2025.sqlite"
BG_DB_CANDIDATES = (
    ROOT_DIR / "runtime" / "data" / "bg_data" / BG_DB_NAME,
    ROOT_DIR / "data" / "bg_data" / BG_DB_NAME,
    ROOT_DIR / "app" / "bg_data" / BG_DB_NAME,
)
BG_DB_PATH = next((path for path in BG_DB_CANDIDATES if path.is_file()), BG_DB_CANDIDATES[0])
logger = logging.getLogger("autoro.bg_rules")


def bg_lookup(payload: dict[str, Any], include_customer_explanation: bool = True) -> dict[str, Any]:
    if not BG_DB_PATH.exists():
        raise FileNotFoundError(f"BG rules database not found at {BG_DB_PATH}")

    vehicle = normalize_vehicle(payload)
    selected_service_id = to_int(payload.get("service_id"))
    service_status = normalize_service_status(payload.get("service_status"))
    coverage_basis = normalize_coverage_basis(payload.get("coverage_basis"))
    with get_bg_db() as conn:
        sources = rows_to_dicts(conn.execute("SELECT * FROM source_documents").fetchall())
        plan_rules = rows_to_dicts(conn.execute("SELECT * FROM plan_entry_rules ORDER BY id").fetchall())
        service_rules = rows_to_dicts(conn.execute("SELECT * FROM service_rules ORDER BY id").fetchall())
        plan_terms = rows_to_dicts(conn.execute("SELECT * FROM plan_terms ORDER BY id").fetchall())
        advisor_reminders = rows_to_dicts(conn.execute("SELECT * FROM advisor_reminders ORDER BY id").fetchall())

    rule_log: list[str] = [
        f"Loaded BG DB: {BG_DB_PATH.name}",
        f"Read {len(sources)} source_documents rows",
        f"Read {len(plan_rules)} plan_entry_rules rows",
        f"Read {len(service_rules)} service_rules rows",
        f"Read {len(plan_terms)} plan_terms rows",
        f"Read {len(advisor_reminders)} advisor_reminders rows",
    ]

    source_notice = build_source_notice(sources)
    plan = determine_plan(vehicle, plan_rules, rule_log, coverage_basis)
    if selected_service_id is not None:
        selected_service = determine_selected_service(vehicle, plan, service_rules, selected_service_id, rule_log)
        qualifying_services = [selected_service] if selected_service and selected_service["status"] == "eligible" else []
    else:
        selected_service = None
        qualifying_services = determine_qualifying_services(vehicle, plan, service_rules, rule_log)
    eligibility = build_eligibility(qualifying_services, plan)
    advisor_summary = build_advisor_summary(vehicle, plan, qualifying_services, eligibility)
    coverage_terms = build_coverage_terms(qualifying_services, plan, plan_terms)
    interval_reminders = build_interval_reminders(qualifying_services, plan_terms)
    roadside = build_roadside(advisor_reminders, bool(qualifying_services), rule_log)

    result = {
        "vehicle": vehicle,
        "coverage_basis": coverage_basis,
        "selected_service_status": service_status,
        "selected_service": selected_service,
        "likely_plan_tier": plan,
        "advisor_summary": advisor_summary,
        "eligible_bg_systems": eligibility,
        "qualifying_services": qualifying_services,
        "service_interval_reminders": interval_reminders,
        "coverage_terms": coverage_terms,
        "roadside": roadside,
        "enrollment_card_reminder": enrollment_card_reminder(advisor_reminders),
        "verification_notice": source_notice,
        "rule_log": rule_log,
        "customer_explanation": "",
    }

    if include_customer_explanation:
        result["customer_explanation"] = limit_customer_explanation(generate_customer_explanation(result))

    logger.info("BG lookup rule log: %s", " | ".join(rule_log))
    return result


def bg_service_options() -> list[dict[str, Any]]:
    if not BG_DB_PATH.exists():
        raise FileNotFoundError(f"BG rules database not found at {BG_DB_PATH}")

    with get_bg_db() as conn:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT
                    id,
                    service_category,
                    service_name,
                    system_coverage,
                    fuel_type,
                    transmission_applicability,
                    interval_km
                FROM service_rules
                ORDER BY service_category, service_name, id
                """
            ).fetchall()
        )

    return [
        {
            "id": row["id"],
            "category": row["service_category"],
            "name": row["service_name"],
            "covered_system": row["system_coverage"],
            "fuel_type": row.get("fuel_type") or "any",
            "transmission_applicability": row.get("transmission_applicability") or "any",
            "interval_km": row.get("interval_km"),
            "label": f"{row['service_name']} - {row['system_coverage']}",
        }
        for row in rows
    ]


def get_bg_db() -> sqlite3.Connection:
    conn = sqlite3.connect(BG_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def normalize_vehicle(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "year": to_int(payload.get("year")),
        "make": clean_text(payload.get("make")),
        "model": clean_text(payload.get("model")),
        "mileage_km": to_int(payload.get("mileage_km")),
        "fuel_type": normalize_fuel_type(payload.get("fuel_type")),
        "transmission_type": normalize_transmission_type(payload.get("transmission_type")),
    }


def determine_plan(
    vehicle: dict[str, Any],
    plan_rules: list[dict[str, Any]],
    rule_log: list[str],
    coverage_basis: str = "initial",
) -> dict[str, Any]:
    mileage = vehicle["mileage_km"]
    fuel_type = vehicle["fuel_type"]
    vehicle_age = vehicle_age_years(vehicle.get("year"))

    if mileage is None:
        rule_log.append("No mileage supplied; plan tier cannot be determined")
        return plan_result("Verify", "verify", "Mileage is required to compare against official plan entry rules.")

    age_limits = [
        int(row["vehicle_age_max_years"])
        for row in plan_rules
        if row.get("vehicle_age_max_years") is not None
    ]
    if coverage_basis != "existing" and vehicle_age is not None and age_limits and vehicle_age > max(age_limits):
        rule_log.append(f"No plan entry rule matched: vehicle age {vehicle_age} exceeds max {max(age_limits)}")
        return plan_result(
            "Not eligible",
            "not eligible",
            f"Vehicle age is {vehicle_age} years; BG entry rules in this data set allow up to {max(age_limits)} years at initial service.",
        )
    if coverage_basis == "existing":
        rule_log.append("Existing coverage basis selected; initial-service age gate bypassed, records must be verified")

    for row in plan_rules:
        if coverage_basis != "existing" and vehicle_age is not None and row.get("vehicle_age_max_years") is not None:
            if vehicle_age > row["vehicle_age_max_years"]:
                rule_log.append(
                    f"Plan rule skipped id={row['id']}: vehicle age {vehicle_age} exceeds max {row['vehicle_age_max_years']}"
                )
                continue
        if not fuel_matches_rule(fuel_type, row.get("fuel_type")):
            rule_log.append(
                f"Plan rule skipped id={row['id']}: fuel_type={fuel_type or 'unknown'} does not match {row.get('fuel_type')}"
            )
            continue
        if row["mileage_min_km"] <= mileage <= row["mileage_max_km"]:
            rule_log.append(f"Plan entry rule matched id={row['id']} ({row['plan_name']})")
            display = "existing coverage - verify records" if coverage_basis == "existing" else "eligible"
            reason = row.get("notes")
            if coverage_basis == "existing":
                reason = (
                    f"Existing BG coverage selected. Mileage is within {row['plan_name']} range; "
                    "verify prior enrollment, required intervals, and service records before presenting as active."
                )
            return {
                "plan_name": row["plan_name"],
                "status": "eligible",
                "display_status": display,
                "reason": reason,
                "rule_id": row["id"],
                "coverage_percent": plan_coverage_percent(row["plan_name"]),
                "vehicle_age_years": vehicle_age,
            }

    if vehicle_age is None:
        rule_log.append("No plan entry rule matched; vehicle year missing, age eligibility may need verification")
        return plan_result("Verify", "verify", "No matching mileage/fuel rule found; vehicle year was not supplied.")

    rule_log.append("No official plan entry rule matched supplied vehicle")
    return plan_result("Not eligible", "not eligible", "No matching official mileage, age, and fuel entry rule was found.")


def plan_result(plan_name: str, status: str, reason: str) -> dict[str, Any]:
    return {
        "plan_name": plan_name,
        "status": status,
        "display_status": display_status(status),
        "reason": reason,
        "rule_id": None,
        "coverage_percent": None,
        "vehicle_age_years": None,
    }


def determine_qualifying_services(
    vehicle: dict[str, Any],
    plan: dict[str, Any],
    service_rules: list[dict[str, Any]],
    rule_log: list[str],
) -> list[dict[str, Any]]:
    qualifying: list[dict[str, Any]] = []
    for row in service_rules:
        applies, reason = service_applies(vehicle, plan, row)
        if not applies:
            rule_log.append(f"Service skipped id={row['id']} ({service_debug_name(row)}): {reason}")
            continue
        qualifying.append(
            {
                "service_id": row["id"],
                "service_category": row["service_category"],
                "service_name": row["service_name"],
                "advisor_label": advisor_service_label(vehicle, row),
                "covered_system": row["system_coverage"],
                "vehicle_applicability": row.get("fuel_type") or "",
                "transmission_applicability": row.get("transmission_applicability") or "any",
                "interval_km": row.get("interval_km"),
                "plan1_max_reimbursement_usd": row.get("plan1_max_coverage_usd"),
                "plan2_max_reimbursement_usd": row.get("plan2_max_coverage_usd"),
                "entry_service_only": is_entry_service(row),
                "followup_service": row.get("special_notes"),
                "advisor_reminder": row.get("special_notes"),
                "bg_products_required": row.get("bg_products_required"),
                "covered_summary": row.get("covered_summary"),
                "not_covered_summary": row.get("not_covered_summary"),
                "status": "eligible",
                "display_status": "eligible",
                "verification_status": "official_2025_certificate",
            }
        )
        rule_log.append(f"Service included id={row['id']} ({service_debug_name(row)})")
    return qualifying


def determine_selected_service(
    vehicle: dict[str, Any],
    plan: dict[str, Any],
    service_rules: list[dict[str, Any]],
    selected_service_id: int,
    rule_log: list[str],
) -> dict[str, Any] | None:
    selected_rule = None
    for row in service_rules:
        if row["id"] == selected_service_id:
            selected_rule = row
            break

    if selected_rule is None:
        rule_log.append(f"Selected BG service id={selected_service_id} was not found")
        return None

    applies, reason = service_applies(vehicle, plan, selected_rule)
    service = build_service_payload(vehicle, selected_rule)
    if applies:
        service["status"] = "eligible"
        service["display_status"] = "eligible"
        service["advisor_match_note"] = "Advisor-selected BG service matches the supplied vehicle and plan rules."
        rule_log.append(f"Selected service included id={selected_rule['id']} ({service_debug_name(selected_rule)})")
        return service

    service["status"] = "not eligible" if plan["status"] == "not eligible" else "verify"
    service["display_status"] = display_status(service["status"])
    service["advisor_match_note"] = reason
    rule_log.append(f"Selected service needs review id={selected_rule['id']} ({service_debug_name(selected_rule)}): {reason}")
    return service


def build_service_payload(vehicle: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    return {
        "service_id": row["id"],
        "service_category": row["service_category"],
        "service_name": row["service_name"],
        "advisor_label": advisor_service_label(vehicle, row),
        "covered_system": row["system_coverage"],
        "vehicle_applicability": row.get("fuel_type") or "",
        "transmission_applicability": row.get("transmission_applicability") or "any",
        "interval_km": row.get("interval_km"),
        "plan1_max_reimbursement_usd": row.get("plan1_max_coverage_usd"),
        "plan2_max_reimbursement_usd": row.get("plan2_max_coverage_usd"),
        "entry_service_only": is_entry_service(row),
        "followup_service": row.get("special_notes"),
        "advisor_reminder": row.get("special_notes"),
        "bg_products_required": row.get("bg_products_required"),
        "covered_summary": row.get("covered_summary"),
        "not_covered_summary": row.get("not_covered_summary"),
        "status": "eligible",
        "display_status": "eligible",
        "verification_status": "official_2025_certificate",
    }


def service_applies(vehicle: dict[str, Any], plan: dict[str, Any], service: dict[str, Any]) -> tuple[bool, str]:
    if plan["status"] == "not eligible":
        return False, "skipped: mileage/plan not applicable; no eligible BG plan matched"

    fuel_type = vehicle["fuel_type"]
    transmission_type = vehicle["transmission_type"]
    year = vehicle["year"]
    mileage = vehicle["mileage_km"]
    service_fuel = clean_text(service.get("fuel_type")).lower()
    transmission_applicability = clean_text(service.get("transmission_applicability")).lower() or "any"

    if service_fuel and not fuel_matches_service(fuel_type, service_fuel):
        return False, f"skipped: fuel mismatch; requires {service_fuel}, vehicle fuel is {fuel_type or 'unknown'}"
    if not transmission_matches_service(transmission_type, transmission_applicability):
        return (
            False,
            f"skipped: transmission mismatch; requires {transmission_applicability}, vehicle transmission is {transmission_type or 'unknown'}",
        )
    if is_entry_service(service) and not is_high_mileage_gasoline_entry(vehicle):
        return False, "skipped: mileage/plan not applicable; high-mileage gasoline entry service applies only from 120,001-200,000 km"
    if is_entry_service(service) and mileage is None:
        return False, "skipped: mileage/plan not applicable; high-mileage gasoline entry service requires mileage"
    if "cvt" in clean_text(service.get("service_name")).lower():
        if year is not None and year < 2014:
            return False, "skipped: model year requirement; CVT service requires model year 2014 and newer"
    return True, "matches official service rule filters"


def build_advisor_summary(
    vehicle: dict[str, Any],
    plan: dict[str, Any],
    qualifying_services: list[dict[str, Any]],
    eligibility: list[dict[str, Any]],
) -> dict[str, Any]:
    primary_service = choose_primary_service(vehicle, plan, qualifying_services)
    protection_items = build_protection_value_items(qualifying_services, plan)
    intervals = [
        service.get("interval_km")
        for service in qualifying_services
        if service.get("interval_km") is not None
    ]
    next_interval = primary_service.get("interval_km") if primary_service else None
    if next_interval is None and intervals:
        next_interval = min(intervals)
    return {
        "plan": plan["plan_name"],
        "plan_status": plan["display_status"],
        "primary_recommended_action": format_primary_action(primary_service, plan),
        "primary_service": primary_service,
        "protection_opportunity": [item["system"] for item in eligibility if item["status"] == "eligible"],
        "protection_value_items": protection_items,
        "total_potential_coverage_usd": sum(
            item["max_coverage_usd"] for item in protection_items if item["max_coverage_usd"] is not None
        ),
        "coverage_disclaimer": "Coverage subject to BG terms, conditions, claim approval, and maintenance compliance.",
        "next_service_interval_km": next_interval,
        "roadside_visible": bool(qualifying_services) and plan["status"] != "not eligible",
        "decision_note": build_decision_note(vehicle, plan, primary_service),
    }


def build_protection_value_items(
    qualifying_services: list[dict[str, Any]],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    if plan["status"] != "eligible":
        return []

    systems: dict[str, dict[str, Any]] = {}
    for service in qualifying_services:
        system = protection_display_system(service)
        group = protection_group(service)
        rank = protection_rank(service)
        coverage = service_coverage_for_plan(service, plan)
        interval = service.get("interval_km")
        existing = systems.get(group)
        if existing is None:
            systems[group] = {
                "coverage_group": group,
                "covered_system": system,
                "_coverage_rank": rank,
                "max_coverage_usd": coverage,
                "interval_km": interval,
                "source_service": service["advisor_label"],
            }
            continue

        existing_coverage = existing.get("max_coverage_usd")
        should_replace = coverage is not None and (existing_coverage is None or coverage > existing_coverage)
        should_replace = should_replace or (
            coverage is not None
            and existing_coverage == coverage
            and rank > existing.get("_coverage_rank", 0)
        )
        if should_replace:
            existing["max_coverage_usd"] = coverage
            existing["covered_system"] = system
            existing["_coverage_rank"] = rank
            existing["source_service"] = service["advisor_label"]
        if interval is not None and (existing.get("interval_km") is None or interval < existing["interval_km"]):
            existing["interval_km"] = interval

    values = list(systems.values())
    for value in values:
        value.pop("_coverage_rank", None)
    return values


def service_coverage_for_plan(service: dict[str, Any], plan: dict[str, Any]) -> int | None:
    plan_name = plan.get("plan_name", "")
    if "Plan 1" in plan_name:
        return service.get("plan1_max_reimbursement_usd")
    if "Plan 2" in plan_name:
        return service.get("plan2_max_reimbursement_usd")
    return None


def protection_group(service: dict[str, Any]) -> str:
    system = service["covered_system"].lower()
    if system in {"engine", "engine and fuel"}:
        return "engine_fuel"
    if system in {"fuel plus throttle body", "fuel plus throttle body and intake valves"}:
        return "fuel_system"
    if system in {"automatic transmission", "cvt transmission"}:
        return "transmission"
    return system


def protection_display_system(service: dict[str, Any]) -> str:
    system = service["covered_system"]
    group = protection_group(service)
    if group == "engine_fuel":
        return "Engine & Fuel"
    if group == "fuel_system":
        return system
    if group == "transmission":
        return system
    return system


def protection_rank(service: dict[str, Any]) -> int:
    system = service["covered_system"].lower()
    if system == "engine and fuel":
        return 2
    if system == "fuel plus throttle body and intake valves":
        return 2
    return 1


def choose_primary_service(
    vehicle: dict[str, Any],
    plan: dict[str, Any],
    qualifying_services: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not qualifying_services or plan["status"] == "not eligible":
        return None

    if is_high_mileage_gasoline_entry(vehicle):
        dynamic = find_service(qualifying_services, "Dynamic Engine Restoration Service")
        if dynamic:
            return dynamic

    preferred_names = [
        "Engine Service - Gasoline/Hybrid",
        "Engine Service - Diesel",
        "Engine & Fuel Service - Gasoline/Hybrid",
        "Engine & Fuel Service - Diesel",
        "Fuel System Service",
        "Transmission Service",
        "CVT Service",
        "Cooling System Service",
        "Power Steering Service",
        "Drive Line Service",
        "Brake Service",
    ]
    for name in preferred_names:
        service = find_service(qualifying_services, name)
        if service:
            return service
    return qualifying_services[0]


def find_service(services: list[dict[str, Any]], service_name: str) -> dict[str, Any] | None:
    for service in services:
        if service["service_name"] == service_name:
            return service
    return None


def format_primary_action(service: dict[str, Any] | None, plan: dict[str, Any]) -> str:
    if plan["status"] == "not eligible":
        return "No qualifying BG service action from the current rules."
    if plan["status"] == "verify":
        return "Verify BG eligibility before recommending a service."
    if service is None:
        return "Review BG opportunities; no qualifying service matched the supplied vehicle details."
    return service["advisor_label"]


def build_decision_note(
    vehicle: dict[str, Any],
    plan: dict[str, Any],
    primary_service: dict[str, Any] | None,
) -> str:
    if plan["status"] == "not eligible":
        return plan.get("reason") or "Vehicle did not match an eligible plan entry rule."
    if plan["status"] == "verify":
        return plan.get("reason") or "More vehicle information is needed."
    if "existing coverage" in clean_text(plan.get("display_status")).lower():
        return "Existing BG coverage path selected; verify prior enrollment, interval compliance, and repair-order records."
    if is_high_mileage_gasoline_entry(vehicle):
        return "High-mileage gasoline Plan 2 entry path."
    mileage = vehicle.get("mileage_km")
    if mileage is not None and mileage <= 80000:
        return "Plan 1 entry window applies before 80,000 km."
    if mileage is not None and 80001 <= mileage <= 120000:
        return "Plan 2 entry window applies."
    if primary_service:
        return "Primary opportunity selected from qualifying services."
    return ""


def build_eligibility(
    qualifying_services: list[dict[str, Any]],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    systems: dict[str, dict[str, Any]] = {}
    for service in qualifying_services:
        system = service["covered_system"]
        status = service["status"]
        if plan["status"] == "not eligible":
            status = "not eligible"
        elif plan["status"] == "verify":
            status = "verify"
        systems[system] = {
            "system": system,
            "status": status,
            "display_status": display_status(status),
        }
    return list(systems.values())


def build_coverage_terms(
    qualifying_services: list[dict[str, Any]],
    plan: dict[str, Any],
    plan_terms: list[dict[str, Any]],
) -> list[str]:
    terms: list[str] = []
    if plan.get("reason"):
        terms.append(f"{plan['plan_name']}: {plan['reason']} ({plan['display_status']}).")
    for term in plan_terms:
        terms.append(f"{term['term_type']}: {term['term_text']} Advisor note: {term['advisor_effect']}")
    for service in qualifying_services:
        pieces = [service["service_name"]]
        if service.get("interval_km"):
            pieces.append(f"interval {service['interval_km']:,} km")
        if service.get("plan1_max_reimbursement_usd") is not None:
            pieces.append(f"Plan 1 max coverage ${service['plan1_max_reimbursement_usd']:,} USD")
        if service.get("plan2_max_reimbursement_usd") is not None:
            pieces.append(f"Plan 2 max coverage ${service['plan2_max_reimbursement_usd']:,} USD")
        if service.get("bg_products_required"):
            pieces.append(f"required products: {service['bg_products_required']}")
        if service.get("not_covered_summary"):
            pieces.append(f"not covered: {service['not_covered_summary']}")
        terms.append("; ".join(pieces) + ".")
    return terms


def build_interval_reminders(
    qualifying_services: list[dict[str, Any]],
    plan_terms: list[dict[str, Any]],
) -> list[str]:
    reminders: list[str] = []
    for service in qualifying_services:
        if service.get("interval_km"):
            reminders.append(f"{service['service_name']}: every {service['interval_km']:,} km.")
        if service.get("followup_service"):
            reminders.append(f"{service['service_name']} note: {service['followup_service']}.")
    for term in plan_terms:
        if term["term_type"] in {"Grace Period", "Plan 2 Delay"}:
            reminders.append(f"{term['term_type']}: {term['advisor_effect']}")
    return reminders


def build_roadside(
    advisor_reminders: list[dict[str, Any]],
    has_qualifying_service: bool,
    rule_log: list[str],
) -> dict[str, Any]:
    reminder_rows = []
    for row in advisor_reminders:
        reminder_rows.append(
            {
                "rule_id": row["id"],
                "rule_name": row["trigger_condition"],
                "qualifying_condition": row["trigger_condition"],
                "term_months": None,
                "max_events_per_term": None,
                "max_claims_window": "",
                "availability": "",
                "advisor_reminder": row["reminder_text"],
                "display_status": "eligible" if has_qualifying_service else "not eligible",
                "verification_status": "official_2025_certificate",
            }
        )
        rule_log.append(f"Advisor reminder read id={row['id']} ({row['trigger_condition']})")

    explicit_reminders = [
        "Remind advisor to offer BG On The Road if qualifying service applies.",
        "Remind advisor to provide BG enrollment card.",
    ]
    for row in advisor_reminders:
        if "roadside" in row["reminder_text"].lower() or "enrollment" in row["reminder_text"].lower():
            explicit_reminders.append(row["reminder_text"])
    return {
        "applies": has_qualifying_service,
        "reminders": list(dict.fromkeys(explicit_reminders)),
        "rules": reminder_rows,
    }


def enrollment_card_reminder(advisor_reminders: list[dict[str, Any]]) -> str:
    for row in advisor_reminders:
        if "enrollment" in row["reminder_text"].lower() or "card" in row["reminder_text"].lower():
            return row["reminder_text"]
    return "Provide BG enrollment card."


def generate_customer_explanation(result: dict[str, Any]) -> str:
    confirmed_payload = {
        "vehicle": result["vehicle"],
        "coverage_basis": result.get("coverage_basis"),
        "advisor_selected_service": result.get("selected_service"),
        "service_status": result.get("selected_service_status"),
        "likely_plan_tier": result["likely_plan_tier"],
        "advisor_summary": result["advisor_summary"],
        "qualifying_services": [
            {
                "service_name": service["advisor_label"],
                "covered_system": service["covered_system"],
                "display_status": service["display_status"],
                "interval_km": service.get("interval_km"),
                "plan1_max_reimbursement_usd": service.get("plan1_max_reimbursement_usd"),
                "plan2_max_reimbursement_usd": service.get("plan2_max_reimbursement_usd"),
            }
            for service in result["qualifying_services"]
        ],
        "roadside_reminders": result["roadside"]["reminders"],
        "verification_notice": result["verification_notice"],
    }
    prompt = "\n\n".join(
        [
            "Write a short customer-friendly BG coverage explanation for a service advisor.",
            "Maximum 4 short lines. Calm and practical. No marketing fluff.",
            "The advisor has already selected the BG service proposed or performed. Do not recommend additional services.",
            "Focus on coverage, term/interval requirements, documentation, and roadside/enrollment reminders.",
            "Use only the supplied deterministic rule output. Do not invent BG terms, coverage, dollar amounts, or service details.",
            "Do not say 'our BG Protection Plan'. Refer to BG protection or BG service eligibility only.",
            "If current operational terms should be verified, say the advisor will verify current BG details before presenting coverage as final.",
            json.dumps(confirmed_payload, indent=2),
        ]
    )
    try:
        return generate(prompt, model_name=settings.model_name).response_text.strip()
    except ModelError as exc:
        logger.warning("BG customer explanation generation failed: %s", exc)
        service = result.get("selected_service") or {}
        plan = result.get("likely_plan_tier") or {}
        if service.get("status") == "eligible":
            return (
                f"The selected BG service may qualify this vehicle for {plan.get('plan_name', 'BG')} protection "
                "when the service is completed, documented, and maintained at the required interval. "
                "Roadside/enrollment details should be provided according to current BG program requirements."
            )
        return "Verify BG eligibility before presenting coverage or roadside/enrollment benefits as active."


def limit_customer_explanation(text: str) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if len(lines) > 1:
        return "\n".join(lines[:6])

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    return " ".join(sentences[:4]).strip()


def build_source_notice(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "Verify current BG operational process before customer-facing use."
    source = sources[0]
    return (
        f"Rules sourced from {source['source_name']} ({source['revision']}, accessed {source['accessed_date']}). "
        "Verify Canadian distributor/dealer operational details before counter use."
    )


def fuel_matches_rule(fuel_type: str, rule_fuel: str | None) -> bool:
    rule_fuel = clean_text(rule_fuel).lower()
    if rule_fuel in {"", "any"}:
        return True
    if not fuel_type:
        return False
    return fuel_type == normalize_fuel_type(rule_fuel)


def fuel_matches_service(fuel_type: str, service_fuel: str) -> bool:
    normalized_service_fuel = clean_text(service_fuel).lower()
    if normalized_service_fuel in {"", "any"}:
        return True
    if not fuel_type:
        return normalized_service_fuel in {"", "any"}
    allowed = {normalize_fuel_type(item) for item in re.split(r"[/, ]+", normalized_service_fuel) if item}
    if "any" in allowed:
        return True
    return fuel_type in allowed


def transmission_matches_service(transmission_type: str, service_transmission: str) -> bool:
    service_transmission = normalize_transmission_type(service_transmission)
    if service_transmission in {"", "any"}:
        return True
    if not transmission_type:
        return False
    return transmission_type == service_transmission


def normalize_fuel_type(value: Any) -> str:
    fuel = clean_text(value).lower()
    if fuel in {"gas", "petrol"}:
        return "gasoline"
    if fuel in {"electric"}:
        return "ev"
    return fuel


def normalize_transmission_type(value: Any) -> str:
    transmission = clean_text(value).lower()
    if transmission in {"auto", "automatic transmission"}:
        return "automatic"
    if transmission in {"standard", "manual transmission", "manual transaxle"}:
        return "manual"
    if transmission in {"continuously variable", "continuously variable transmission"}:
        return "cvt"
    return transmission


def normalize_service_status(value: Any) -> str:
    status = clean_text(value).lower()
    if status in {"done", "completed", "performed"}:
        return "performed"
    return "proposed"


def normalize_coverage_basis(value: Any) -> str:
    basis = clean_text(value).lower()
    if basis in {"existing", "active", "already covered", "previously enrolled"}:
        return "existing"
    return "initial"


def vehicle_age_years(year: int | None) -> int | None:
    if year is None:
        return None
    return max(date.today().year - year, 0)


def plan_coverage_percent(plan_name: str) -> int | None:
    if "Plan 1" in plan_name:
        return 100
    if "Plan 2" in plan_name:
        return 50
    return None


def is_entry_service(service: dict[str, Any]) -> bool:
    return "dynamic engine restoration" in clean_text(service.get("service_name")).lower()


def is_high_mileage_gasoline_entry(vehicle: dict[str, Any]) -> bool:
    mileage = vehicle.get("mileage_km")
    if mileage is None:
        return False
    return vehicle.get("fuel_type") == "gasoline" and 120001 <= mileage <= 200000


def advisor_service_label(vehicle: dict[str, Any], service: dict[str, Any]) -> str:
    service_name = service["service_name"]
    if service_name == "Drive Line Service" and vehicle.get("transmission_type") == "manual":
        return "Drive Line Service - differentials / transfer case / manual transmission where applicable"
    return service_name


def service_debug_name(service: dict[str, Any]) -> str:
    service_name = service["service_name"]
    system = clean_text(service.get("system_coverage"))
    if system and system.lower() not in service_name.lower():
        return f"{service_name} - {system}"
    return service_name


def display_status(status: str) -> str:
    if status == "verify":
        return "Needs BG verification"
    return status


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

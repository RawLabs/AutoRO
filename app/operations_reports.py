from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from app.config import PORTABLE_ROOT, settings


NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def reports_root() -> Path:
    root = Path(settings.reports_root).expanduser()
    if not root.is_absolute():
        root = PORTABLE_ROOT / root
    return root.resolve()


def valid_month(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", value))


def resolve_month_directory(month: str, root: Path | None = None) -> Path:
    if not valid_month(month):
        raise ValueError("Report month must use YYYY-MM format.")
    resolved_root = (root or reports_root()).resolve()
    month_dir = (resolved_root / month).resolve()
    try:
        month_dir.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("Report month must remain inside the reports directory.") from exc
    return month_dir


def valid_code(code: str | None) -> bool:
    return bool(code) and str(code).strip() == settings.management_code


def available_months() -> list[str]:
    root = reports_root()
    if not root.exists():
        return []
    return sorted([p.name for p in root.iterdir() if p.is_dir() and valid_month(p.name)], reverse=True)


def latest_month() -> str:
    months = available_months()
    return months[0] if months else ""


def build_month_digest(month: str | None = None) -> dict[str, Any]:
    selected_month = month or latest_month()
    month_dir = resolve_month_directory(selected_month) if selected_month else reports_root()
    reports = read_month_reports(month_dir) if selected_month else []
    by_key = {report["key"]: report for report in reports}

    business = first_row(by_key.get("business_summary"))
    advisor_rows = rows_for(by_key.get("sales_by_service_advisor"))
    category_rows = rows_for(by_key.get("category_profit_summary"))
    tech_rows = rows_for(by_key.get("technician_pay_hours"))
    wip_rows = rows_for(by_key.get("work_in_progress"))
    discount_rows = rows_for(by_key.get("discount_summary"))
    deleted_orders = rows_for(by_key.get("deleted_orders"))
    deleted_payments = rows_for(by_key.get("deleted_payments"))
    po_rows = rows_for(by_key.get("outstanding_purchase_orders"))
    low_inventory_rows = rows_for(by_key.get("low_inventory_by_vendor"))

    total_sales = number(business.get("Total Sales"))
    gross_profit = number(business.get("Gross Profit"))
    car_count = number(business.get("Car Count"))
    billed_hours = number(business.get("Billed Labour Hours"))
    discounts = number(business.get("Discounts Given"))
    gp_percent = (gross_profit / total_sales * 100) if total_sales else 0
    average_ro = (total_sales / car_count) if car_count else 0
    sales_per_billed_hour = (total_sales / billed_hours) if billed_hours else 0

    kpis = [
        kpi("Total Sales", money(total_sales)),
        kpi("Gross Profit", money(gross_profit), f"{gp_percent:.1f}% GP"),
        kpi("Car Count", whole(car_count)),
        kpi("Average RO", money(average_ro)),
        kpi("Billed Hours", f"{billed_hours:,.1f}"),
        kpi("Sales / Billed Hour", money(sales_per_billed_hour)),
        kpi("Discounts Given", money(discounts)),
        kpi("Open WIP Dollars", money(sum(number(row.get("WIP Dollars")) for row in wip_rows))),
    ]

    highlights = [
        f"Gross profit is {money(gross_profit)} on {money(total_sales)} sales ({gp_percent:.1f}% GP).",
        f"Average RO is {money(average_ro)} across {whole(car_count)} repair orders.",
        f"Discounts total {money(discounts)} for the month.",
        f"Open WIP currently represents {money(sum(number(row.get('WIP Dollars')) for row in wip_rows))}.",
    ]
    risks = []
    if discounts > total_sales * 0.02:
        risks.append("Discounts exceed 2% of sales; review advisor discount patterns.")
    if deleted_orders:
        risks.append(f"{len(deleted_orders)} deleted order(s) require audit review.")
    if deleted_payments:
        risks.append(f"{len(deleted_payments)} deleted payment(s) require audit review.")
    if low_inventory_rows:
        risks.append(f"{len(low_inventory_rows)} low-inventory item(s) may affect fill rate.")
    if po_rows:
        risks.append(f"{len(po_rows)} outstanding purchase order(s) remain open.")
    opportunities = []
    low_gp_categories = [row for row in category_rows if number(row.get("Gross Profit %")) < 45]
    if low_gp_categories:
        opportunities.append("Review low-margin categories: " + ", ".join(str(row.get("Category")) for row in low_gp_categories) + ".")
    under_100 = [row for row in tech_rows if number(row.get("Productivity %")) < 100]
    if under_100:
        opportunities.append("Technician productivity coaching: " + ", ".join(str(row.get("Technician")) for row in under_100) + ".")

    return {
        "month": selected_month,
        "reports_root": str(reports_root()),
        "months": available_months(),
        "kpis": kpis,
        "highlights": highlights,
        "risks": risks,
        "opportunities": opportunities,
        "analytics": {
            "sales_by_advisor": advisor_rows,
            "category_profit": category_rows,
            "technician_hours": tech_rows,
            "work_in_progress": wip_rows,
            "discounts": discount_rows,
        },
        "reports": reports,
    }


def read_month_reports(month_dir: Path) -> list[dict[str, Any]]:
    if not month_dir.exists() or not month_dir.is_dir():
        return []
    reports: list[dict[str, Any]] = []
    for path in sorted(month_dir.glob("*.xlsx")):
        headers, rows = read_xlsx_table(path)
        reports.append({
            "key": report_key(path),
            "title": report_title(path),
            "filename": path.name,
            "path": str(path),
            "headers": headers,
            "rows": rows,
            "row_count": len(rows),
        })
    return reports


def read_xlsx_table(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    values = read_xlsx_values(path)
    if not values:
        return [], []
    headers = [str(value or "").strip() for value in values[0]]
    rows = []
    for raw_row in values[1:]:
        if not any(value not in (None, "") for value in raw_row):
            continue
        row = {}
        for idx, header in enumerate(headers):
            if not header:
                continue
            row[header] = raw_row[idx] if idx < len(raw_row) else None
        rows.append(row)
    return headers, rows


def read_xlsx_values(path: Path) -> list[list[Any]]:
    with zipfile.ZipFile(path) as zf:
        shared = read_shared_strings(zf)
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        first_sheet = workbook.find("main:sheets/main:sheet", NS)
        if first_sheet is None:
            return []
        rel_id = first_sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        target = None
        for rel in rels:
            if rel.attrib.get("Id") == rel_id:
                target = rel.attrib.get("Target")
                break
        sheet_path = "xl/" + (target or "worksheets/sheet1.xml").lstrip("/")
        sheet = ET.fromstring(zf.read(sheet_path))
    rows: list[list[Any]] = []
    for row_el in sheet.findall("main:sheetData/main:row", NS):
        row_values: list[Any] = []
        for cell in row_el.findall("main:c", NS):
            idx = column_index(cell.attrib.get("r", "A1"))
            while len(row_values) < idx:
                row_values.append(None)
            row_values.append(cell_value(cell, shared))
        rows.append(row_values)
    return rows


def read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    strings = []
    for si in root.findall("main:si", NS):
        parts = [text.text or "" for text in si.findall(".//main:t", NS)]
        strings.append("".join(parts))
    return strings


def cell_value(cell: ET.Element, shared: list[str]) -> Any:
    cell_type = cell.attrib.get("t")
    value_el = cell.find("main:v", NS)
    if value_el is None:
        inline = cell.find("main:is/main:t", NS)
        return inline.text if inline is not None else None
    raw = value_el.text or ""
    if cell_type == "s":
        return shared[int(raw)] if raw.isdigit() and int(raw) < len(shared) else raw
    if cell_type == "b":
        return raw == "1"
    try:
        number_value = float(raw)
        return int(number_value) if number_value.is_integer() else number_value
    except ValueError:
        return raw


def column_index(cell_ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", cell_ref.upper())
    total = 0
    for char in letters:
        total = total * 26 + (ord(char) - 64)
    return max(total - 1, 0)


def report_key(path: Path) -> str:
    return path.stem.replace("_demo", "")


def report_title(path: Path) -> str:
    return report_key(path).replace("_", " ").title()


def first_row(report: dict[str, Any] | None) -> dict[str, Any]:
    rows = rows_for(report)
    return rows[0] if rows else {}


def rows_for(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not report:
        return []
    return list(report.get("rows") or [])


def number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^0-9.-]", "", str(value))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def money(value: float) -> str:
    return f"${value:,.2f}"


def whole(value: float) -> str:
    return f"{int(value):,}"


def kpi(label: str, value: str, note: str = "") -> dict[str, str]:
    return {"label": label, "value": value, "note": note}


def manager_answer(question: str, digest: dict[str, Any]) -> str:
    q = question.strip() or "Summarize the monthly report."
    payload = {
        "question": q,
        "month": digest.get("month"),
        "highlights": digest.get("highlights", []),
        "risks": digest.get("risks", []),
        "opportunities": digest.get("opportunities", []),
    }
    lines = [
        f"Question: {payload['question']}",
        f"Month: {payload['month']}",
        "",
        "Best read:",
    ]
    for item in payload["highlights"][:4]:
        lines.append(f"- {item}")
    if payload["risks"]:
        lines.append("")
        lines.append("Risks to review:")
        lines.extend(f"- {item}" for item in payload["risks"][:5])
    if payload["opportunities"]:
        lines.append("")
        lines.append("Opportunities:")
        lines.extend(f"- {item}" for item in payload["opportunities"][:5])
    lines.append("")
    lines.append("Source digest:")
    lines.append(json.dumps(payload, indent=2))
    return "\n".join(lines)

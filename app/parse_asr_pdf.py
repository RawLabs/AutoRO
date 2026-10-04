#!/usr/bin/env python3
"""
Parse a Mitchell SubEstimate / ASR PDF into a standard manifest JSON.
"""
import re
import sys
import json
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

def extract_text(pdf_path: str) -> str:
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            ["pdftotext", "-layout", pdf_path, "-"],
            stdout=output,
            stderr=errors,
        )
        try:
            process.wait(timeout=45)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise TimeoutError("PDF text extraction exceeded 45 seconds.")
        if process.returncode:
            errors.seek(0)
            detail = errors.read(64 * 1024).decode("utf-8", errors="replace")
            raise RuntimeError(f"PDF text extraction failed: {detail.strip()}")
        size = output.tell()
        if size > 5 * 1024 * 1024:
            raise ValueError("Extracted PDF text exceeded the 5 MB limit.")
        output.seek(0)
        return output.read().decode("utf-8", errors="replace")

def parse_header(text: str) -> dict:
    lines = [l.rstrip() for l in text.splitlines()]
    meta = {
        "shop": "AutoRO",
        "customer": {"name": "", "phone": "", "email": ""},
        "year": "",
        "make": "",
        "model": "",
        "vin": "",
        "plate": "",
        "mileage": "",
        "estimate_date": "",
        "estimate_number": "",
        "estimate_due": "",
        "customer_id": "",
        "service_advisor": "",
    }

    for line in lines:
        # Match Estimate # or Sub Estimate for Order # or Order #
        m = re.search(r"(?:Sub\s+Estimate\s+for\s+Order|Estimate|Order)\s*#\s*([0-9A-Za-z-]+)", line, re.IGNORECASE)
        if m:
            meta["estimate_number"] = m.group(1)
        
        # Estimate Due
        m = re.search(r"Estimate Due:\s*\$([0-9\.,]+)", line, re.IGNORECASE)
        if m:
            meta["estimate_due"] = m.group(1)
            
        # Customer name + vehicle line
        m = re.search(r"([A-Za-z][A-Za-z\s,]{2,40})\s{2,}(\d{4})\s+([A-Za-z]+)\s+-\s+([A-Za-z0-9\s\-]+)", line)
        if m:
            meta["customer"]["name"] = m.group(1).strip().rstrip(",")
            meta["year"] = int(m.group(2))
            meta["make"] = m.group(3)
            model_raw = re.split(r"\s{2,}", m.group(4))
            meta["model"] = model_raw[0].strip()
            continue
            
        # Vehicle fallback
        m = re.search(r"(\d{4})\s+([A-Za-z]+)\s+-\s+([A-Za-z0-9\s\-]+)", line)
        if m and not meta["make"]:
            meta["year"] = int(m.group(1))
            meta["make"] = m.group(2)
            meta["model"] = re.split(r"\s{2,}", m.group(3))[0].strip()
            
        # VIN (flexible stop)
        m = re.search(r"VIN:\s*([A-Z0-9\s]+?)(?:\s{2,}|$)", line, re.IGNORECASE)
        if m:
            meta["vin"] = m.group(1).replace(" ", "").strip()
            continue
            
        # License Plate
        m = re.search(r"License Plate:\s*([A-Z0-9\-\s]+)", line, re.IGNORECASE)
        if m:
            meta["plate"] = m.group(1).strip()
            
        # Odometer
        m = re.search(r"Odometer:\s*(.+)", line, re.IGNORECASE)
        if m:
            meta["mileage"] = m.group(1).strip().replace("In ", "").strip()
            
        # Estimate Date
        m = re.search(r"Estimate Date:\s*([\d\-/]+)", line, re.IGNORECASE)
        if m:
            meta["estimate_date"] = m.group(1)
            
        # Customer ID
        m = re.search(r"Customer ID:\s*(\d+)", line, re.IGNORECASE)
        if m:
            meta["customer_id"] = m.group(1)
            
        # Service Advisor
        m = re.search(r"Service Advisor:\s*(.+)", line, re.IGNORECASE)
        if m and m.group(1).strip():
            meta["service_advisor"] = m.group(1).strip()
            
        # Home phone
        m = re.search(r"Home:\s*([\d\-\s\(\)]+)", line, re.IGNORECASE)
        if m:
            meta["customer"]["phone"] = m.group(1).strip()
            
        # Cell/Mobile phone fallback
        m = re.search(r"(?:Cell|Cellular|Mobile):\s*([\d\-\s\(\)]+)", line, re.IGNORECASE)
        if m and not meta["customer"]["phone"]:
            meta["customer"]["phone"] = m.group(1).strip()
            
    return meta

def clean_title(raw: str) -> str:
    t = raw.strip().rstrip(",")
    for pat in (
        r"[\s,]*ACCORDING TO\s+CUSTOMER.*$",
        r"[\s,]*ACCORDING TO.*$",
        r"[\s,]*CUSTOMER\s+WAS\s+ADVISED.*$",
        r"[\s,]*CUSTOMER\s+STATES.*$",
        r"[\s,]*NOTE\s+ABOUT.*$",
        r"[\s,]*--.*$",
    ):
        t = re.sub(pat, "", t, flags=re.IGNORECASE).strip().rstrip(",")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s*\([^)]*INTERVAL[^)]*\)", "", t, flags=re.IGNORECASE).strip()
    if len(t) > 120:
        t = t[:120].rsplit(" ", 1)[0].strip().rstrip(",")
    return t if t else raw.strip()

def clean_detail(raw: str) -> str:
    text = re.sub(r"\s+", " ", str(raw or "")).strip(" ,-")
    text = re.sub(r"^(Labor|Part)\s+", "", text, flags=re.IGNORECASE).strip(" ,-")
    text = re.sub(r"\s*\$[\d,]+\.\d{2}.*$", "", text).strip(" ,-")
    return text

def is_job_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if line.startswith("       "):
        return False
    if "Initials:" not in stripped:
        return False
    if not re.search(r"\$[\d\.,]+", stripped):
        return False
    if stripped.startswith(("Type ", "Parts:", "Labor:", "Tax:", "Total:")):
        return False
    return True

def title_from_job_header(line: str) -> str:
    left = re.split(r"\s+Initials:", line.strip(), maxsplit=1)[0]
    left = re.sub(r"\s+\$[\d\.,]+\s*$", "", left).strip()
    return clean_title(left)

def parse_jobs(text: str) -> list:
    lines = [l.rstrip() for l in text.splitlines()]
    jobs = []
    current_job = None
    current_parts = []
    current_labours = []
    last_item_type = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
            
        if is_job_header(line):
            if current_job:
                current_job["parts"] = current_parts
                current_job["labour"] = current_labours
                jobs.append(current_job)
            current_job = {"title": title_from_job_header(line)}
            current_parts = []
            current_labours = []
            last_item_type = "header"
            continue

        if current_job is not None:
            # Mitchell's order-level fee heading can follow the final job with
            # no explicit delimiter. It is not part of the preceding part line.
            if re.match(r"^Order\s+\$[\d,.]+$", stripped, re.IGNORECASE):
                last_item_type = "other"
                continue
            if stripped.startswith("Part"):
                m = re.search(r"Part\s+(.+?)\s{2,}([\d\.]+)\s+\$([\d\.,]+)\s+\$([\d\.,]+)", line)
                if m:
                    current_parts.append({
                        "description": m.group(1).strip(),
                        "qty": float(m.group(2)),
                        "price": float(m.group(3).replace(",", "")),
                        "total": float(m.group(4).replace(",", "")),
                    })
                last_item_type = "part"
                continue
            if stripped.startswith("Labor"):
                desc_m = re.search(r"^\s*Labor\s+(.+?)\s+[\d\.]+\s*hr\b", line)
                if desc_m:
                    desc = desc_m.group(1).strip()
                else:
                    left = re.split(r"\s{2,}", line.strip(), maxsplit=2)
                    desc = re.sub(r"^\s*Labor\s+", "", left[-1] if left else line.strip()).strip()
                hr_m = re.search(r"([\d\.]+)\s*hr", line)
                dollars = re.findall(r"\$([\d\.,]+)", line)
                rate = float(dollars[0].replace(",", "")) if dollars else 0.0
                total = float(dollars[1].replace(",", "")) if len(dollars) > 1 else (float(dollars[0].replace(",", "")) if dollars else 0.0)
                if len(dollars) <= 1:
                    rate = 0.0
                hrs = float(hr_m.group(1)) if hr_m else 0.0
                current_labours.append({
                    "description": desc,
                    "hrs": hrs,
                    "rate": rate,
                    "total": total,
                })
                last_item_type = "labor"
                continue
            if stripped.startswith("Note") or stripped.startswith("Misc"):
                last_item_type = "other"
                continue
            if re.match(r"\s*Parts:\s*\$", line) and "Total:" in line:
                m_sum = re.search(r"Parts:\s*\$([\d\.,]+)\s+Labor:\s*\$([\d\.,]+)(?:\s+Tax:\s*\$([\d\.,]+))?\s+Total:\s*\$([\d\.,]+)", line)
                if m_sum:
                    current_job["parts_sum"] = float(m_sum.group(1).replace(",", ""))
                    current_job["labor_sum"] = float(m_sum.group(2).replace(",", ""))
                    current_job["tax_sum"] = float(m_sum.group(3).replace(",", "")) if m_sum.group(3) else 0.0
                    current_job["total_sum"] = float(m_sum.group(4).replace(",", ""))
                last_item_type = "other"
                continue
            if "Estimate Total:" in line:
                break
                
            if not stripped.startswith(("Type", "Qty/Hr", "Sale/Rate", "Subtotal", "Description")):
                if last_item_type == "labor" and current_labours:
                    current_labours[-1]["description"] += " " + stripped
                elif last_item_type == "part" and current_parts:
                    current_parts[-1]["description"] += " " + stripped
                elif last_item_type == "header" and current_job:
                    current_job["title"] += " " + stripped

    if current_job:
        current_job["parts"] = current_parts
        current_job["labour"] = current_labours
        jobs.append(current_job)
    return jobs

def parse_totals(text: str) -> dict:
    totals = {
        "labor": None,
        "parts": None,
        "supplies": 0.0,
        "subtotal": None,
        "tax": None,
        "grand_total": None,
    }
    lines = [l.strip() for l in text.splitlines()]
    for line in lines:
        line_clean = re.sub(r"\s+", " ", line)
        
        m = re.match(r"^Labor\s+\$([\d\.,]+)$", line_clean, re.IGNORECASE)
        if m:
            totals["labor"] = float(m.group(1).replace(",", ""))
            continue
        m = re.match(r"^Parts\s+\$([\d\.,]+)$", line_clean, re.IGNORECASE)
        if m:
            totals["parts"] = float(m.group(1).replace(",", ""))
            continue
        m = re.match(r"^Subtotal\s+\$([\d\.,]+)$", line_clean, re.IGNORECASE)
        if m:
            totals["subtotal"] = float(m.group(1).replace(",", ""))
            continue
        m = re.match(r"^(Taxes|GST/HST|Tax)\s+\$([\d\.,]+)$", line_clean, re.IGNORECASE)
        if m:
            totals["tax"] = float(m.group(2).replace(",", ""))
            continue
        m = re.search(r"(?:Estimate Total|Grand total|Total|Estimate Due):\s*\$([\d\.,]+)", line_clean, re.IGNORECASE)
        if m:
            if not any(k in line_clean for k in ("Parts:", "Labor:", "Tax:")):
                totals["grand_total"] = float(m.group(1).replace(",", ""))
                continue
        
        if not line_clean.startswith(("Misc", "Part", "Labor", "Parts")):
            m = re.match(r"^(?:Misc\s+)?(Recyle/disposal/co|Recyle/disposal/consumables|Shop\s+supplies|Surcharge|Hazmat|Hazardous)\b.*\$([\d\.,]+)$", line_clean, re.IGNORECASE)
            if m:
                totals["supplies"] += float(m.group(2).replace(",", ""))
    return totals

def build_manifest(header: dict, jobs_raw: list, totals_parsed: dict) -> dict:
    jobs = []
    for j in jobs_raw:
        hrs = sum(item.get("hrs", 0.0) for item in j.get("labour", []))
        labour_cost = j.get("labor_sum")
        if labour_cost is None:
            labour_cost = sum(item.get("total", 0.0) for item in j.get("labour", []))
            
        parts_cost = j.get("parts_sum")
        if parts_cost is None:
            parts_cost = sum(item.get("total", 0.0) for item in j.get("parts", []))
            
        part_desc = ""
        if j.get("parts"):
            part_desc = j["parts"][0]["description"]
            if len(j["parts"]) > 1:
                part_desc += f" + {len(j['parts'])-1} more"
        jobs.append({
            "title": j.get("title", "Repair"),
            "labour_hours": hrs,
            "labour_cost": labour_cost,
            "parts_retail_cad": parts_cost,
            "part_desc": part_desc,
            "labour_lines": [
                clean_detail(item.get("description", ""))
                for item in j.get("labour", [])
                if clean_detail(item.get("description", ""))
            ],
            "part_lines": [
                clean_detail(item.get("description", ""))
                for item in j.get("parts", [])
                if clean_detail(item.get("description", ""))
            ],
            "parts": j.get("parts", []),
            "labour": j.get("labour", []),
            "oem_pn": "Mitchell Lookup",
            "supplier": "NAPA Preferred",
            "class_label": "",
            "source_system": "Mitchell 1 PDF parse",
            "source_time": datetime.now().isoformat(),
            "fitment_notes": "",
        })

    has_parts = any(j.get("parts_retail_cad", 0) > 0 for j in jobs)

    if totals_parsed.get("labor") is None:
        totals_parsed["labor"] = sum(j["labour_cost"] for j in jobs)
    if totals_parsed.get("parts") is None:
        totals_parsed["parts"] = sum(j["parts_retail_cad"] for j in jobs)
    if totals_parsed.get("subtotal") is None:
        totals_parsed["subtotal"] = totals_parsed["labor"] + totals_parsed["parts"] + totals_parsed["supplies"]
    if totals_parsed.get("tax") is None:
        totals_parsed["tax"] = round(totals_parsed["subtotal"] * 0.05, 2)
    if totals_parsed.get("grand_total") is None:
        totals_parsed["grand_total"] = totals_parsed["subtotal"] + totals_parsed["tax"]

    return {
        "VIN": header.get("vin", ""),
        "STATUS": "Lookup Required",
        "PARTS_CONFIRMED": has_parts,
        "customer": header.get("customer", {"name": "", "phone": "", "email": ""}),
        "year": header.get("year", ""),
        "make": header.get("make", ""),
        "model": header.get("model", ""),
        "plate": header.get("plate", ""),
        "mileage": header.get("mileage", ""),
        "estimate_date": header.get("estimate_date", ""),
        "estimate_number": header.get("estimate_number", ""),
        "estimate_due": header.get("estimate_due", ""),
        "customer_id": header.get("customer_id", ""),
        "service_advisor": header.get("service_advisor", ""),
        "totals": totals_parsed,
        "jobs": jobs,
    }

def parse_asr_pdf(pdf_path: str) -> dict:
    text = extract_text(pdf_path)
    header = parse_header(text)
    jobs_raw = parse_jobs(text)
    totals_parsed = parse_totals(text)
    manifest = build_manifest(header, jobs_raw, totals_parsed)
    return manifest

document.addEventListener("DOMContentLoaded", () => {
  if (document.body.dataset.page !== "bg-lookup") return;
  initBGCoverage();
});

function initBGCoverage() {
  const form = document.getElementById("bg-lookup-form");
  const output = document.getElementById("bg-output");
  const button = document.getElementById("bg-lookup-button");
  const serviceSelect = document.getElementById("bg-service-select");

  loadBGServices(serviceSelect);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    button.textContent = "Building...";
    try {
      const data = await apiRequest("/api/bg/lookup", {
        method: "POST",
        body: JSON.stringify(formToPayload(form)),
      });
      renderBGCoverageCard(output, data.summary);
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Build Coverage Card";
    }
  });
}

async function loadBGServices(select) {
  try {
    const data = await apiRequest("/api/bg/services");
    const services = data.services || [];
    select.innerHTML = '<option value="">Select BG service...</option>';

    const groups = new Map();
    for (const service of services) {
      const category = service.category || "BG Services";
      if (!groups.has(category)) groups.set(category, []);
      groups.get(category).push(service);
    }

    for (const [category, groupServices] of groups.entries()) {
      const group = document.createElement("optgroup");
      group.label = category;
      for (const service of groupServices) {
        const option = document.createElement("option");
        option.value = service.id;
        option.textContent = service.label || service.name;
        group.appendChild(option);
      }
      select.appendChild(group);
    }
  } catch (error) {
    select.innerHTML = '<option value="">BG services unavailable</option>';
    showToast(error.message);
  }
}

function renderBGCoverageCard(container, summary) {
  const advisor = summary.advisor_summary || {};
  const selected = summary.selected_service || {};
  const plan = summary.likely_plan_tier || {};
  const isExistingCoverage = summary.coverage_basis === "existing";
  const isEligible = selected.status === "eligible" && plan.status === "eligible";
  const coverageAmount = serviceCoverageForPlan(selected, plan);

  container.classList.remove("output-empty");
  container.innerHTML = "";

  const card = document.createElement("div");
  card.className = "bg-summary-card";

  appendKeyValue(card, "Vehicle", vehicleLine(summary.vehicle));
  appendKeyValue(card, "BG Service", serviceLine(selected, summary.selected_service_status));
  appendKeyValue(card, "Coverage Status", coverageStatusLine(selected, plan, isExistingCoverage));
  appendKeyValue(card, "Coverage", coverageLine(selected, coverageAmount, plan, isExistingCoverage));
  if (isEligible) {
    appendKeyValue(card, "Coverage Term / Required Interval", intervalLine(selected));
    appendListBlock(card, "Requirements To Keep Coverage Active", keepCoveredRows(selected, summary, isExistingCoverage));
    if (isExistingCoverage && isOverInitialAgeLimit(plan)) {
      appendListBlock(card, "Advisor Age Flag", existingCoverageAgeFlagRows(plan));
    }
    appendRoadside(card, true, summary.roadside, isExistingCoverage);
  } else {
    appendListBlock(card, "Advisor Next Step", ineligibleAdvisorRows(selected, plan));
  }

  if (selected.advisor_match_note && !isEligible) {
    appendKeyValue(card, "Advisor Review", selected.advisor_match_note);
  } else if (advisor.decision_note) {
    appendKeyValue(card, "Advisor Review", advisor.decision_note);
  }

  appendKeyValue(card, "Customer Wording", compactText(summary.customer_explanation || fallbackCustomerWording(selected, plan)));

  container.appendChild(card);

  appendDetails(container, "Coverage Details", coverageDetailRows(selected, plan, coverageAmount, isEligible));
  appendDetails(container, "Not Covered / Limits", exclusionRows(selected));
  appendDetails(container, "Source Verification", [summary.verification_notice]);
  appendDetails(container, "Technical Rule Log", summary.rule_log || []);
}

function appendKeyValue(container, label, value) {
  const section = document.createElement("section");
  section.className = "bg-main-section";

  const heading = document.createElement("h3");
  heading.textContent = label;
  section.appendChild(heading);

  const paragraph = document.createElement("p");
  paragraph.textContent = textOrDash(value);
  section.appendChild(paragraph);

  container.appendChild(section);
}

function appendListBlock(container, label, values) {
  const cleanValues = cleanList(values);
  const section = document.createElement("section");
  section.className = "bg-main-section";

  const heading = document.createElement("h3");
  heading.textContent = label;
  section.appendChild(heading);

  if (!cleanValues.length) {
    const paragraph = document.createElement("p");
    paragraph.textContent = "-";
    section.appendChild(paragraph);
  } else {
    const list = document.createElement("ul");
    for (const value of cleanValues) {
      const item = document.createElement("li");
      item.textContent = value;
      list.appendChild(item);
    }
    section.appendChild(list);
  }

  container.appendChild(section);
}

function appendRoadside(container, isEligible, roadside, isExistingCoverage = false) {
  const section = document.createElement("section");
  section.className = "bg-roadside-card";

  const heading = document.createElement("h3");
  heading.textContent = "Roadside / Enrollment";
  section.appendChild(heading);

  const list = document.createElement("ul");
  const rows = isEligible
    ? isExistingCoverage
      ? [
          "Verify BG On The Road roadside benefit from the existing enrollment record before presenting it as active.",
          "Verify the BG enrollment card/information is on file.",
          "Keep current service documentation with the repair order.",
        ]
      : [
          "Offer BG On The Road roadside benefit when the qualifying service applies.",
          "Provide the BG enrollment card/information.",
          "Complete or verify enrollment and keep service documentation with the repair order.",
        ]
    : ["Roadside/enrollment should not be presented as active until BG coverage eligibility is verified."];

  for (const row of rows) {
    const item = document.createElement("li");
    item.textContent = row;
    list.appendChild(item);
  }

  for (const reminder of cleanList((roadside && roadside.reminders) || [])) {
    if (rows.includes(reminder)) continue;
    const item = document.createElement("li");
    item.textContent = reminder;
    list.appendChild(item);
  }

  section.appendChild(list);
  container.appendChild(section);
}

function appendDetails(container, title, values) {
  const details = document.createElement("details");
  details.className = "bg-details";

  const summary = document.createElement("summary");
  summary.textContent = title;
  details.appendChild(summary);

  const cleanValues = cleanList(values);
  if (!cleanValues.length) {
    const paragraph = document.createElement("p");
    paragraph.textContent = "-";
    details.appendChild(paragraph);
  } else {
    const list = document.createElement("ul");
    for (const value of cleanValues) {
      const item = document.createElement("li");
      item.textContent = value;
      list.appendChild(item);
    }
    details.appendChild(list);
  }

  container.appendChild(details);
}

function serviceLine(service, serviceStatus) {
  const status = serviceStatus === "performed" ? "performed" : "proposed";
  const name = service.advisor_label || service.service_name || "Service not selected";
  return `${name} (${status})`;
}

function coverageStatusLine(service, plan, isExistingCoverage = false) {
  if (!service.service_id) return "Select a BG service.";
  if (plan.status === "not eligible") return `Not eligible: ${plan.reason || "No matching BG entry rule."}`;
  if (plan.status === "verify") return `Needs BG verification: ${plan.reason || "More vehicle information is needed."}`;
  if (service.status !== "eligible") return `Needs BG verification: ${service.advisor_match_note || service.display_status}`;
  if (isExistingCoverage) return `Existing coverage - verify records: ${plan.reason || "Confirm enrollment, service history, and interval compliance."}`;
  return `${plan.plan_name || "BG plan"}: ${plan.display_status || "eligible"}`;
}

function coverageLine(service, coverageAmount, plan, isExistingCoverage = false) {
  if (plan.status !== "eligible") return "Coverage should not be presented as active for this vehicle based on the current BG rule table.";
  if (service.status !== "eligible") return "Coverage cannot be presented until eligibility is verified.";
  const system = service.covered_system || "covered system";
  const amount = coverageAmount === null || coverageAmount === undefined ? "BG amount requires verification" : `up to ${formatUsd(coverageAmount)}`;
  const percent = plan.coverage_percent ? ` (${plan.coverage_percent}% plan level)` : "";
  const prefix = isExistingCoverage ? "Existing coverage record may show" : system;
  return isExistingCoverage ? `${prefix} ${system}: ${amount}${percent}.` : `${system}: ${amount}${percent}.`;
}

function intervalLine(service) {
  if (!service.interval_km) return "Verify current BG interval requirement.";
  return `Repeat the qualifying BG service every ${formatKm(service.interval_km)} to maintain coverage, subject to BG terms.`;
}

function keepCoveredRows(service, summary, isExistingCoverage = false) {
  const rows = [
    isExistingCoverage
      ? "Verify prior BG enrollment/card or repair-order record."
      : "Complete the selected qualifying BG service using required BG products.",
    "Document the service on the repair order.",
    "Provide/verify BG enrollment information for the customer.",
  ];
  if (isExistingCoverage) rows.push("Confirm service interval compliance before presenting coverage as active.");
  if (service.interval_km) rows.push(`Repeat at the required ${formatKm(service.interval_km)} interval.`);
  if (service.bg_products_required) rows.push(`Required products: ${service.bg_products_required}.`);
  if (summary.enrollment_card_reminder) rows.push(summary.enrollment_card_reminder);
  rows.push("Final coverage is subject to BG terms, conditions, claim approval, and maintenance compliance.");
  return rows;
}

function isOverInitialAgeLimit(plan) {
  return Number(plan.vehicle_age_years || 0) > 20;
}

function existingCoverageAgeFlagRows(plan) {
  return [
    `Vehicle age is ${plan.vehicle_age_years} years. The 20-year rule applies to initial BG enrollment, not verified existing coverage.`,
    "Do not present this as new BG coverage unless BG/dealer records confirm it is already active and interval-compliant.",
    "Verify prior enrollment/card, repair-order history, and mileage interval compliance before customer-facing confirmation.",
  ];
}

function ineligibleAdvisorRows(service, plan) {
  const rows = [
    "Do not present BG protection, roadside, or enrollment as active for this vehicle.",
    "Confirm the vehicle details were entered correctly before discussing eligibility.",
  ];
  if (plan.reason) rows.push(plan.reason);
  if (service.advisor_match_note) rows.push(service.advisor_match_note);
  rows.push("The selected service can still be discussed as maintenance/service value, separate from BG protection coverage.");
  return rows;
}

function coverageDetailRows(service, plan, coverageAmount, isEligible) {
  const rows = [];
  if (plan.reason) rows.push(`${plan.plan_name}: ${plan.reason}`);
  if (!isEligible) {
    if (service.advisor_match_note) rows.push(`Selected service review: ${service.advisor_match_note}`);
    return rows;
  }
  if (service.covered_summary) rows.push(`Covered: ${service.covered_summary}`);
  if (coverageAmount !== null && coverageAmount !== undefined) rows.push(`Selected plan coverage amount: ${formatUsd(coverageAmount)}.`);
  if (service.plan1_max_reimbursement_usd !== null && service.plan1_max_reimbursement_usd !== undefined) {
    rows.push(`Plan 1 max: ${formatUsd(service.plan1_max_reimbursement_usd)}.`);
  }
  if (service.plan2_max_reimbursement_usd !== null && service.plan2_max_reimbursement_usd !== undefined) {
    rows.push(`Plan 2 max: ${formatUsd(service.plan2_max_reimbursement_usd)}.`);
  }
  return rows;
}

function exclusionRows(service) {
  const rows = [];
  if (service.not_covered_summary) rows.push(service.not_covered_summary);
  if (service.advisor_reminder) rows.push(service.advisor_reminder);
  return rows;
}

function serviceCoverageForPlan(service, plan) {
  const planName = plan.plan_name || "";
  if (planName.includes("Plan 1")) return service.plan1_max_reimbursement_usd;
  if (planName.includes("Plan 2")) return service.plan2_max_reimbursement_usd;
  return null;
}

function fallbackCustomerWording(service, plan) {
  if (plan.status !== "eligible" || service.status !== "eligible") {
    return "BG protection should not be presented as active until the vehicle and selected service meet BG eligibility rules.";
  }
  return `The selected BG service may qualify this vehicle for ${plan.plan_name || "BG"} protection when completed, documented, and maintained at the required interval.`;
}

function vehicleLine(vehicle) {
  const name = [vehicle.year, vehicle.make, vehicle.model].filter(Boolean).join(" ") || "Vehicle not entered";
  return `${name}${vehicle.mileage_km ? `, ${formatKm(vehicle.mileage_km)}` : ""}`;
}

function formatKm(value) {
  if (value === null || value === undefined || value === "") return "";
  return `${Number(value).toLocaleString()} km`;
}

function formatUsd(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `$${Number(value).toLocaleString()} USD`;
}

function compactText(value) {
  const text = textOrDash(value);
  if (text === "-" || text === "—") return text;
  return text.split(/\s+/).join(" ");
}

function cleanList(values) {
  return values
    .map((value) => textOrDash(value))
    .filter((value) => value !== "-" && value !== "—");
}

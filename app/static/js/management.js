document.addEventListener("DOMContentLoaded", () => {
  if (document.body.dataset.page !== "management") return;
  initManagementReports();
});

async function initManagementReports() {
  const refreshButton = document.getElementById("refresh-management-button");
  if (refreshButton) {
    refreshButton.addEventListener("click", loadManagementReport);
  }
  await loadManagementReport();
}

async function loadManagementReport() {
  try {
    const report = await apiRequest("/api/management/report");
    renderManagementTotals(report.totals || {}, report.estimate_conversion || {});
    renderReportList("approval-breakdown", report.approval_breakdown || []);
    renderReportList("category-breakdown", report.category_breakdown || []);
    renderReportList("model-run-breakdown", report.model_run_breakdown || []);
    renderReportList("common-missing-fields", report.common_missing_fields || []);
    renderReportList("misses-by-tech", report.misses_by_tech || []);
    renderReportList("clarifier-pack-breakdown", report.clarifier_pack_breakdown || []);
    renderEstimatorStatus(report.estimate_conversion || {});
    renderManagementRecentCases(report.recent_cases || []);
    renderRecentModelRuns(report.recent_model_runs || []);

    let needsPolling = false;
    for (const engine of Object.values(report.estimate_conversion?.model_engines || {})) {
      if (engine.status === "loading") needsPolling = true;
    }
    if (needsPolling) setTimeout(loadManagementReport, 3000);
  } catch (error) {
    showToast(error.message);
  }
}

function renderManagementTotals(totals, estimator) {
  setText("mgmt-cases", totals.cases);
  setText("mgmt-approved", totals.approved);
  setText("mgmt-runs", totals.model_runs);
  setText("mgmt-estimator", estimator.ready ? "Ready" : "Needs setup");
}

function renderReportList(id, rows) {
  const container = document.getElementById(id);
  if (!container) return;
  container.innerHTML = "";
  if (!rows.length) {
    container.appendChild(emptyReportRow("No data yet."));
    return;
  }
  for (const row of rows) {
    const item = document.createElement("div");
    item.className = "report-row";
    const label = document.createElement("span");
    label.textContent = textOrDash(row.label);
    const count = document.createElement("strong");
    count.textContent = textOrDash(row.count);
    item.append(label, count);
    container.appendChild(item);
  }
}

function renderEstimatorStatus(status) {
  const container = document.getElementById("management-estimator-status");
  if (!container) return;
  container.innerHTML = "";
  const checks = status.checks || {};
  for (const [key, ok] of Object.entries(checks)) {
    const row = document.createElement("div");
    row.className = "status-row";
    const label = document.createElement("span");
    label.textContent = key.replaceAll("_", " ");
    const value = document.createElement("strong");
    value.className = ok ? "ok" : "bad";
    value.textContent = ok ? "OK" : "Missing";
    row.append(label, value);
    container.appendChild(row);
  }
  for (const engine of Object.values(status.model_engines || {})) {
    const row = document.createElement("div");
    row.className = "status-row";
    const label = document.createElement("span");
    label.textContent = engine.label || "AI engine";
    const value = document.createElement("strong");
    value.className = engine.online ? "ok" : engine.status === "loading" ? "warn" : "bad";
    value.textContent = engineStatusLabel(engine);
    row.title = `${engine.model || ""} ${engine.provider || ""} ${engine.url || ""} ${engine.detail || ""}`.trim();
    row.append(label, value);
    container.appendChild(row);
  }
  const path = document.createElement("div");
  path.className = "status-path";
  path.textContent = status.root || "";
  container.appendChild(path);
}

function engineStatusLabel(engine) {
  if (engine.online) return "Model ready";
  if (engine.status === "loading") return "Model loading";
  return "Model offline";
}

function renderManagementRecentCases(rows) {
  const container = document.getElementById("management-recent-cases");
  if (!container) return;
  container.innerHTML = "";
  if (!rows.length) {
    container.appendChild(emptyReportRow("No recent translations."));
    return;
  }
  for (const row of rows) {
    const link = document.createElement("a");
    link.className = "case-card";
    link.href = `/cases/${row.id}`;
    const title = document.createElement("strong");
    title.textContent = textOrDash(row.category);
    const note = document.createElement("span");
    note.textContent = textOrDash(row.corrected_translation || row.technician_note_raw);
    const status = document.createElement("span");
    status.textContent = textOrDash(row.approval_status);
    link.append(title, note, status);
    container.appendChild(link);
  }
}

function renderRecentModelRuns(rows) {
  const container = document.getElementById("management-recent-runs");
  if (!container) return;
  container.innerHTML = "";
  if (!rows.length) {
    container.appendChild(emptyReportRow("No model runs yet."));
    return;
  }
  for (const row of rows) {
    const item = document.createElement("div");
    item.className = "report-row tall";
    const label = document.createElement("span");
    label.textContent = `${textOrDash(row.model_name)} - ${textOrDash(row.status)}`;
    const detail = document.createElement("strong");
    detail.textContent = row.duration_ms ? `${row.duration_ms} ms` : textOrDash(row.created_at);
    item.append(label, detail);
    container.appendChild(item);
  }
}

function emptyReportRow(message) {
  const row = document.createElement("div");
  row.className = "report-row";
  const label = document.createElement("span");
  label.textContent = message;
  row.appendChild(label);
  return row;
}

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = textOrDash(value);
}

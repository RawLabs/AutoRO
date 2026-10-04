let managerCode = "";
let managerDigest = null;
let activeManagerReport = null;

document.addEventListener("DOMContentLoaded", () => {
  if (document.body.dataset.page !== "manager") return;
  initManager();
});

function initManager() {
  const form = document.getElementById("manager-code-form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    managerCode = document.getElementById("manager-code").value.trim();
    await loadManagerDigest();
  });

  document.querySelectorAll("[data-manager-tab]").forEach((button) => {
    button.addEventListener("click", () => activateManagerTab(button.dataset.managerTab));
  });
  document.getElementById("manager-import").addEventListener("click", loadManagerDigest);
  document.getElementById("manager-recalc").addEventListener("click", loadManagerDigest);
  document.getElementById("manager-relock").addEventListener("click", relockManager);
  document.getElementById("manager-copy-summary").addEventListener("click", copyManagerSummary);
  document.getElementById("manager-export-json").addEventListener("click", exportManagerJson);
  document.getElementById("manager-report-filter").addEventListener("input", renderActiveManagerReport);
  document.getElementById("manager-ask-form").addEventListener("submit", askManager);
  document.getElementById("manager-copy-answer").addEventListener("click", () => copyText(document.getElementById("manager-answer-output").textContent));
  document.getElementById("manager-export-answer").addEventListener("click", exportManagerAnswer);
  document.querySelectorAll("[data-print-target]").forEach((button) => {
    button.addEventListener("click", () => printElement(button.dataset.printTarget));
  });
  document.querySelectorAll("[data-copy-table]").forEach((button) => {
    button.addEventListener("click", () => copyText(document.getElementById(button.dataset.copyTable).innerText));
  });
}

function relockManager() {
  managerCode = "";
  managerDigest = null;
  activeManagerReport = null;
  const lock = document.getElementById("manager-lock");
  const app = document.getElementById("manager-app");
  const codeInput = document.getElementById("manager-code");
  app.hidden = true;
  lock.hidden = false;
  lock.classList.remove("is-unlocked");
  lock.removeAttribute("aria-hidden");
  if (codeInput) {
    codeInput.value = "";
    codeInput.focus();
  }
}

async function loadManagerDigest() {
  if (!managerCode) {
    showToast("Enter security code");
    return;
  }
  try {
    managerDigest = await fetchJsonWithManagerCode("/api/operations/digest");
    const lock = document.getElementById("manager-lock");
    const app = document.getElementById("manager-app");
    lock.hidden = true;
    lock.classList.add("is-unlocked");
    lock.setAttribute("aria-hidden", "true");
    app.hidden = false;
    renderManagerDigest();
  } catch (error) {
    showToast(error.message);
  }
}

async function fetchJsonWithManagerCode(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Manager-Code": managerCode,
      ...(options.headers || {}),
    },
  });
  let data = {};
  try {
    data = await response.json();
  } catch (_error) {
    data = {};
  }
  if (!response.ok) {
    throw new Error(data.detail || `Request failed with ${response.status}`);
  }
  return data;
}

function renderManagerDigest() {
  if (!managerDigest) return;
  document.getElementById("manager-date-range").textContent = managerDigest.month || "No reports found";
  renderManagerKpis();
  renderManagerAnalytics();
  renderManagerReportList();
}

function renderManagerKpis() {
  const container = document.getElementById("manager-kpi-grid");
  container.innerHTML = "";
  for (const kpi of managerDigest.kpis || []) {
    const card = document.createElement("article");
    card.className = "manager-kpi";
    const label = document.createElement("span");
    label.textContent = kpi.label;
    const value = document.createElement("strong");
    value.textContent = kpi.value;
    const note = document.createElement("small");
    note.textContent = kpi.note || "";
    card.append(label, value, note);
    container.appendChild(card);
  }
}

function renderManagerAnalytics() {
  const container = document.getElementById("manager-analytics");
  container.innerHTML = "";
  renderManagerListPanel(container, "Highlights", managerDigest.highlights || []);
  renderManagerListPanel(container, "Risks To Review", managerDigest.risks || []);
  renderManagerListPanel(container, "Opportunities", managerDigest.opportunities || []);
  const analytics = managerDigest.analytics || {};
  for (const [key, rows] of Object.entries(analytics)) {
    renderManagerTablePanel(container, key.replaceAll("_", " "), rows);
  }
}

function renderManagerListPanel(container, title, items) {
  const panel = document.createElement("article");
  panel.className = "panel";
  const heading = document.createElement("h2");
  heading.textContent = title;
  const list = document.createElement("ul");
  list.className = "manager-bullet-list";
  if (!items.length) {
    const item = document.createElement("li");
    item.textContent = "No items flagged.";
    list.appendChild(item);
  }
  for (const text of items) {
    const item = document.createElement("li");
    item.textContent = text;
    list.appendChild(item);
  }
  panel.append(heading, list);
  container.appendChild(panel);
}

function renderManagerTablePanel(container, title, rows) {
  const panel = document.createElement("article");
  panel.className = "panel stack";
  const heading = document.createElement("h2");
  heading.textContent = title;
  const tableWrap = document.createElement("div");
  tableWrap.className = "table-wrap";
  tableWrap.appendChild(buildObjectTable(rows || []));
  panel.append(heading, tableWrap);
  container.appendChild(panel);
}

function renderManagerReportList() {
  const container = document.getElementById("manager-report-list");
  const reports = managerDigest.reports || [];
  const table = document.createElement("table");
  table.innerHTML = "<thead><tr><th>Report</th><th>Rows</th><th>File</th></tr></thead>";
  const body = document.createElement("tbody");
  for (const report of reports) {
    const row = document.createElement("tr");
    row.innerHTML = `<td><button class="linkish" type="button">${escapeHtml(report.title)}</button></td><td>${report.row_count}</td><td>${escapeHtml(report.filename)}</td>`;
    row.querySelector("button").addEventListener("click", () => showManagerReport(report.key));
    body.appendChild(row);
  }
  table.appendChild(body);
  container.innerHTML = "";
  container.appendChild(table);
}

function showManagerReport(key) {
  activeManagerReport = (managerDigest.reports || []).find((report) => report.key === key);
  document.getElementById("manager-report-detail-panel").hidden = !activeManagerReport;
  renderActiveManagerReport();
}

function renderActiveManagerReport() {
  if (!activeManagerReport) return;
  const filter = document.getElementById("manager-report-filter").value.trim().toLowerCase();
  let rows = activeManagerReport.rows || [];
  if (filter) {
    rows = rows.filter((row) => JSON.stringify(row).toLowerCase().includes(filter));
  }
  document.getElementById("manager-report-title").textContent = activeManagerReport.title;
  document.getElementById("manager-report-count").textContent = `${rows.length} of ${activeManagerReport.row_count} rows`;
  const container = document.getElementById("manager-report-table");
  container.innerHTML = "";
  container.appendChild(buildObjectTable(rows));
}

function buildObjectTable(rows) {
  const table = document.createElement("table");
  if (!rows || !rows.length) {
    table.innerHTML = "<tbody><tr><td>No rows.</td></tr></tbody>";
    return table;
  }
  const headers = Object.keys(rows[0]);
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const header of headers) {
    const th = document.createElement("th");
    th.textContent = header;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  const tbody = document.createElement("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const header of headers) {
      const td = document.createElement("td");
      td.textContent = textOrDash(row[header]);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.append(thead, tbody);
  return table;
}

function activateManagerTab(tab) {
  document.querySelectorAll("[data-manager-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.managerTab === tab);
  });
  document.querySelectorAll("[data-manager-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.managerPanel === tab);
  });
}

async function askManager(event) {
  event.preventDefault();
  const button = document.getElementById("manager-ask-button");
  const formData = new FormData(event.currentTarget);
  button.disabled = true;
  button.textContent = "Reviewing...";
  try {
    const data = await fetchJsonWithManagerCode("/api/operations/ask", {
      method: "POST",
      body: JSON.stringify({ question: String(formData.get("question") || ""), month: managerDigest ? managerDigest.month : "" }),
    });
    document.getElementById("manager-answer-card").hidden = false;
    document.getElementById("manager-answer-output").textContent = data.answer || "";
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Ask Manager";
  }
}

function copyManagerSummary() {
  if (!managerDigest) return;
  const lines = [
    `Month: ${managerDigest.month}`,
    ...(managerDigest.highlights || []),
    ...(managerDigest.risks || []),
    ...(managerDigest.opportunities || []),
  ];
  copyText(lines.join("\n"));
}

function exportManagerJson() {
  if (!managerDigest) return;
  downloadText(`manager-digest-${managerDigest.month || "reports"}.json`, JSON.stringify(managerDigest, null, 2));
}

function exportManagerAnswer() {
  downloadText("manager-answer.txt", document.getElementById("manager-answer-output").textContent || "");
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text || "");
    showToast("Copied");
  } catch (_error) {
    showToast("Could not copy");
  }
}

function downloadText(filename, text) {
  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function printElement(id) {
  const element = document.getElementById(id);
  if (!element) return;
  const popup = window.open("", "_blank");
  popup.document.write(`<pre>${escapeHtml(element.innerText)}</pre>`);
  popup.document.close();
  popup.print();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

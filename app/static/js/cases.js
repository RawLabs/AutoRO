document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;
  if (page === "cases") initCasesPage();
  if (page === "case-detail") initCaseDetailPage();
});

async function initCasesPage() {
  const form = document.getElementById("case-search-form");
  const input = document.getElementById("case-search");
  const container = document.getElementById("case-results");

  async function runSearch() {
    const query = encodeURIComponent(input.value.trim());
    const data = await apiRequest(`/api/cases?limit=100${query ? `&search=${query}` : ""}`);
    renderCaseList(container, data.cases, true);
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await runSearch();
    } catch (error) {
      showToast(error.message);
    }
  });

  try {
    await runSearch();
  } catch (error) {
    showToast(error.message);
  }
}

function renderCaseList(container, cases, wide = false) {
  container.innerHTML = "";
  if (!cases || cases.length === 0) {
    const empty = document.createElement("div");
    empty.className = "output-empty";
    empty.textContent = "No cases saved.";
    container.appendChild(empty);
    return;
  }

  for (const item of cases) {
    const card = document.createElement("a");
    card.className = "case-card";
    card.href = `/cases/${item.id}`;

    const title = document.createElement("strong");
    title.textContent = `#${item.id} - ${formatCategory(item.category) || "Uncategorized"}`;
    card.appendChild(title);

    const note = document.createElement("span");
    note.textContent =
      item.technician_note_raw ||
      item.technician_note ||
      item.raw_customer_complaint ||
      "No technician note";
    card.appendChild(note);

    const meta = document.createElement("span");
    meta.textContent = wide
      ? `${formatApprovalStatus(item.approval_status || item.status)} - ${item.date_created}`
      : item.date_created;
    card.appendChild(meta);

    container.appendChild(card);
  }
}

async function initCaseDetailPage() {
  const caseId = document.querySelector("[data-case-id]").dataset.caseId;
  const data = await apiRequest(`/api/cases/${caseId}`);
  const caseData = data.case;

  renderCaseSummary(caseData);
  const corrected = Object.keys(caseData.corrected_output || {}).length
    ? caseData.corrected_output
    : caseData.normalized_output;
  const modelExplanation =
    caseData.model_translation ||
    (caseData.normalized_output || {}).customer_explanation ||
    "";
  const correctedExplanation =
    caseData.corrected_translation ||
    corrected.customer_explanation ||
    modelExplanation;
  document.getElementById("case-model-translation").value = modelExplanation;
  document.getElementById("case-corrected-translation").value = correctedExplanation;
  document.getElementById("case-notes").value = caseData.notes || "";

  document.getElementById("save-case-notes").addEventListener("click", async () => {
    try {
      await apiRequest(`/api/cases/${caseId}`, {
        method: "PATCH",
        body: JSON.stringify({
          notes: document.getElementById("case-notes").value.trim(),
        }),
      });
      showToast("Case notes saved");
    } catch (error) {
      showToast(error.message);
    }
  });

  document.getElementById("approve-case-translation").addEventListener("click", async () => {
    await saveCaseTranslation("approved", document.getElementById("approve-case-translation"), "Approved as training example");
  });

  document.getElementById("logged-only-case").addEventListener("click", async () => {
    await saveCaseTranslation("logged_only", document.getElementById("logged-only-case"), "Kept as logged-only translation");
  });

  async function saveCaseTranslation(approvalStatus, button, successMessage) {
    const finalText = document.getElementById("case-corrected-translation").value.trim();
    button.disabled = true;
    try {
      await apiRequest(`/api/cases/${caseId}/corrections`, {
        method: "POST",
        body: JSON.stringify({
          after_output: { customer_explanation: finalText },
          status: approvalStatus,
        }),
      });
      showToast(successMessage);
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
    }
  }
}

function renderCaseSummary(caseData) {
  const summary = document.getElementById("case-summary");
  const rows = [
    ["Category", formatCategory(caseData.category)],
    ["Technician note", caseData.technician_note_raw || caseData.technician_note || caseData.raw_customer_complaint],
    ["Model", caseData.model_name],
    ["Created", caseData.date_created],
  ];

  summary.innerHTML = "";
  for (const [label, value] of rows) {
    const row = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = textOrDash(value);
    row.appendChild(dt);
    row.appendChild(dd);
    summary.appendChild(row);
  }
}

function formatApprovalStatus(status) {
  if (status === "approved") return "approved training example";
  if (status === "rejected") return "rejected";
  return "logged only";
}

function formatCategory(category) {
  if (!category) return "";
  return category.replace("_", " ");
}

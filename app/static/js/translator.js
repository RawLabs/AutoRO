let activeCaseId = null;
let activeNoteQuality = null;

document.addEventListener("DOMContentLoaded", () => {
  if (document.body.dataset.page !== "translator") return;
  initTranslator();
});

function initTranslator() {
  loadTranslatorStatus();
  const form = document.getElementById("translator-form");
  const modelTranslation = document.getElementById("model-translation");
  const correctedTranslation = document.getElementById("corrected-translation");
  const copyButton = document.getElementById("copy-corrected-button");
  const approveButton = document.getElementById("approve-translation-button");
  const loggedOnlyButton = document.getElementById("logged-only-button");
  const noteField = form.querySelector("[name='technician_note']");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = document.getElementById("translate-button");
    button.disabled = true;
    button.textContent = "Checking...";

    try {
      const payload = formToPayload(form);
      payload.qualifier_answers = {};
      const shouldContinue = await confirmMissingDetails(payload, button);
      if (!shouldContinue) return;
      await runTranslation(payload, button, modelTranslation, correctedTranslation);
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Translate";
    }
  });

  approveButton.addEventListener("click", async () => {
    await saveTranslation("approved", approveButton, "Approved as training example");
  });

  loggedOnlyButton.addEventListener("click", async () => {
    await saveTranslation("logged_only", loggedOnlyButton, "Kept as logged-only translation");
  });

  copyButton.addEventListener("click", async () => {
    const text = correctedTranslation.value.trim();
    if (!text) {
      showToast("Nothing to copy");
      return;
    }

    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        correctedTranslation.focus();
        correctedTranslation.select();
        document.execCommand("copy");
        correctedTranslation.setSelectionRange(text.length, text.length);
      }
      showToast("Copied to clipboard");
    } catch (_error) {
      showToast("Could not copy text");
    }
  });

  async function saveTranslation(approvalStatus, button, successMessage) {
    if (!activeCaseId) return;
    button.disabled = true;
    try {
      await apiRequest(`/api/cases/${activeCaseId}/corrections`, {
        method: "POST",
        body: JSON.stringify({
          after_output: {
            customer_explanation: correctedTranslation.value.trim(),
          },
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

  noteField.focus();
}

async function loadTranslatorStatus() {
  try {
    const status = await apiRequest("/api/estimate-conversion/status");
    const translatorEngine = (status.model_engines || {}).translator;
    const pill = document.getElementById("status-translator");
    if (!pill) return;
    
    if (translatorEngine && translatorEngine.online) {
      pill.textContent = "Online";
      pill.dataset.state = "online";
    } else if (translatorEngine && translatorEngine.status === "loading") {
      pill.textContent = "Loading";
      pill.dataset.state = "loading";
      setTimeout(loadTranslatorStatus, 3000);
    } else {
      pill.textContent = "Offline";
      pill.dataset.state = "offline";
    }
    pill.className = "status-pill";
  } catch (error) {
    console.error("Failed to load translator status:", error);
  }
}

async function confirmMissingDetails(payload, translateButton) {
  if (!payload.technician_note) {
    throw new Error("Enter a technician note.");
  }

  while (true) {
    activeNoteQuality = await apiRequest("/api/note-quality", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    if (!activeNoteQuality || !activeNoteQuality.has_guidance) {
      return true;
    }

    translateButton.disabled = false;
    translateButton.textContent = "Translate";
    const decision = await showMissingInfoPrompt(activeNoteQuality);
    translateButton.disabled = true;
    translateButton.textContent = "Translating...";

    if (decision.action === "cancel") return false;

    payload.qualifier_answers = {
      __nudge_action: decision.action,
      __nudge_pack: activeNoteQuality.pack || "",
      __nudge_missing_fields: (activeNoteQuality.missing_fields || []).join(","),
      __nudge_added_text: decision.appendText || "",
    };

    if (decision.action === "fixed" && decision.appendText) {
      payload.technician_note = appendDetail(payload.technician_note, decision.appendText);
      const noteField = document.querySelector("#translator-form [name='technician_note']");
      if (noteField) noteField.value = payload.technician_note;
      // Loop around to check note-quality again
    } else {
      // Skipped or other action, break loop and proceed
      return true;
    }
  }
}

async function runTranslation(payload, button, modelTranslation, correctedTranslation) {
  button.textContent = "Translating...";
  modelTranslation.value = "Translating technician notes... 🔧";
  correctedTranslation.value = "Translating technician notes... 🔧";
  
  const startTime = Date.now();
  try {
    const data = await apiRequest("/api/translate", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    activeCaseId = data.case_id;
    activeNoteQuality = data.note_quality || activeNoteQuality;
    const explanation = data.output.customer_explanation || "";
    modelTranslation.value = explanation;
    correctedTranslation.value = explanation;
    
    const durationMs = Date.now() - startTime;
    const pill = document.getElementById("status-translator");
    if (pill) {
      pill.textContent = `Done (${(durationMs / 1000).toFixed(1)}s)`;
      pill.dataset.state = "done";
    }
  } catch (error) {
    modelTranslation.value = "Translation failed.";
    correctedTranslation.value = "";
    const pill = document.getElementById("status-translator");
    if (pill) {
      pill.textContent = "Error";
      pill.dataset.state = "error";
    }
    throw error;
  }
}

function showMissingInfoPrompt(noteQuality) {
  return new Promise((resolve) => {
    const dialog = document.getElementById("missing-info-dialog");
    const title = document.getElementById("missing-info-title");
    const text = document.getElementById("missing-info-text");
    const chips = document.getElementById("missing-info-options");
    const custom = document.getElementById("missing-info-custom");
    const customButton = document.getElementById("missing-info-add");
    const skipButton = document.getElementById("missing-info-skip");
    const cancelButton = document.getElementById("missing-info-cancel");
    if (!dialog || !title || !text || !chips || !custom || !customButton || !skipButton || !cancelButton) {
      resolve({ action: "skipped" });
      return;
    }

    let settled = false;
    const finish = (decision) => {
      if (settled) return;
      settled = true;
      dialog.hidden = true;
      dialog.removeEventListener("keydown", onKeydown);
      resolve(decision);
    };
    const onKeydown = (event) => {
      if (event.key === "Escape") finish({ action: "cancel" });
    };

    title.textContent = `${noteQuality.label}: detail missing`;
    text.textContent = noteQuality.message || "Confirm the missing detail before translating, or translate anyway if unknown.";
    chips.innerHTML = "";
    custom.value = "";

    for (const option of noteQuality.quick_options || []) {
      const button = document.createElement("button");
      button.className = "missing-info-chip";
      button.type = "button";
      button.textContent = option.label;
      button.addEventListener("click", () => {
        const current = custom.value.trim();
        const append = option.append_text || option.label;
        custom.value = current ? current + ", " + append : append;
        custom.focus();
      });
      chips.appendChild(button);
    }

    customButton.onclick = () => {
      const detail = custom.value.trim();
      if (!detail) {
        custom.focus();
        return;
      }
      finish({ action: "fixed", appendText: detail });
    };
    custom.onkeydown = (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        customButton.click();
      }
    };
    skipButton.onclick = () => finish({ action: "skipped" });
    cancelButton.onclick = () => finish({ action: "cancel" });

    dialog.hidden = false;
    dialog.addEventListener("keydown", onKeydown);
    const firstChip = chips.querySelector("button");
    if (firstChip) firstChip.focus();
    else custom.focus();
  });
}

function appendDetail(note, detail) {
  const cleanNote = String(note || "").trim();
  const cleanDetail = String(detail || "").trim();
  if (!cleanDetail) return cleanNote;
  if (!cleanNote) return cleanDetail;
  return `${cleanNote}; confirmed ${cleanDetail}`;
}

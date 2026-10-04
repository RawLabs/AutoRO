let advisorQueueProcessing = false;
let advisorPollTimer = null;
const advisorSaveTimers = new Map();

document.addEventListener("DOMContentLoaded", () => {
  if (document.body.dataset.page !== "advisor-queue") return;
  initAdvisorQueue();
  initIntakeGuide();
});

async function initAdvisorQueue() {
  const form = document.getElementById("advisor-queue-form");
  const input = document.getElementById("advisor-queue-input");
  const clearButton = document.getElementById("advisor-clear-button");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) {
      showToast("Enter one advisor line");
      input.focus();
      return;
    }
    await addAdvisorQueueItem(text);
    input.value = "";
    input.focus();
    processAdvisorQueue();
  });

  input.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  clearButton.addEventListener("click", clearAdvisorQueueItems);

  const items = await loadAdvisorQueueItems();
  input.focus();

  const hasPending = items.some(item => item.status === "waiting" || item.status === "translating");
  if (hasPending) {
    processAdvisorQueue();
  }
}

async function addAdvisorQueueItem(rawText) {
  try {
    await apiRequest("/api/advisor-queue/items", {
      method: "POST",
      body: JSON.stringify({ raw_text: rawText }),
    });
    await loadAdvisorQueueItems();
  } catch (error) {
    showToast(error.message);
  }
}

async function loadAdvisorQueueItems() {
  const list = document.getElementById("advisor-queue-list");
  if (!list) return [];
  try {
    const data = await apiRequest("/api/advisor-queue/items");
    renderAdvisorQueueItems(data.items || []);
    return data.items || [];
  } catch (error) {
    showToast(error.message);
    return [];
  }
}

function renderAdvisorQueueItems(items) {
  const list = document.getElementById("advisor-queue-list");
  list.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "output-empty advisor-empty";
    empty.textContent = "No advisor lines queued yet.";
    list.appendChild(empty);
    return;
  }

  for (const item of items) {
    list.appendChild(renderAdvisorQueueItem(item));
  }
}

function renderAdvisorQueueItem(item) {
  const card = document.createElement("article");
  card.className = `advisor-queue-item status-${item.status || "waiting"}`;
  card.dataset.itemId = item.id;

  const head = document.createElement("div");
  head.className = "advisor-queue-head";
  const id = document.createElement("strong");
  id.textContent = `#${item.id}`;
  const status = document.createElement("span");
  status.className = "advisor-status-pill";
  if (item.status === "done" && item.duration_ms) {
    status.textContent = `${statusLabel(item.status)} (${(item.duration_ms / 1000).toFixed(1)}s)`;
  } else {
    status.textContent = statusLabel(item.status);
  }
  head.append(id, status);

  const raw = document.createElement("p");
  raw.className = "advisor-raw-line";
  raw.textContent = item.raw_text || "";

  card.append(head, raw);

  let translatedEditor = null;
  if (item.translated_text) {
    translatedEditor = document.createElement("textarea");
    translatedEditor.className = "advisor-translated-line advisor-translated-editor";
    translatedEditor.rows = 3;
    translatedEditor.value = item.translated_text;
    translatedEditor.addEventListener("input", () => {
      translatedEditor.dataset.dirty = translatedEditor.value === item.translated_text ? "" : "true";
      scheduleAdvisorTranslationSave(item, translatedEditor);
    });
    translatedEditor.addEventListener("blur", () => saveAdvisorTranslation(item, translatedEditor, { quiet: true }));
    card.appendChild(translatedEditor);
  }

  if (item.error) {
    const error = document.createElement("p");
    error.className = "advisor-error-line";
    error.textContent = item.error;
    card.appendChild(error);
  }

  const actions = document.createElement("div");
  actions.className = "button-row advisor-item-actions";
  if (item.status === "done" && item.translated_text) {
    const copy = document.createElement("button");
    copy.className = "secondary-button compact-button";
    copy.type = "button";
    copy.textContent = item.copied_at ? "Copied" : "Copy";
    copy.addEventListener("click", () => copyAdvisorItem(item, translatedEditor));
    actions.appendChild(copy);
  }
  if (item.status === "failed") {
    const retry = document.createElement("button");
    retry.className = "secondary-button compact-button";
    retry.type = "button";
    retry.textContent = "Retry";
    retry.addEventListener("click", () => retryAdvisorItem(item.id));
    actions.appendChild(retry);
  }
  if (actions.children.length) card.appendChild(actions);

  return card;
}

function statusLabel(status) {
  if (status === "done") return "Done";
  if (status === "translating") return "Translating";
  if (status === "failed") return "Failed";
  return "Waiting";
}

async function processAdvisorQueue() {
  if (advisorQueueProcessing) return;
  advisorQueueProcessing = true;

  try {
    await apiRequest("/api/advisor-queue/process-next", {
      method: "POST",
      body: JSON.stringify({}),
    });
    startAdvisorPolling();
  } catch (error) {
    showToast(error.message);
    advisorQueueProcessing = false;
  }
}

function startAdvisorPolling() {
  window.clearTimeout(advisorPollTimer);
  const poll = async () => {
    const items = await loadAdvisorQueueItems();
    
    let isProcessing = false;
    for (const item of items) {
      if (item.status === 'waiting' || item.status === 'translating') {
         isProcessing = true;
         break;
      }
    }
    
    if (isProcessing) {
       advisorPollTimer = window.setTimeout(poll, 1500);
    } else {
       advisorQueueProcessing = false;
    }
  };
  advisorPollTimer = window.setTimeout(poll, 1000);
}

async function clearAdvisorQueueItems() {
  if (advisorQueueProcessing) return;
  try {
    const data = await apiRequest("/api/advisor-queue/clear", {
      method: "POST",
      body: JSON.stringify({}),
    });
    showToast(data.deleted ? `Cleared ${data.deleted} line${data.deleted === 1 ? "" : "s"}` : "No lines to clear");
    await loadAdvisorQueueItems();
  } catch (error) {
    showToast(error.message);
  }
}

async function retryAdvisorItem(itemId) {
  try {
    await apiRequest(`/api/advisor-queue/items/${itemId}/retry`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    await loadAdvisorQueueItems();
    await processAdvisorQueue();
  } catch (error) {
    showToast(error.message);
  }
}

function scheduleAdvisorTranslationSave(item, editor) {
  window.clearTimeout(advisorSaveTimers.get(item.id));
  const timer = window.setTimeout(() => {
    saveAdvisorTranslation(item, editor, { quiet: true });
  }, 900);
  advisorSaveTimers.set(item.id, timer);
}

async function saveAdvisorTranslation(item, editor, options = {}) {
  const text = String(editor?.value || "").trim();
  if (!text) {
    if (!options.quiet) showToast("Translated text is required");
    editor?.focus();
    return false;
  }
  if (text === item.translated_text && editor?.dataset.dirty !== "true") return true;

  try {
    const data = await apiRequest(`/api/advisor-queue/items/${item.id}/translation`, {
      method: "POST",
      body: JSON.stringify({ translated_text: text }),
    });
    item.translated_text = data.item?.translated_text || text;
    if (editor) editor.dataset.dirty = "";
    if (!options.quiet) showToast("Saved");
    return true;
  } catch (error) {
    showToast(error.message);
    return false;
  }
}

async function copyAdvisorItem(item, editor = null) {
  if (editor?.dataset.dirty === "true") {
    const saved = await saveAdvisorTranslation(item, editor, { quiet: true });
    if (!saved) return;
  }
  const text = String(editor?.value || item.translated_text || "").trim();
  if (!text) return;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    await apiRequest(`/api/advisor-queue/items/${item.id}/copied`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    showToast("Copied");
    await loadAdvisorQueueItems();
  } catch (_error) {
    showToast("Could not copy");
  }
}


let activeIntakeQuality = null;
let activeIntakePayload = {
  raw_text: "",
  qualifier_answers: {}
};

function initIntakeGuide() {
  const form = document.getElementById("intake-guide-form");
  const rawInput = document.getElementById("intake-raw-input");
  const checkButton = document.getElementById("intake-check-button");
  
  const feedback = document.getElementById("intake-guide-feedback");
  const title = document.getElementById("intake-guide-title");
  const message = document.getElementById("intake-guide-message");
  const chipsContainer = document.getElementById("intake-chips-container");
  const customInput = document.getElementById("intake-custom-input");
  const customAddBtn = document.getElementById("intake-custom-add");
  const translateAnywayBtn = document.getElementById("intake-translate-anyway");
  const resetBtn = document.getElementById("intake-reset");
  
  const resultPanel = document.getElementById("intake-result-panel");
  const resultText = document.getElementById("intake-result-text");
  const queueButton = document.getElementById("intake-queue-button");

  if (!form || !rawInput) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = rawInput.value.trim();
    if (!text) {
      showToast("Enter a customer concern first");
      rawInput.focus();
      return;
    }

    checkButton.disabled = true;
    checkButton.textContent = "Checking...";
    
    try {
      activeIntakePayload.raw_text = text;
      activeIntakePayload.qualifier_answers = {};
      
      const res = await apiRequest("/api/intake/analyze", {
        method: "POST",
        body: JSON.stringify(activeIntakePayload)
      });
      
      activeIntakeQuality = res;
      if (res.has_guidance) {
        // Show interactive clarification panel
        title.textContent = res.label || "Clarification Needed";
        message.textContent = res.message || "Please select or type extra details.";
        chipsContainer.innerHTML = "";
        customInput.value = "";
        
        for (const opt of res.quick_options || []) {
          const chip = document.createElement("button");
          chip.className = "missing-info-chip";
          chip.type = "button";
          chip.textContent = opt.label;
          chip.addEventListener("click", () => {
            const current = customInput.value.trim();
            const append = opt.append_text || opt.label;
            customInput.value = current ? current + ", " + append : append;
            customInput.focus();
          });
          chipsContainer.appendChild(chip);
        }
        
        feedback.hidden = false;
        resultPanel.hidden = true;
        
        const firstChip = chipsContainer.querySelector("button");
        if (firstChip) firstChip.focus();
        else customInput.focus();
      } else {
        // No missing details needed, translate immediately
        await runIntakeTranslation();
      }
    } catch (err) {
      showToast(err.message);
    } finally {
      checkButton.disabled = false;
      checkButton.textContent = "Check & Format";
    }
  });

  const handleClarificationSubmit = async () => {
    const detail = customInput.value.trim();
    if (detail) {
      activeIntakePayload.raw_text = appendIntakeDetail(activeIntakePayload.raw_text, detail);
      rawInput.value = activeIntakePayload.raw_text;
    }
    await runIntakeTranslation();
  };

  customAddBtn.addEventListener("click", handleClarificationSubmit);
  customInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleClarificationSubmit();
    }
  });

  translateAnywayBtn.addEventListener("click", async () => {
    await runIntakeTranslation();
  });

  resetBtn.addEventListener("click", () => {
    resetIntake();
  });

  queueButton.addEventListener("click", async () => {
    const text = resultText.value.trim();
    if (!text) {
      showToast("Nothing to queue");
      return;
    }
    queueButton.disabled = true;
    queueButton.textContent = "Sending...";
    try {
      await addAdvisorQueueItem(text);
      showToast("Added concern to queue");
      resetIntake();
      processAdvisorQueue();
    } catch (err) {
      showToast(err.message);
    } finally {
      queueButton.disabled = false;
      queueButton.textContent = "Send to Queue";
    }
  });

  async function runIntakeTranslation() {
    feedback.hidden = true;
    resultPanel.hidden = false;
    resultText.value = "Formatting customer concern... 🔧";
    
    try {
      const res = await apiRequest("/api/intake/translate", {
        method: "POST",
        body: JSON.stringify(activeIntakePayload)
      });
      resultText.value = res.translated_text || "";
    } catch (err) {
      showToast(err.message);
      resultText.value = "Formatting failed.";
    }
  }

  function resetIntake() {
    rawInput.value = "";
    customInput.value = "";
    feedback.hidden = true;
    resultPanel.hidden = true;
    activeIntakeQuality = null;
    activeIntakePayload = {
      raw_text: "",
      qualifier_answers: {}
    };
    rawInput.focus();
  }
}

function appendIntakeDetail(note, detail) {
  const cleanNote = String(note || "").trim();
  const cleanDetail = String(detail || "").trim();
  if (!cleanDetail) return cleanNote;
  if (!cleanNote) return cleanDetail;
  const connector = /[,.;]$/.test(cleanNote) ? " " : ", ";
  return `${cleanNote}${connector}specifically: ${cleanDetail}`;
}


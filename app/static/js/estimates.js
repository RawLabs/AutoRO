document.addEventListener("DOMContentLoaded", () => {
  if (document.body.dataset.page !== "estimate-conversion") return;
  initEstimateConversion();
});

async function initEstimateConversion() {
  loadEstimateConversionStatus();
  const form = document.getElementById("estimate-conversion-form");
  const fileInput = document.getElementById("estimate-file-input");
  const dropZone = document.getElementById("estimate-drop-zone");
  let selectedFile = null;

  // Toggle Mode UI logic
  const modePre = document.getElementById("mode-preestimate");
  const modeQuote = document.getElementById("mode-quote");
  const modeProp = document.getElementById("mode-proposal");
  const inshopContainer = document.getElementById("inshop-input-container");
  const estimatePreview = document.getElementById("estimate-preview");
  const primaryNotesLabel = document.getElementById("estimate-primary-notes-label");
  const secondaryNotesLabel = document.getElementById("estimate-secondary-notes-label");

  function updateModeUI() {
    const usesNotes = (modeQuote && modeQuote.checked) || (modeProp && modeProp.checked);
    if (primaryNotesLabel) primaryNotesLabel.textContent = modeProp && modeProp.checked
      ? "Custom Build Goal / Customer Vision"
      : "Customer Complaint / Reason for visit";
    if (secondaryNotesLabel) secondaryNotesLabel.textContent = modeProp && modeProp.checked
      ? "Build Notes / Intended Use"
      : "Technician Findings / Story";
    if (usesNotes) {
      const iframe = estimatePreview.querySelector("iframe");
      const hasInShopIframe = iframe !== null && iframe.src.indexOf("/inshop/") !== -1;
      if (!hasInShopIframe) {
        estimatePreview.style.display = "none";
        inshopContainer.style.display = "flex";
      } else {
        estimatePreview.style.display = "flex";
        inshopContainer.style.display = "none";
      }
    } else {
      estimatePreview.style.display = "flex";
      inshopContainer.style.display = "none";
    }
  }

  [modePre, modeQuote, modeProp].forEach(el => {
    if (el) {
      el.addEventListener("change", () => {
        resetPreviewAndInputs();
        updateModeUI();
      });
    }
  });
  updateModeUI();

  function resetPreviewAndInputs() {
    const button = document.getElementById("estimate-run-button");
    if (button) {
      button.disabled = false;
      button.textContent = "Build PDF";
      button.style.opacity = "";
      button.style.cursor = "";
    }

    const pill = document.getElementById("status-estimate");
    if (pill) {
      pill.textContent = "Ready";
      pill.dataset.state = "online";
    }

    if (estimatePreview) {
      estimatePreview.innerHTML = "No PDF built yet.";
      estimatePreview.className = "output-empty pdf-preview-empty";
    }

    const openLink = document.getElementById("open-pdf-link");
    const downloadLink = document.getElementById("download-pdf-link");
    if (openLink) openLink.style.display = "none";
    if (downloadLink) downloadLink.style.display = "none";

    if ((modeQuote && modeQuote.checked) || (modeProp && modeProp.checked)) {
      if (estimatePreview) estimatePreview.style.display = "none";
      if (inshopContainer) {
        inshopContainer.style.display = "flex";
        const compInput = document.getElementById("inshop-customer-complaint");
        const techInput = document.getElementById("inshop-tech-findings");
        if (compInput) compInput.value = "";
        if (techInput) techInput.value = "";
      }
    } else {
      if (estimatePreview) estimatePreview.style.display = "flex";
      if (inshopContainer) inshopContainer.style.display = "none";
    }
  }

  if (fileInput) {
    fileInput.addEventListener("change", () => {
      selectedFile = fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;
      updateDropZone(dropZone, selectedFile);
      resetPreviewAndInputs();
    });
  }

  if (dropZone) {
    dropZone.addEventListener("dragover", (event) => {
      event.preventDefault();
      dropZone.classList.add("dragging");
    });
    dropZone.addEventListener("dragleave", () => {
      dropZone.classList.remove("dragging");
    });
    dropZone.addEventListener("drop", (event) => {
      event.preventDefault();
      dropZone.classList.remove("dragging");
      const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
      if (!file) return;
      selectedFile = file;
      if (fileInput) {
        const transfer = new DataTransfer();
        transfer.items.add(file);
        fileInput.files = transfer.files;
      }
      updateDropZone(dropZone, selectedFile);
      resetPreviewAndInputs();
    });
  }

  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = document.getElementById("estimate-run-button");
    button.disabled = true;
    button.textContent = "Building...";
    let shouldReEnable = true;
    try {
      const payload = formToPayload(form);
      delete payload[""];
      
      // In-shop estimate workflow
      if (payload.mode === "quote" || payload.mode === "proposal") {
        if (!selectedFile) {
          throw new Error("Select an ASR PDF estimate.");
        }
        
        const startTime = Date.now();
        
        button.textContent = "Uploading...";
        const upload = await uploadInShopEstimatePdf(selectedFile);
        const estimateId = upload.estimate_id;
        
        const complaint = document.getElementById("inshop-customer-complaint").value.trim();
        const findings = document.getElementById("inshop-tech-findings").value.trim();
        const isCustomBuild = payload.mode === "proposal";
        if (!complaint && !findings) {
          throw new Error(isCustomBuild
            ? "Enter the customer's custom-build goal or intended use."
            : "Enter a customer concern or technician findings for an in-shop estimate.");
        }
        const rawText = complaint + "\n--------\n" + findings;
        
        button.textContent = "Analyzing...";
        const analyzeResp = await fetch(`/api/inshop/estimate/${estimateId}/analyze`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            raw_text: rawText,
            document_type: isCustomBuild ? "custom_build" : "inshop",
          }),
        });
        if (!analyzeResp.ok) {
          const err = await analyzeResp.json().catch(() => ({}));
          throw new Error(err.detail || "Analysis matching failed");
        }
        
        button.textContent = "Building PDF...";
        const genResp = await fetch(`/api/inshop/estimate/${estimateId}/generate-pdf`, {
          method: "POST"
        });
        if (!genResp.ok) {
          const err = await genResp.json().catch(() => ({}));
          throw new Error(err.detail || "PDF generation failed");
        }
        const generated = await genResp.json();
        
        const durationMs = Date.now() - startTime;
        const pill = document.getElementById("status-estimate");
        if (pill) {
          pill.textContent = `Done (${(durationMs / 1000).toFixed(1)}s)`;
          pill.dataset.state = "done";
        }
        
        // Hide inputs and display PDF preview
        inshopContainer.style.display = "none";
        renderEstimatePreview({
          pdf: `/api/inshop/estimate/${estimateId}/pdf`,
          filename: pdfFilename(generated.pdf_path),
        });
        
        shouldReEnable = false;
        button.disabled = true;
        button.style.opacity = "0.4";
        button.style.cursor = "not-allowed";
        return;
      }

      if (selectedFile) {
        button.textContent = "Uploading...";
        const upload = await uploadEstimatePdf(selectedFile);
        payload.input_pdf = upload.path;
        payload.delete_after_run = true;
        const pathInput = form.querySelector('input[name="input_pdf"]');
        if (pathInput) pathInput.value = upload.path;
      }
      button.textContent = "Checking...";
      const preflight = await apiRequest("/api/estimate-conversion/preflight", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if ((preflight.findings || []).length) {
        const approved = confirm(sanityReviewMessage(preflight));
        if (!approved) {
          renderEstimatePreflight(preflight, "Build cancelled. Fix the estimate, then run again.");
          return;
        }
        payload.sanity_confirmed = true;
      }
      button.textContent = "Building...";
      const startTime = Date.now();
      const data = await apiRequest("/api/estimate-conversion/run", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const durationMs = Date.now() - startTime;
      const pill = document.getElementById("status-estimate");
      if (pill) {
        pill.textContent = `Done (${(durationMs / 1000).toFixed(1)}s)`;
        pill.dataset.state = "done";
      }
      renderEstimateOutput(data);
      
      shouldReEnable = false;
      button.disabled = true;
      button.style.opacity = "0.4";
      button.style.cursor = "not-allowed";
    } catch (error) {
      const pill = document.getElementById("status-estimate");
      if (pill) {
        pill.textContent = "Error";
        pill.dataset.state = "error";
      }
      showToast(error.message);
    } finally {
      if (shouldReEnable) {
        button.disabled = false;
        button.textContent = "Build PDF";
        button.style.opacity = "";
        button.style.cursor = "";
      } else {
        button.textContent = "Build PDF";
      }
    }
  });
}

async function uploadEstimatePdf(file) {
  if (file.type && file.type !== "application/pdf") {
    throw new Error("Select a PDF estimate.");
  }
  const response = await fetch(`/api/estimate-conversion/upload?filename=${encodeURIComponent(file.name || "estimate.pdf")}`, {
    method: "POST",
    headers: {"Content-Type": "application/pdf"},
    body: await file.arrayBuffer(),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Upload failed with ${response.status}`);
  }
  return data;
}

function updateDropZone(dropZone, file) {
  if (!dropZone) return;
  if (!file) {
    dropZone.innerHTML = "<strong>Drop estimate PDF here</strong><span>or use the file picker above</span>";
    return;
  }
  dropZone.innerHTML = "";
  const name = document.createElement("strong");
  name.textContent = file.name || "Selected PDF";
  const size = document.createElement("span");
  size.textContent = `${Math.round((file.size || 0) / 1024).toLocaleString()} KB ready to upload`;
  dropZone.append(name, size);
}

async function loadEstimateConversionStatus() {
  try {
    const status = await apiRequest("/api/estimate-conversion/status");
    renderEstimateStatus(status);
    let needsPolling = false;
    let isOnline = false;
    for (const engine of Object.values(status.model_engines || {})) {
      if (engine.status === "loading") needsPolling = true;
      if (engine.online) isOnline = true;
    }
    
    const pill = document.getElementById("status-estimate");
    if (pill) {
      if (isOnline) {
        pill.textContent = "Online";
        pill.dataset.state = "online";
      } else if (needsPolling) {
        pill.textContent = "Loading";
        pill.dataset.state = "loading";
      } else {
        pill.textContent = "Offline";
        pill.dataset.state = "offline";
      }
    }
    
    if (needsPolling) setTimeout(loadEstimateConversionStatus, 3000);
  } catch (error) {
    showToast(error.message);
  }
}

function sanityReviewMessage(preflight) {
  const lines = [
    "Estimate Sanity Check:",
    "",
  ];
  
  const grouped = {};
  for (const finding of preflight.findings || []) {
    const title = finding.job_title || "General";
    if (!grouped[title]) {
      grouped[title] = [];
    }
    grouped[title].push(finding.message);
  }

  for (const [title, msgs] of Object.entries(grouped)) {
    lines.push(`• ${title}:`);
    for (const msg of msgs) {
      lines.push(`  - ${msg}`);
    }
    lines.push("");
  }

  lines.push("OK = Build PDF anyway");
  lines.push("Cancel = Stop and fix in Mitchell");
  return lines.join("\n");
}

function renderEstimatePreflight(preflight, statusText) {
  const container = document.getElementById("estimate-preview");
  if (!container) return;
  container.className = "output-empty warning-preview stack";
  container.innerHTML = "";

  const heading = document.createElement("h3");
  heading.style.color = "#ffc107";
  heading.textContent = "Estimate Sanity Check (Build Cancelled)";
  container.appendChild(heading);

  const status = document.createElement("p");
  status.textContent = statusText || "Review required before building.";
  container.appendChild(status);

  const list = document.createElement("ul");
  list.style.textAlign = "left";
  list.style.display = "inline-block";
  list.style.margin = "10px auto";
  for (const finding of preflight.findings || []) {
    const item = document.createElement("li");
    item.textContent = `${finding.job_title || "Estimate line"} - ${finding.message || ""}`;
    list.appendChild(item);
  }
  container.appendChild(list);
}

function renderEstimateStatus(status) {
  const pill = document.getElementById("estimate-status-pill");
  if (pill) pill.textContent = status.ready ? "Ready" : status.setup_ready ? "Model offline" : "Needs setup";

  const container = document.getElementById("estimate-status");
  if (!container) return;
  const checks = status.checks || {};
  container.innerHTML = "";

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

  const rootRow = document.createElement("div");
  rootRow.className = "status-path";
  rootRow.textContent = status.root || "";
  container.appendChild(rootRow);
}

function engineStatusLabel(engine) {
  if (engine.online) return "Model ready";
  if (engine.status === "loading") return "Model loading";
  return "Model offline";
}

function renderEstimateOutput(data) {
  renderEstimatePreview(data);
}

function renderEstimatePreview(data) {
  const preview = document.getElementById("estimate-preview");
  const openLink = document.getElementById("open-pdf-link");
  const downloadLink = document.getElementById("download-pdf-link");
  if (!preview) return;
  preview.innerHTML = "";

  if (!data.pdf) {
    preview.className = "output-empty pdf-preview-empty";
    preview.textContent = "No PDF built yet.";
    if (openLink) openLink.style.display = "none";
    if (downloadLink) downloadLink.style.display = "none";
    return;
  }

  if (openLink) {
    openLink.href = estimatePdfUrl(data.pdf);
    openLink.style.display = "inline-flex";
  }
  if (downloadLink) {
    downloadLink.href = estimatePdfUrl(data.pdf);
    // Setting download attribute explicitly with the file name helps browsers prompt for download
    const filename = data.filename || pdfFilename(data.pdf);
    downloadLink.setAttribute("download", filename);
    downloadLink.style.display = "inline-flex";
  }

  preview.className = "pdf-preview-shell stack";
  preview.style.display = "flex";
  preview.style.flexDirection = "column";

  const helpText = document.createElement("p");
  helpText.style.textAlign = "center";
  helpText.style.color = "var(--muted)";
  helpText.style.fontSize = "0.85rem";
  helpText.style.margin = "0 0 12px 0";
  helpText.innerHTML = "💡 Previewing document below. <strong>Click 'Open in New Tab' to view full-size, or 'Download PDF' to save to your PC.</strong>";
  preview.appendChild(helpText);

  const frame = document.createElement("iframe");
  frame.className = "pdf-preview-frame";
  frame.title = "Generated estimate PDF preview";
  frame.src = estimatePdfUrl(data.pdf);
  frame.style.flex = "1";
  preview.appendChild(frame);
}

function estimatePdfUrl(path) {
  if (path.includes("/inshop/")) {
    return path;
  }
  return `/api/estimate-conversion/pdf?path=${encodeURIComponent(path)}`;
}

function pdfFilename(path) {
  return String(path || "").split(/[\\/]/).pop() || "estimate.pdf";
}

async function uploadInShopEstimatePdf(file) {
  if (!file) {
    throw new Error("Select a Mitchell SubEstimate / ASR PDF.");
  }
  const response = await fetch(`/api/inshop/estimate/upload?filename=${encodeURIComponent(file.name || "estimate.pdf")}`, {
    method: "POST",
    headers: {"Content-Type": "application/pdf"},
    body: await file.arrayBuffer(),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Upload failed with ${response.status}`);
  }
  return data;
}

document.addEventListener("DOMContentLoaded", () => {
  if (!document.getElementById("status-inshop")) return;
  initInShopEstimate();
});

function initInShopEstimate() {
  const statusPill = document.getElementById("status-inshop");
  const fileInput = document.getElementById("asr-pdf-file");
  const techNotesInput = document.getElementById("tech-notes");
  
  const step1Panel = document.getElementById("step-1-panel");
  const step2Panel = document.getElementById("step-2-panel");
  const step3Panel = document.getElementById("step-3-panel");
  
  const editComplaint = document.getElementById("edit-complaint");
  const editFindings = document.getElementById("edit-findings");
  const editCurrentRoTotal = document.getElementById("edit-current-ro-total");
  const jobsContainer = document.getElementById("jobs-container");
  
  const btnAnalyze = document.getElementById("btn-analyze");
  const btnSaveGenerate = document.getElementById("btn-save-generate");
  const btnBackStep1 = document.getElementById("btn-back-step1");
  const btnStartOver = document.getElementById("btn-start-over");
  
  const pdfFrame = document.getElementById("inshop-pdf-frame");
  const downloadLink = document.getElementById("download-inshop-link");
  
  let currentEstimateId = null;
  let parsedManifest = null;

  const setStatus = (state, label) => {
    statusPill.dataset.state = state;
    statusPill.textContent = label;
  };

  btnAnalyze.addEventListener("click", async () => {
    const file = fileInput.files[0];
    const notesText = techNotesInput.value.trim();

    if (!file) {
      alert("Please select a Mitchell SubEstimate / ASR PDF.");
      return;
    }
    if (!notesText) {
      alert("Please paste the technician findings/stories.");
      return;
    }

    btnAnalyze.disabled = true;
    setStatus("loading", "Uploading PDF...");

    try {
      // 1. Upload PDF
      const uploadResp = await fetch(`/api/inshop/estimate/upload?filename=${encodeURIComponent(file.name || "estimate.pdf")}`, {
        method: "POST",
        headers: { "Content-Type": "application/pdf" },
        body: await file.arrayBuffer(),
      });
      if (!uploadResp.ok) {
        const err = await uploadResp.json();
        throw new Error(err.detail || "Failed to upload ASR PDF");
      }
      const uploadData = await uploadResp.json();
      currentEstimateId = uploadData.estimate_id;
      parsedManifest = uploadData.manifest;

      // 2. Run LLM Analysis
      setStatus("loading", "Analyzing with Qwen...");
      const analyzeResp = await fetch(`/api/inshop/estimate/${currentEstimateId}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw_text: notesText }),
      });
      if (!analyzeResp.ok) {
        const err = await analyzeResp.json();
        throw new Error(err.detail || "LLM matching failed");
      }
      const analyzeData = await analyzeResp.json();

      // Populate Step 2 fields
      editComplaint.value = analyzeData.customer_concern;
      editFindings.value = analyzeData.technician_findings;
      
      renderJobCards(parsedManifest.jobs, analyzeData.jobs);

      // Transition to Step 2
      step1Panel.style.display = "none";
      step2Panel.style.display = "block";
      setStatus("online", "Review Mappings");
    } catch (err) {
      console.error(err);
      setStatus("error", "Error");
      alert(err.message);
    } finally {
      btnAnalyze.disabled = false;
    }
  });

  function renderJobCards(jobs, mappings) {
    jobsContainer.replaceChildren();
    jobs.forEach((job, idx) => {
      const mapping = mappings[idx] || {};
      const card = document.createElement("div");
      card.className = "job-edit-card stack";
      card.dataset.idx = idx;

      const jobTotal = (parseFloat(job.labour_cost) || 0) + (parseFloat(job.parts_retail_cad) || 0);

      // Create includes string from array
      const includesStr = Array.isArray(mapping.repair_includes) 
        ? mapping.repair_includes.join("\n") 
        : (job.labour_lines || []).join("\n");

      const heading = document.createElement("h3");
      const title = document.createElement("span");
      title.textContent = `Job ${idx + 1}: ${job.title || "Untitled service"}`;
      const total = document.createElement("span");
      total.className = "job-total";
      total.textContent = `$${jobTotal.toFixed(2)}`;
      heading.append(title, total);

      const grid = document.createElement("div");
      grid.className = "job-grid";

      const priorityLabel = document.createElement("label");
      priorityLabel.append(document.createTextNode("Priority"));
      const prioritySelect = document.createElement("select");
      prioritySelect.className = "job-priority";
      const priorities = [
        "Severe - Repair Promptly",
        "Maintenance - Recommended",
        "Nice to Do - Suggested",
      ];
      const requestedPriority = String(mapping.priority || "Maintenance - Recommended");
      priorities.forEach(priority => {
        const option = document.createElement("option");
        option.value = priority;
        option.textContent = priority;
        if (
          (priority.startsWith("Severe") && requestedPriority.includes("Severe")) ||
          (priority.startsWith("Maintenance") && requestedPriority.includes("Maintenance")) ||
          (priority.startsWith("Nice") && (requestedPriority.includes("Nice") || requestedPriority.includes("Suggested")))
        ) {
          option.selected = true;
        }
        prioritySelect.appendChild(option);
      });
      priorityLabel.appendChild(prioritySelect);
      grid.appendChild(priorityLabel);

      const addTextarea = (labelText, className, rows, value, wide = false) => {
        const label = document.createElement("label");
        label.append(document.createTextNode(labelText));
        if (wide) label.className = "job-field-wide";
        const textarea = document.createElement("textarea");
        textarea.className = className;
        textarea.rows = rows;
        textarea.value = String(value ?? "");
        label.appendChild(textarea);
        grid.appendChild(label);
      };

      addTextarea("Included Work (One step per line)", "job-includes", 3, includesStr);
      addTextarea(
        "What Technician Found (Condition)",
        "job-found",
        2,
        mapping.tech_found || "Technician findings for this service."
      );
      addTextarea(
        "What We Recommend (Correction)",
        "job-rec",
        2,
        mapping.recommendation || "Perform recommended service."
      );
      addTextarea(
        "Why It Matters (Psychology / Customer context)",
        "job-matters",
        2,
        mapping.why_matters || "Helps maintain safety and reliability.",
        true
      );

      card.append(heading, grid);
      jobsContainer.appendChild(card);
    });
  }

  btnSaveGenerate.addEventListener("click", async () => {
    btnSaveGenerate.disabled = true;
    setStatus("loading", "Saving changes...");

    const story_mappings = {};
    const cards = jobsContainer.querySelectorAll(".job-edit-card");
    cards.forEach(card => {
      const idx = card.dataset.idx;
      const priority = card.querySelector(".job-priority").value;
      const tech_found = card.querySelector(".job-found").value.trim();
      const rec = card.querySelector(".job-rec").value.trim();
      const why_matters = card.querySelector(".job-matters").value.trim();
      
      const includesLines = card.querySelector(".job-includes").value.split("\n")
        .map(line => line.trim())
        .filter(line => line.length > 0);

      story_mappings[idx] = {
        job_index: parseInt(idx),
        priority: priority,
        tech_found: tech_found,
        recommendation: rec,
        why_matters: why_matters,
        repair_includes: includesLines
      };
    });

    try {
      // 1. Save data
      const saveResp = await fetch(`/api/inshop/estimate/${currentEstimateId}/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_concern: editComplaint.value.trim(),
          technician_findings: editFindings.value.trim(),
          current_ro_total: parseFloat(editCurrentRoTotal.value) || null,
          story_mappings: story_mappings
        }),
      });
      if (!saveResp.ok) throw new Error("Failed to save changes to DB");

      // 2. Generate PDF
      setStatus("loading", "Building PDF...");
      const genResp = await fetch(`/api/inshop/estimate/${currentEstimateId}/generate-pdf`, {
        method: "POST"
      });
      if (!genResp.ok) {
        const err = await genResp.json();
        throw new Error(err.detail || "PDF generation failed");
      }
      const genData = await genResp.json();

      // Show Step 3 preview
      pdfFrame.src = `/api/inshop/estimate/${currentEstimateId}/pdf`;
      downloadLink.href = `/api/inshop/estimate/${currentEstimateId}/pdf`;
      const filename = String(genData.pdf_path || "").split(/[\\/]/).pop() || "IN_SHOP_ESTIMATE.pdf";
      downloadLink.setAttribute("download", filename);

      step2Panel.style.display = "none";
      step3Panel.style.display = "block";
      setStatus("done", "Estimate Generated");
    } catch (err) {
      console.error(err);
      setStatus("error", "Error");
      alert(err.message);
    } finally {
      btnSaveGenerate.disabled = false;
    }
  });

  btnBackStep1.addEventListener("click", () => {
    step2Panel.style.display = "none";
    step1Panel.style.display = "block";
    setStatus("online", "Ready");
  });

  btnStartOver.addEventListener("click", () => {
    if (confirm("Are you sure you want to discard this estimate and start over?")) {
      currentEstimateId = null;
      parsedManifest = null;
      fileInput.value = "";
      techNotesInput.value = "";
      step3Panel.style.display = "none";
      step1Panel.style.display = "block";
      setStatus("online", "Ready");
    }
  });
}

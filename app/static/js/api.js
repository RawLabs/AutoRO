async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  let data = null;
  try {
    data = await response.json();
  } catch (_error) {
    data = {};
  }

  if (!response.ok) {
    const detail = data.detail || `Request failed with ${response.status}`;
    throw new Error(detail);
  }

  return data;
}

function showToast(message) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 3800);
}

function formToPayload(form) {
  const formData = new FormData(form);
  const payload = {};
  for (const [key, value] of formData.entries()) {
    if (key === "vehicle_year" || key === "mileage" || key === "year" || key === "mileage_km") {
      payload[key] = value ? Number(value) : null;
    } else {
      payload[key] = String(value || "").trim();
    }
  }
  return payload;
}

function textOrDash(value) {
  if (value === null || value === undefined || value === "") return "—";
  const text = String(value).trim();
  if (looksLikeJsonDump(text)) return "—";
  return text;
}

function looksLikeJsonDump(text) {
  return (
    (text.startsWith("{") && text.includes("}")) ||
    (text.startsWith("[") && text.includes("]"))
  );
}

function outputLabels() {
  return {
    customer_explanation: "Customer explanation",
  };
}

function renderOutput(container, output) {
  const labels = outputLabels();
  container.innerHTML = "";

  for (const [key, label] of Object.entries(labels)) {
    const section = document.createElement("section");
    section.className = "output-section";

    const heading = document.createElement("h3");
    heading.textContent = label;
    section.appendChild(heading);

    const paragraph = document.createElement("p");
    paragraph.textContent = textOrDash(output ? output[key] : "");
    section.appendChild(paragraph);

    container.appendChild(section);
  }
}

function renderInvoiceText(container, explanation) {
  container.classList.remove("output-empty");
  container.innerHTML = "";
  const paragraph = document.createElement("p");
  paragraph.className = "invoice-text";
  paragraph.textContent = textOrDash(explanation);
  container.appendChild(paragraph);
}

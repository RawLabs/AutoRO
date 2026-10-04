document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;
  loadReleaseIdentifier();

  if (page === "dashboard") {
    showLaunchSplash();
    initDashboard();
  }
});

function showLaunchSplash() {
  const splash = document.getElementById("launch-splash");
  if (!splash) return;

  const storageKey = "autoro-beta-splash-seen";
  try {
    if (window.sessionStorage.getItem(storageKey) === "1") return;
    window.sessionStorage.setItem(storageKey, "1");
  } catch (_error) {
    // Storage may be disabled; the splash can still run normally.
  }

  let dismissed = false;
  let hideTimer;
  let removeTimer;
  const dismiss = () => {
    if (dismissed) return;
    dismissed = true;
    window.clearTimeout(hideTimer);
    window.clearTimeout(removeTimer);
    splash.classList.add("is-leaving");
    removeTimer = window.setTimeout(() => {
      splash.hidden = true;
      document.body.classList.remove("splash-active");
    }, 450);
  };

  document.body.classList.add("splash-active");
  splash.hidden = false;
  window.requestAnimationFrame(() => splash.classList.add("is-visible"));
  splash.addEventListener("click", dismiss);
  splash.querySelector(".launch-splash-skip")?.addEventListener("click", dismiss);
  hideTimer = window.setTimeout(dismiss, 3000);
}

async function loadReleaseIdentifier() {
  const releasePill = document.getElementById("release-pill");
  if (!releasePill) return;

  try {
    const data = await apiRequest("/api/release");
    const releaseId = String(data?.release_id || "").trim() || "UNVERIFIED";
    releasePill.textContent = `AutoRO ${releaseId}`;
  } catch (_error) {
    releasePill.textContent = "AutoRO UNVERIFIED";
  }
}

function moduleStatusLabel(engine) {
  if (!engine) return "Unknown";
  if (engine.online) return "Ready";
  if (engine.status === "loading") return "Loading";
  return "Offline";
}

function setModuleStatus(id, label, state = "ready") {
  const element = document.getElementById(id);
  if (!element) return;
  element.textContent = label;
  element.dataset.state = state;
}

async function loadDashboardReadiness() {
  try {
    const data = await apiRequest("/api/health");
    const engines = data.estimate_conversion?.model_engines || {};
    // Translator and estimate conversion normally share one local Qwen engine.
    // Keep the named fallbacks for older/split-engine installations.
    const sharedEngine = engines.estimate_ai || engines.estimator || engines.translator || {};
    const translator = engines.translator || sharedEngine;
    const estimator = engines.estimate_ai || engines.estimator || sharedEngine;
    const translatorState = translator.online ? "online" : translator.status === "loading" ? "loading" : "offline";
    const estimatorState = estimator.online ? "online" : estimator.status === "loading" ? "loading" : "offline";

    setModuleStatus("status-translator", moduleStatusLabel(translator), translatorState);
    setModuleStatus("status-advisor", moduleStatusLabel(translator), translatorState);
    setModuleStatus("status-estimates", moduleStatusLabel(estimator), estimatorState);
    setModuleStatus("status-operations", moduleStatusLabel(translator), translatorState);

    setModuleStatus("status-bg", "Ready", "ready");
    setModuleStatus("status-logs", "Ready", "ready");
    setModuleStatus("status-management", "Ready", "ready");

    const allOnline = translatorState === "online" && estimatorState === "online";
    window.setTimeout(loadDashboardReadiness, allOnline ? 10000 : 3000);
  } catch (_error) {
    for (const id of ["status-translator", "status-advisor", "status-estimates", "status-operations"]) {
      setModuleStatus(id, "Status unknown", "unknown");
    }
    window.setTimeout(loadDashboardReadiness, 3000);
  }
}

async function initDashboard() {
  await Promise.all([loadStats(), loadDashboardReadiness()]);
}

async function loadStats() {
  try {
    const stats = await apiRequest("/api/stats");
    document.getElementById("stat-cases").textContent = stats.cases;
    document.getElementById("stat-saved").textContent = stats.approved_training_examples;
  } catch (error) {
    showToast(error.message);
  }
}

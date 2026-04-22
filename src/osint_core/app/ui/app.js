/* ==========================================================================
   POIREAUT · app.js
   Routing entre vues + lifecycle d'une enquête via pywebview.api
   ========================================================================== */

const ENTITY_COLORS = {
  username: "#2f6b4a",
  account:  "#1e4a34",
  email:    "#c6a14a",
  url:      "#8c6f2a",
  location: "#a54a3e",
  phone:    "#549a70",
  person:   "#c6a14a",
  domain:   "#549a70",
  ip:       "#549a70",
  image:    "#a54a3e",
};

// ---------- State ----------

const state = {
  currentView: "home",
  targetType: "username",
  investigationId: null,
  pollTimer: null,
  capabilities: { maigret: false, vision: false, holehe: false },
};

// ---------- Helpers ----------

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function api() {
  return (window.pywebview && window.pywebview.api) || null;
}

function setView(view) {
  state.currentView = view;
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  $$(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.view === view));
}

// ---------- Boot ----------

window.addEventListener("pywebviewready", async () => {
  await bootstrap();
});

// If pywebview isn't available (ex: opened directly in browser for dev),
// fall back after a short wait so the UI is at least visible.
setTimeout(async () => {
  if (!api()) {
    console.warn("pywebview.api unavailable — running in preview mode");
    renderCapabilities({ maigret: false, vision: false, holehe: false });
    $("#version").textContent = "dev";
    setupStaticBindings();
    return;
  }
  await bootstrap();
}, 400);

async function bootstrap() {
  const a = api();
  if (!a) return;

  try {
    const version = await a.get_version();
    $("#version").textContent = version;
  } catch {}

  try {
    const caps = await a.get_capabilities();
    state.capabilities = caps;
    renderCapabilities(caps);
  } catch (e) {
    console.warn("get_capabilities failed", e);
  }

  setupStaticBindings();
}

function renderCapabilities(caps) {
  const capsEl = $("#caps");
  capsEl.innerHTML = "";
  const entries = [
    ["maigret", "Maigret"],
    ["vision", "Vision"],
    ["holehe", "Holehe"],
  ];
  for (const [key, label] of entries) {
    const pill = document.createElement("span");
    pill.className = "cap-pill" + (caps[key] ? " on" : "");
    pill.textContent = label;
    pill.title = caps[key]
      ? `${label} est installé et disponible`
      : `${label} non installé — le collecteur sera désactivé`;
    capsEl.appendChild(pill);
  }

  // Reflect on form
  const maigretCheck = $("#opt-maigret");
  const maigretRow   = $("#check-maigret");
  if (!caps.maigret) {
    maigretCheck.disabled = true;
    maigretCheck.checked = false;
    maigretRow.title = "Installer l'extra : pip install 'osint-core[maigret]'";
  }
  const holeheCheck = $("#opt-holehe");
  const holeheRow   = $("#check-holehe");
  if (!caps.holehe) {
    holeheCheck.disabled = true;
    holeheCheck.checked = false;
    holeheRow.title = "Installer l'extra : pip install 'osint-core[email-lookup]'";
  }
}

// ---------- Static bindings ----------

function setupStaticBindings() {
  // Sidebar nav
  $$(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      setView(btn.dataset.view);
    });
  });
  // "data-go" shortcut buttons in Home
  $$("[data-go]").forEach((el) => {
    el.addEventListener("click", () => setView(el.dataset.go));
  });

  // Segmented control: username / email
  $$("#seg-type .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$("#seg-type .seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
      state.targetType = btn.dataset.type;
      const input = $("#target-input");
      input.placeholder = state.targetType === "email"
        ? "ex. alice@exemple.com"
        : "ex. alice_dev";
    });
  });

  // Submit on Enter inside the input
  $("#target-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") startInvestigation();
  });

  $("#btn-start").addEventListener("click", startInvestigation);
  $("#btn-view-graph").addEventListener("click", openGraphView);
  $("#btn-save-report").addEventListener("click", saveReport);
}

// ---------- Investigation lifecycle ----------

async function startInvestigation() {
  const a = api();
  const target = $("#target-input").value.trim();
  if (!target) {
    $("#target-input").focus();
    return;
  }
  if (!a) {
    console.warn("No API — cannot start");
    return;
  }

  const config = {
    target,
    target_type: state.targetType,
    maigret: $("#opt-maigret").checked,
    enrich:  $("#opt-enrich").checked,
    holehe:  $("#opt-holehe").checked,
  };

  $("#btn-start").disabled = true;
  $("#btn-start").textContent = "Enquête en cours…";

  // Switch visual state
  $("#status-empty").hidden = true;
  $("#status-active").hidden = false;
  $("#results-actions").hidden = true;
  $("#log").innerHTML = "";
  $("#status-phase").textContent = "Analyse en cours";
  $("#status-target").textContent = `${state.targetType === "email" ? "✉" : "@"} ${target}`;
  $("#status-summary").innerHTML = "";

  try {
    const invId = await a.start_investigation(config);
    state.investigationId = invId;
    pollStatus();
  } catch (e) {
    console.error("start_investigation failed", e);
    showError(String(e));
    resetStartButton();
  }
}

function pollStatus() {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    const a = api();
    if (!a || !state.investigationId) return;
    try {
      const st = await a.get_status(state.investigationId);
      renderStatus(st);
      if (st.status === "done" || st.status === "error") {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        resetStartButton();
        if (st.status === "done") {
          $("#nav-graph").disabled = false;
          $("#results-actions").hidden = false;
          $("#status-phase").textContent = "Enquête close";
          $("#status-block").querySelector(".status-dot")?.classList.add("done");
        } else {
          $("#status-phase").textContent = st.error === "Cancelled" ? "Enquête interrompue" : "Échec";
          $("#status-block").querySelector(".status-dot")?.classList.add("error");
        }
      }
    } catch (e) {
      console.warn("poll error", e);
    }
  }, 450);
}

function renderStatus(st) {
  // Log
  const logEl = $("#log");
  const wantScroll = Math.abs(logEl.scrollHeight - logEl.clientHeight - logEl.scrollTop) < 30;
  logEl.innerHTML = "";
  for (const line of st.logs || []) {
    const div = document.createElement("div");
    div.textContent = line;
    logEl.appendChild(div);
  }
  if (wantScroll) logEl.scrollTop = logEl.scrollHeight;

  // Summary chips
  const sum = st.summary || {};
  const chipContainer = $("#status-summary");
  chipContainer.innerHTML = "";
  const sorted = Object.entries(sum)
    .filter(([k]) => k !== "relationships")
    .sort((a, b) => b[1] - a[1]);
  for (const [type, count] of sorted) {
    const chip = document.createElement("div");
    chip.className = "summary-chip";
    chip.innerHTML = `
      <span class="dot" style="background:${ENTITY_COLORS[type] || '#8a8170'}"></span>
      <span class="k">${type}</span>
      <span class="v">${count}</span>
    `;
    chipContainer.appendChild(chip);
  }
  if (sum.relationships) {
    const chip = document.createElement("div");
    chip.className = "summary-chip";
    chip.innerHTML = `
      <span class="dot" style="background:var(--brass)"></span>
      <span class="k">relations</span>
      <span class="v">${sum.relationships}</span>
    `;
    chipContainer.appendChild(chip);
  }
}

function resetStartButton() {
  $("#btn-start").disabled = false;
  $("#btn-start").innerHTML = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m5 12 5 5L20 7"/></svg>
    Démarrer l'enquête
  `;
}

function showError(msg) {
  const div = document.createElement("div");
  div.style.color = "var(--seal)";
  div.textContent = `✗ ${msg}`;
  $("#log").appendChild(div);
}

// ---------- Graph view ----------

async function openGraphView() {
  const a = api();
  if (!a || !state.investigationId) return;
  try {
    const st = await a.get_status(state.investigationId);
    if (st.graph_url) {
      $("#graph-frame").src = st.graph_url;
      setView("graph");
    }
  } catch (e) {
    console.error("openGraphView", e);
  }
}

// ---------- Save report ----------

async function saveReport() {
  const a = api();
  if (!a || !state.investigationId) return;
  // pywebview has a native save dialog API
  try {
    const result = await window.pywebview.api.get_status(state.investigationId);
    if (!result.report_path) return;

    // Trigger native file save via webview's create_file_dialog — pywebview exposes it globally
    // but not on js_api by default. We fall back to asking the user to copy the path.
    const filename = `poireaut-${result.target.replace(/[^a-z0-9_-]/gi, "_")}.json`;

    // Try pywebview native save dialog (depends on version)
    if (window.pywebview && typeof window.pywebview.saveDialog === "function") {
      const path = await window.pywebview.saveDialog(filename);
      if (!path) return;
      const r = await a.save_report(state.investigationId, path);
      if (r.ok) flashSuccess(`Dossier exporté : ${r.path}`);
      else flashError(`Échec : ${r.error}`);
      return;
    }

    // Fallback: copy the temp report path to the clipboard so the user can
    // move the file themselves.
    try {
      await navigator.clipboard.writeText(result.report_path);
      flashSuccess(`Chemin copié dans le presse-papier :\n${result.report_path}`);
    } catch {
      alert(`Le rapport est disponible ici :\n\n${result.report_path}`);
    }
  } catch (e) {
    console.error("saveReport", e);
  }
}

function flashSuccess(msg) { addLogMessage("✓  " + msg); }
function flashError(msg)   { addLogMessage("✗  " + msg); }
function addLogMessage(msg) {
  const div = document.createElement("div");
  div.textContent = msg;
  $("#log").appendChild(div);
  $("#log").scrollTop = $("#log").scrollHeight;
}

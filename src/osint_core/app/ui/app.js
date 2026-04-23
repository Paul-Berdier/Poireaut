const ENTITY_COLORS = {
  username:"#2f6b4a", account:"#1e4a34", email:"#c6a14a", url:"#8c6f2a",
  location:"#a54a3e", phone:"#549a70", person:"#c6a14a", domain:"#549a70",
  ip:"#549a70", image:"#a54a3e",
};
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
const api = () => (window.pywebview && window.pywebview.api) || null;

let _booted = false;
let currentInvId = null;
let pollTimer = null;

// ===== BOOT =====
window.addEventListener("pywebviewready", () => { if(!_booted){_booted=true;boot();} });
(async()=>{for(let i=0;i<20;i++){await new Promise(r=>setTimeout(r,200));if(_booted)return;if(api()){_booted=true;boot();return;}}if(!_booted){_booted=true;boot();}})();

async function boot() {
  const a = api();
  if (a) {
    try { $("#version").textContent = await a.get_version(); } catch {}
    try {
      const caps = await a.get_capabilities();
      const el = $("#caps");
      el.innerHTML = "";
      for (const [k,v] of Object.entries(caps)) {
        const pill = document.createElement("span");
        pill.className = "cap-pill" + (v ? " on" : "");
        pill.textContent = k;
        el.appendChild(pill);
      }
    } catch {}
  }
  setupBindings();
}

// ===== NAVIGATION =====
function setView(v) {
  $$(".view").forEach(el => el.classList.toggle("active", el.id === "view-"+v));
  $$(".nav-item").forEach(n => n.classList.toggle("active", n.dataset.view === v));
}

// ===== BINDINGS =====
function setupBindings() {
  $$(".nav-item").forEach(b => b.addEventListener("click", () => setView(b.dataset.view)));
  $$("[data-go]").forEach(b => b.addEventListener("click", () => setView(b.dataset.go)));

  // Add row buttons
  $$(".add-row-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const container = $("#" + btn.dataset.target);
      const type = btn.dataset.type;
      const placeholders = {username:"ex. pseudo",email:"ex. email@test.com",phone:"ex. +33...",ip:"ex. 8.8.8.8"};
      const row = document.createElement("div");
      row.className = "multi-row";
      row.innerHTML = `<input type="text" placeholder="${placeholders[type]||''}" data-type="${type}"><button class="row-remove" title="Retirer">&times;</button>`;
      container.appendChild(row);
      row.querySelector("input").focus();
    });
  });

  // Remove row (delegation)
  document.addEventListener("click", e => {
    if (e.target.classList.contains("row-remove")) {
      const row = e.target.closest(".multi-row");
      const container = row.parentElement;
      if (container.children.length > 1) row.remove();
      else row.querySelector("input").value = "";
    }
  });

  // Enter key in any input -> start
  document.addEventListener("keydown", e => {
    if (e.key === "Enter" && e.target.closest(".multi-row")) startInvestigation();
  });

  $("#btn-start").addEventListener("click", startInvestigation);
  $("#btn-view-graph").addEventListener("click", openGraph);
  $("#btn-save-report").addEventListener("click", saveReport);
}

// ===== COLLECT ALL INPUTS =====
function collectSeeds() {
  const seeds = [];
  $$(".multi-row input").forEach(input => {
    const val = input.value.trim();
    if (!val) return;
    seeds.push({ value: val, type: input.dataset.type });
  });
  return seeds;
}

// ===== START INVESTIGATION =====
async function startInvestigation() {
  const a = api();
  if (!a) return;

  const seeds = collectSeeds();
  if (seeds.length === 0) {
    $$(".multi-row input")[0]?.focus();
    return;
  }

  $("#btn-start").disabled = true;
  $("#btn-start").textContent = "Enquete en cours...";
  $("#status-empty").hidden = true;
  $("#status-active").hidden = false;
  $("#results-actions").hidden = true;
  $("#log").innerHTML = "";
  $("#status-summary").innerHTML = "";
  $(".status-dot").className = "status-dot";
  $("#status-phase").textContent = "Analyse en cours";

  try {
    const invId = await a.start_investigation({ seeds: seeds });
    currentInvId = invId;
    startPolling();
  } catch (e) {
    addLog("Erreur: " + e);
    resetBtn();
  }
}

// ===== POLLING =====
function startPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const a = api();
    if (!a || !currentInvId) return;
    try {
      const st = await a.get_status(currentInvId);
      renderStatus(st);
      if (st.status === "done" || st.status === "error") {
        clearInterval(pollTimer);
        resetBtn();
        if (st.status === "done") {
          $("#results-actions").hidden = false;
          $("#status-phase").textContent = "Enquete close";
          $(".status-dot").classList.add("done");
        } else {
          $("#status-phase").textContent = "Echec";
          $(".status-dot").classList.add("error");
        }
      }
    } catch {}
  }, 400);
}

function renderStatus(st) {
  const logEl = $("#log");
  const autoScroll = Math.abs(logEl.scrollHeight - logEl.clientHeight - logEl.scrollTop) < 40;
  logEl.innerHTML = "";
  for (const line of (st.logs || [])) {
    const d = document.createElement("div");
    d.textContent = line;
    logEl.appendChild(d);
  }
  if (autoScroll) logEl.scrollTop = logEl.scrollHeight;

  const chips = $("#status-summary");
  chips.innerHTML = "";
  const sum = st.summary || {};
  for (const [type, count] of Object.entries(sum).filter(([k])=>k!=="relationships").sort((a,b)=>b[1]-a[1])) {
    chips.innerHTML += `<span class="summary-chip"><span class="dot" style="background:${ENTITY_COLORS[type]||'#888'}"></span><span class="k">${type}</span><span class="v">${count}</span></span>`;
  }
  if (sum.relationships) {
    chips.innerHTML += `<span class="summary-chip"><span class="dot" style="background:var(--brass)"></span><span class="k">liens</span><span class="v">${sum.relationships}</span></span>`;
  }
}

function resetBtn() {
  $("#btn-start").disabled = false;
  $("#btn-start").textContent = "Lancer l'enquete";
}

// ===== GRAPH =====
async function openGraph() {
  const a = api();
  if (!a || !currentInvId) return;
  try {
    const r = await a.open_graph(currentInvId);
    if (r && r.ok) addLog("Toile ouverte dans le navigateur");
    else addLog("Erreur: " + (r?r.error:"indisponible"));
  } catch(e) { addLog("Erreur: "+e); }
}

// ===== SAVE =====
async function saveReport() {
  const a = api();
  if (!a || !currentInvId) return;
  try {
    const r = await a.save_report(currentInvId);
    if (r && r.ok) addLog("Rapport enregistre: " + r.path);
    else addLog("Export annule");
  } catch(e) { addLog("Erreur: "+e); }
}

function addLog(msg) {
  const d = document.createElement("div");
  d.textContent = msg;
  $("#log").appendChild(d);
  $("#log").scrollTop = $("#log").scrollHeight;
}

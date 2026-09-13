let state = {
  timeline: [],
  selectedIndex: null,
  currentTab: "summary",
  currentDesignTab: "verilog",
  verilog: "",
  graph: { status: "wip", message: "Work in Progress" },
};

async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Request failed: ${res.status}`);
  }
  return res.json();
}

async function configureSession() {
  const payload = {
    config_path: document.getElementById("configPath").value,
    no_llm: document.getElementById("noLlm").checked,
    require_llm: document.getElementById("requireLlm").checked,
    debug: document.getElementById("debugMode").checked,
  };
  await api("/api/configure", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  await refreshState();
}

async function resetSession() {
  await api("/api/reset", { method: "POST" });
  state.timeline = [];
  state.selectedIndex = null;
  renderAll();
}

async function runRequest() {
  const text = document.getElementById("requestInput").value.trim();
  if (!text) return;
  await api("/api/request", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  document.getElementById("requestInput").value = "";
  await refreshState();
  state.selectedIndex = state.timeline.length - 1;
  renderAll();
}

async function refreshState() {
  const data = await api("/api/state");
  state.timeline = data.timeline || [];
  state.verilog = data.verilog || "";
  state.graph = data.graph || { status: "wip", message: "Work in Progress" };

  document.getElementById("plannerStatus").textContent = `Planner: ${data.planner_class || "-"}`;
  document.getElementById("caseStatus").textContent = `Case: ${data.case_name || "-"}`;
  document.getElementById("designStatus").textContent = `Design: ${data.design_loaded || "-"}`;

  if (state.selectedIndex === null && state.timeline.length > 0) {
    state.selectedIndex = state.timeline.length - 1;
  }

  renderAll();
}

function renderAll() {
  renderTimeline();
  renderDetail();
  renderDesign();
}

function renderTimeline() {
  const root = document.getElementById("timeline");
  root.innerHTML = "";

  if (!state.timeline.length) {
    root.innerHTML = `<div class="empty">No requests yet.</div>`;
    return;
  }

  state.timeline.forEach((item, idx) => {
    const card = document.createElement("div");
    card.className = `timeline-card ${state.selectedIndex === idx ? "selected" : ""}`;
    card.onclick = () => {
      state.selectedIndex = idx;
      renderAll();
    };

    const tool = item.validated_tool?.tool || "-";
    const status = item.execution_error && Object.keys(item.execution_error).length
      ? "error"
      : item.validation_error && Object.keys(item.validation_error).length
      ? "warning"
      : "success";

    card.innerHTML = `
      <div class="timeline-header">
        <span class="req-index">Request ${item.request_index}</span>
        <span class="badge ${status}">${status}</span>
      </div>
      <div class="timeline-request">${escapeHtml(item.request_text)}</div>
      <div class="timeline-sub">Tool: ${escapeHtml(tool)}</div>
    `;
    root.appendChild(card);
  });
}

function renderDetail() {
  const root = document.getElementById("detailContent");
  const item = state.selectedIndex !== null ? state.timeline[state.selectedIndex] : null;

  if (!item) {
    root.innerHTML = `<div class="empty">Select a request step.</div>`;
    return;
  }

  const tab = state.currentTab;
  if (tab === "summary") {
    root.innerHTML = `
      <pre>${escapeHtml(JSON.stringify({
        request_text: item.request_text,
        stdout: item.stdout,
        response: item.response,
        planner_meta: item.planner_meta,
      }, null, 2))}</pre>
    `;
    return;
  }

  if (tab === "planner") {
    root.innerHTML = `
      <h3>Planner Meta</h3>
      <pre>${escapeHtml(JSON.stringify(item.planner_meta || {}, null, 2))}</pre>
      <h3>Planner Raw Output</h3>
      <pre>${escapeHtml(item.planner_raw || "")}</pre>
    `;
    return;
  }

  if (tab === "validated") {
    root.innerHTML = `<pre>${escapeHtml(JSON.stringify(item.validated_tool || {}, null, 2))}</pre>`;
    return;
  }

  if (tab === "output") {
    root.innerHTML = `
      <h3>Summary</h3>
      <pre>${escapeHtml(item.tool_output_summary || "")}</pre>
      <h3>Data</h3>
      <pre>${escapeHtml(JSON.stringify(item.tool_output_data || {}, null, 2))}</pre>
    `;
    return;
  }

  if (tab === "errors") {
    root.innerHTML = `
      <h3>Validation Error</h3>
      <pre>${escapeHtml(JSON.stringify(item.validation_error || {}, null, 2))}</pre>
      <h3>Execution Error</h3>
      <pre>${escapeHtml(JSON.stringify(item.execution_error || {}, null, 2))}</pre>
    `;
    return;
  }

  if (tab === "files") {
    const files = item.files || {};
    const entries = Object.entries(files);
    if (!entries.length) {
      root.innerHTML = `<div class="empty">No files available.</div>`;
      return;
    }
    root.innerHTML = entries.map(([name, path]) => `
      <div class="file-row">
        <button onclick="openFile('${name}')">${escapeHtml(name)}</button>
        <span>${escapeHtml(path)}</span>
      </div>
    `).join("");
    return;
  }
}

async function openFile(name) {
  const res = await fetch(`/api/file/${encodeURIComponent(name)}`);
  const text = await res.text();
  state.currentTab = "summary";
  document.querySelectorAll(".tab-btn[data-tab]").forEach(btn => btn.classList.remove("active"));
  document.querySelector(`.tab-btn[data-tab="summary"]`).classList.add("active");
  document.getElementById("detailContent").innerHTML = `<h3>${escapeHtml(name)}</h3><pre>${escapeHtml(text)}</pre>`;
}

function renderDesign() {
  const root = document.getElementById("designContent");
  if (state.currentDesignTab === "verilog") {
    root.innerHTML = `<pre>${escapeHtml(state.verilog || "")}</pre>`;
    return;
  }
  root.innerHTML = `
    <div class="graph-placeholder">
      <div class="graph-title">Graph Viewer</div>
      <div class="wip">Work in Progress</div>
      <div class="wip-sub">Will be added after Yosys integration.</div>
    </div>
  `;
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function attachTabHandlers() {
  document.querySelectorAll(".tab-btn[data-tab]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn[data-tab]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.currentTab = btn.dataset.tab;
      renderDetail();
    });
  });

  document.querySelectorAll(".tab-btn[data-design-tab]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn[data-design-tab]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.currentDesignTab = btn.dataset.designTab;
      renderDesign();
    });
  });
}

document.getElementById("configureBtn").addEventListener("click", configureSession);
document.getElementById("resetBtn").addEventListener("click", resetSession);
document.getElementById("sendBtn").addEventListener("click", runRequest);

attachTabHandlers();
refreshState().catch(console.error);
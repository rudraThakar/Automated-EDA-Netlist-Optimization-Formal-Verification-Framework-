let state = {
  timeline: [],
  selectedIndex: null,
  currentTab: "overview",
  currentDesignTab: "verilog",
  verilog: "",
  graph: { status: "empty", message: "No design loaded.", nodes: [], edges: [] },
  metrics: {},
  verificationPolicy: "permissive",
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
    verification_policy: document.getElementById("verificationPolicy").value,
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
  state.graph = data.graph || { status: "empty", message: "No design loaded.", nodes: [], edges: [] };
  state.metrics = data.metrics || {};
  state.verificationPolicy = data.verification_policy || "permissive";

  document.getElementById("plannerStatus").textContent = `Planner: ${data.planner_class || "-"}`;
  document.getElementById("caseStatus").textContent = `Case: ${data.case_name || "-"}`;
  document.getElementById("designStatus").textContent = `Design: ${data.design_loaded || "-"}`;
  document.getElementById("policyStatus").textContent = `Policy: ${state.verificationPolicy}`;
  document.getElementById("verificationPolicy").value = state.verificationPolicy;

  if (state.selectedIndex === null && state.timeline.length > 0) {
    state.selectedIndex = state.timeline.length - 1;
  }

  renderAll();
}

function renderAll() {
  renderTimeline();
  renderMetricsStrip();
  renderDetail();
  renderDesign();
}

function renderMetricsStrip() {
  const root = document.getElementById("metricsStrip");
  const m = state.metrics || {};
  const metrics = [
    ["Module", m.module || "-"],
    ["Gates", m.instances ?? 0],
    ["Nets", m.nets ?? 0],
    ["Inputs", m.inputs ?? 0],
    ["Outputs", m.outputs ?? 0],
    ["Max depth", m.max_depth ?? "-"],
    ["Max fanout", `${m.max_fanout ?? 0}${m.max_fanout_net ? ` @ ${m.max_fanout_net}` : ""}`],
    ["Last tool", m.last_tool || "-"],
  ];
  root.innerHTML = metrics.map(([label, value]) => `
    <div class="metric-tile">
      <div class="metric-label">${escapeHtml(label)}</div>
      <div class="metric-value">${escapeHtml(value)}</div>
    </div>
  `).join("");
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
  if (tab === "overview") {
    const tool = item.validated_tool || {};
    const output = item.tool_output_data || {};
    root.innerHTML = `
      <div class="overview-grid">
        ${summaryBlock("Request", item.request_text || "-")}
        ${summaryBlock("Validated Tool", tool.tool || "-")}
        ${summaryBlock("Verification", formatEquivalent(output.equivalent))}
        ${summaryBlock("Frontend", output.frontend || state.metrics.last_frontend || "-")}
      </div>
      <h3>Response</h3>
      <pre>${escapeHtml(item.response || item.tool_output_summary || "")}</pre>
    `;
    return;
  }

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
    root.innerHTML = state.verilog
      ? `<pre>${escapeHtml(state.verilog)}</pre>`
      : `<div class="empty">No design loaded.</div>`;
    return;
  }

  if (state.currentDesignTab === "metrics") {
    root.innerHTML = `<pre>${escapeHtml(JSON.stringify(state.metrics || {}, null, 2))}</pre>`;
    return;
  }

  root.innerHTML = renderGraphSvg(state.graph || {});
}

function renderGraphSvg(graph) {
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  if (!nodes.length) {
    return `<div class="empty">${escapeHtml(graph.message || "No graph available.")}</div>`;
  }

  const lane = { input: 80, gate: 270, net: 460, output: 650 };
  const counters = { input: 0, gate: 0, net: 0, output: 0 };
  const positions = {};
  nodes.forEach((node) => {
    const kind = lane[node.kind] === undefined ? "net" : node.kind;
    const y = 60 + counters[kind] * 58;
    counters[kind] += 1;
    positions[node.id] = { x: lane[kind], y, kind };
  });

  const height = Math.max(360, 120 + Math.max(...Object.values(counters)) * 58);
  const edgeMarkup = edges.map((edge) => {
    const s = positions[edge.source];
    const t = positions[edge.target];
    if (!s || !t) return "";
    const mid = (s.x + t.x) / 2;
    return `<path class="graph-edge" d="M${s.x + 44},${s.y} C${mid},${s.y} ${mid},${t.y} ${t.x - 44},${t.y}" />`;
  }).join("");

  const nodeMarkup = nodes.map((node) => {
    const p = positions[node.id];
    const label = escapeHtml(node.label || node.id).replaceAll("\\n", " ");
    return `
      <g class="graph-node ${escapeHtml(p.kind)}">
        <rect x="${p.x - 44}" y="${p.y - 18}" width="88" height="36" rx="6" />
        <text x="${p.x}" y="${p.y + 4}">${label.slice(0, 18)}</text>
      </g>
    `;
  }).join("");

  return `
    <div class="graph-header">${escapeHtml(graph.message || "")}</div>
    <svg class="graph-svg" viewBox="0 0 730 ${height}" role="img" aria-label="Netlist graph">
      <defs>
        <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 z"></path>
        </marker>
      </defs>
      ${edgeMarkup}
      ${nodeMarkup}
    </svg>
  `;
}

function summaryBlock(label, value) {
  return `
    <div class="summary-block">
      <div class="metric-label">${escapeHtml(label)}</div>
      <div class="summary-value">${escapeHtml(value)}</div>
    </div>
  `;
}

function formatEquivalent(value) {
  if (value === true) return "proved";
  if (value === false) return "failed";
  if (value === null || value === undefined) return "-";
  return String(value);
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

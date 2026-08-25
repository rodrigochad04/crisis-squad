"""Dashboard HTML — redesenhado para clareza.

Design principles:
- Fluxo vertical top-down: o usuário lê de cima pra baixo como uma história
- Linguagem humana: sem jargão técnico exposto desnecessariamente
- Uma ação por vez: o botão principal muda conforme o estado
- Métricas visíveis sem precisar de abas
- O HitL gate é o momento dramático central — destaque máximo
"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agentic SRE — Incident Response</title>
<style>
:root {
  --bg:      #f6f8fa;
  --surface: #ffffff;
  --border:  #d0d7de;
  --border2: #e6eaef;
  --text:    #1f2328;
  --muted:   #636c76;
  --accent:  #0969da;
  --green:   #1a7f37;
  --green-bg:#dafbe1;
  --red:     #cf222e;
  --red-bg:  #ffebe9;
  --yellow:  #9a6700;
  --yellow-bg:#fff8c5;
  --blue-bg: #ddf4ff;
  --purple:  #8250df;
  --purple-bg:#fbefff;
  --shadow:  0 1px 3px rgba(0,0,0,.08), 0 0 0 1px rgba(0,0,0,.04);
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: -apple-system,"Segoe UI",sans-serif; font-size: 14px; line-height: 1.6; }

/* ── Header ─────────────────────────────────────────────── */
.header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0 32px;
  height: 56px;
  display: flex;
  align-items: center;
  gap: 12px;
  position: sticky;
  top: 0;
  z-index: 100;
}
.header-logo { font-size: 16px; font-weight: 700; color: var(--text); }
.header-sub  { font-size: 12px; color: var(--muted); }
.header-right { margin-left: auto; display: flex; gap: 8px; align-items: center; }
.pill {
  font-size: 11px; font-weight: 600; padding: 3px 10px;
  border-radius: 20px; letter-spacing: .3px;
}
.pill-demo   { background: var(--yellow-bg); color: var(--yellow); border: 1px solid #d4a72c; }
.pill-idle   { background: var(--border2); color: var(--muted); }
.pill-running{ background: var(--blue-bg); color: var(--accent); }
.pill-done   { background: var(--green-bg); color: var(--green); }
.pill-waiting{ background: var(--yellow-bg); color: var(--yellow); }
.header-link { font-size: 12px; color: var(--muted); text-decoration: none; padding: 4px 8px; border-radius: 6px; }
.header-link:hover { background: var(--border2); color: var(--text); }

/* ── Main layout ────────────────────────────────────────── */
.main { max-width: 900px; margin: 0 auto; padding: 32px 20px 80px; }

/* ── Trigger card ───────────────────────────────────────── */
.trigger-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px;
  box-shadow: var(--shadow);
  margin-bottom: 28px;
}
.trigger-title { font-size: 18px; font-weight: 700; margin-bottom: 4px; }
.trigger-sub   { font-size: 13px; color: var(--muted); margin-bottom: 20px; }
.trigger-row   { display: flex; gap: 10px; align-items: center; }
.trigger-input {
  flex: 1; padding: 10px 14px;
  border: 1px solid var(--border); border-radius: 8px;
  font-size: 13px; font-family: monospace;
  background: var(--bg); color: var(--text); outline: none;
}
.trigger-input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(9,105,218,.15); }
.btn {
  border: none; border-radius: 8px; cursor: pointer;
  font-size: 13px; font-weight: 600; padding: 10px 20px;
  transition: opacity .15s; white-space: nowrap;
}
.btn:hover:not(:disabled) { opacity: .85; }
.btn:disabled { opacity: .4; cursor: not-allowed; }
.btn-primary { background: var(--accent); color: #fff; }
.btn-green   { background: var(--green); color: #fff; }
.btn-red     { background: var(--red); color: #fff; }
.btn-ghost   { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
.trigger-hint { font-size: 12px; color: var(--muted); margin-top: 10px; }
.trigger-hint code { background: var(--border2); padding: 1px 5px; border-radius: 4px; font-family: monospace; }

/* ── Progress bar ───────────────────────────────────────── */
.progress-wrap { margin-bottom: 28px; display: none; }
.progress-wrap.show { display: block; }
.progress-label { font-size: 12px; color: var(--muted); margin-bottom: 6px; display: flex; justify-content: space-between; }
.progress-bar-outer { background: var(--border2); border-radius: 8px; height: 6px; overflow: hidden; }
.progress-bar-inner { background: var(--accent); height: 100%; border-radius: 8px; transition: width .4s ease; }

/* ── Section title ──────────────────────────────────────── */
.section-label {
  font-size: 11px; font-weight: 700; color: var(--muted);
  text-transform: uppercase; letter-spacing: 1px;
  margin-bottom: 12px; margin-top: 32px;
  display: flex; align-items: center; gap: 8px;
}
.section-label::after {
  content: ''; flex: 1; height: 1px; background: var(--border2);
}

/* ── Phase pipeline ─────────────────────────────────────── */
.pipeline { display: flex; flex-direction: column; gap: 8px; margin-bottom: 28px; }

.phase-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  transition: border-color .2s, box-shadow .2s;
}
.phase-card.state-running {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(9,105,218,.12);
}
.phase-card.state-done { border-color: #57ab5a; }
.phase-card.state-blocked {
  border-color: #d4a72c;
  box-shadow: 0 0 0 3px rgba(212,167,44,.15);
}

.phase-header {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; cursor: default;
}
.phase-icon-wrap {
  width: 32px; height: 32px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; flex-shrink: 0;
  background: var(--border2);
}
.state-running  .phase-icon-wrap { background: var(--blue-bg); }
.state-done     .phase-icon-wrap { background: var(--green-bg); }
.state-blocked  .phase-icon-wrap { background: var(--yellow-bg); }
.state-error    .phase-icon-wrap { background: var(--red-bg); }

.phase-info { flex: 1; min-width: 0; }
.phase-name { font-weight: 600; font-size: 13px; }
.phase-desc { font-size: 12px; color: var(--muted); }

.phase-status { flex-shrink: 0; }
.status-badge {
  font-size: 11px; font-weight: 700; padding: 3px 10px;
  border-radius: 20px; letter-spacing: .3px;
}
.badge-waiting  { background: var(--border2); color: var(--muted); }
.badge-running  { background: var(--blue-bg); color: var(--accent); }
.badge-done     { background: var(--green-bg); color: var(--green); }
.badge-blocked  { background: var(--yellow-bg); color: var(--yellow); }
.badge-error    { background: var(--red-bg); color: var(--red); }

/* Phase connector line */
.phase-connector {
  width: 2px; height: 12px; background: var(--border2);
  margin: 0 auto; margin-left: 27px;
}
.phase-connector.done { background: #57ab5a; }

/* Phase result panel */
.phase-result {
  border-top: 1px solid var(--border2);
  padding: 12px 16px;
  display: none;
  background: var(--bg);
}
.phase-result.show { display: block; }
.result-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.result-item { }
.result-label { font-size: 11px; color: var(--muted); margin-bottom: 2px; }
.result-value { font-size: 13px; font-weight: 600; }
.val-red    { color: var(--red); }
.val-green  { color: var(--green); }
.val-yellow { color: var(--yellow); }
.val-blue   { color: var(--accent); }
.val-mono   { font-family: monospace; }

/* ── HitL gate (the moment) ─────────────────────────────── */
.hitl-gate {
  background: var(--surface);
  border: 2px solid #d4a72c;
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 28px;
  display: none;
  box-shadow: 0 0 0 4px rgba(212,167,44,.1);
}
.hitl-gate.show { display: block; }
.hitl-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.hitl-icon { font-size: 28px; }
.hitl-title { font-size: 17px; font-weight: 700; }
.hitl-subtitle { font-size: 13px; color: var(--muted); margin-top: 2px; }

.hitl-body { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
.hitl-section-title { font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .8px; margin-bottom: 8px; }
.hitl-action-box {
  background: var(--red-bg); border: 1px solid #ffcecb;
  border-radius: 8px; padding: 12px;
}
.hitl-action-box code {
  display: block; font-family: monospace; font-size: 12px;
  color: var(--red); margin-top: 6px; line-height: 1.8;
}
.hitl-evidence-box {
  background: var(--blue-bg); border: 1px solid #b6e0fe;
  border-radius: 8px; padding: 12px;
}
.hitl-evidence-item { font-size: 12px; margin-bottom: 4px; display: flex; gap: 6px; }
.hitl-evidence-item::before { content: '→'; color: var(--accent); flex-shrink: 0; }

.hitl-approve-row {
  display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap;
}
.hitl-name-wrap { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 160px; }
.hitl-name-label { font-size: 11px; color: var(--muted); font-weight: 600; }
.hitl-name-input {
  padding: 9px 12px; border: 1px solid var(--border); border-radius: 8px;
  font-size: 13px; background: var(--surface); color: var(--text); outline: none;
  width: 100%;
}
.hitl-name-input:focus { border-color: var(--accent); }
.hitl-btns { display: flex; gap: 8px; }
.nist-badge {
  margin-top: 12px; padding: 8px 12px;
  background: var(--purple-bg); border: 1px solid #cfb9f5;
  border-radius: 8px; font-size: 11px; color: var(--purple);
  display: flex; align-items: center; gap: 6px;
}

/* ── Result summary ─────────────────────────────────────── */
.summary-card {
  background: var(--surface);
  border: 1px solid #57ab5a;
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 28px;
  display: none;
}
.summary-card.show { display: block; }
.summary-header { display: flex; align-items: center; gap: 10px; margin-bottom: 20px; }
.summary-title { font-size: 17px; font-weight: 700; }
.summary-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
.summary-item {
  background: var(--bg); border: 1px solid var(--border2);
  border-radius: 8px; padding: 12px;
}
.summary-item-label { font-size: 11px; color: var(--muted); margin-bottom: 4px; }
.summary-item-value { font-size: 14px; font-weight: 700; }

/* ── Metrics row ────────────────────────────────────────── */
.metrics-row {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
  margin-bottom: 28px;
}
.metric-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 16px; text-align: center;
}
.metric-number { font-size: 28px; font-weight: 800; letter-spacing: -1px; }
.metric-label  { font-size: 11px; color: var(--muted); margin-top: 2px; font-weight: 600; text-transform: uppercase; letter-spacing: .5px; }
.metric-target { font-size: 11px; margin-top: 4px; }

/* ── Playbook ───────────────────────────────────────────── */
.playbook-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; overflow: hidden; margin-bottom: 28px;
  display: none;
}
.playbook-card.show { display: block; }
.playbook-header {
  padding: 14px 18px; border-bottom: 1px solid var(--border2);
  display: flex; align-items: center; gap: 8px;
  background: var(--bg);
}
.playbook-title { font-weight: 700; font-size: 13px; }
.playbook-body {
  padding: 18px; font-family: monospace; font-size: 12px;
  line-height: 1.8; white-space: pre-wrap; color: #1f2328;
  max-height: 400px; overflow-y: auto;
  background: #f9fafb;
}

/* ── Audit log ──────────────────────────────────────────── */
.audit-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; overflow: hidden; margin-bottom: 28px;
}
.audit-header { padding: 12px 18px; border-bottom: 1px solid var(--border2); background: var(--bg); display: flex; align-items: center; gap: 8px; }
.audit-title  { font-weight: 700; font-size: 13px; }
.audit-body   { padding: 8px; max-height: 200px; overflow-y: auto; }
.audit-entry  {
  display: flex; gap: 10px; padding: 6px 10px; border-radius: 6px;
  font-size: 12px; margin-bottom: 2px;
}
.audit-entry:hover { background: var(--bg); }
.audit-time  { color: var(--muted); font-family: monospace; flex-shrink: 0; min-width: 80px; }
.audit-dot   { width: 8px; height: 8px; border-radius: 50%; margin-top: 5px; flex-shrink: 0; }
.dot-blue   { background: var(--accent); }
.dot-green  { background: var(--green); }
.dot-yellow { background: var(--yellow); }
.dot-red    { background: var(--red); }
.dot-purple { background: var(--purple); }
.audit-msg  { color: var(--text); }

/* ── Spinner ─────────────────────────────────────────────── */
.spin { display: inline-block; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg) } }

/* ── Footer links ────────────────────────────────────────── */
.footer-links {
  display: flex; gap: 20px; flex-wrap: wrap;
  padding: 20px 0; border-top: 1px solid var(--border2);
  font-size: 12px; color: var(--muted);
}
.footer-link { color: var(--muted); text-decoration: none; }
.footer-link:hover { color: var(--accent); }
</style>
</head>
<body>

<!-- ── Header ──────────────────────────────────────────────────────── -->
<div class="header">
  <div>
    <div class="header-logo">⚡ Agentic SRE</div>
  </div>
  <span class="pill pill-demo">DEMO MODE</span>
  <div class="header-right">
    <span class="pill pill-idle" id="status-pill">Idle</span>
    <a href="/metrics" class="header-link">Metrics</a>
    <a href="/docs" target="_blank" class="header-link">API docs ↗</a>
  </div>
</div>

<!-- ── Main ────────────────────────────────────────────────────────── -->
<div class="main">

  <!-- Trigger -->
  <div class="trigger-card">
    <div class="trigger-title">Respond to an incident</div>
    <div class="trigger-sub">
      Paste an Instana alert ID and click Run. The system will diagnose,
      build a remediation playbook, and wait for your approval before
      touching production.
    </div>
    <div class="trigger-row">
      <input class="trigger-input" id="incident-id-input"
             value="QKTtAivDTAaKvCGqvQOWpA"
             placeholder="Instana event ID"/>
      <button class="btn btn-primary" id="trigger-btn" onclick="triggerIncident()">
        ▶ Run response
      </button>
    </div>
    <div class="trigger-hint">
      Demo uses real incident data from a Robot-Shop-EKS PoC —
      no external credentials needed.
      Event: <code>QKTtAivDTAaKvCGqvQOWpA</code>
    </div>
  </div>

  <!-- Progress bar -->
  <div class="progress-wrap" id="progress-wrap">
    <div class="progress-label">
      <span id="progress-label-text">Starting…</span>
      <span id="progress-label-pct">0%</span>
    </div>
    <div class="progress-bar-outer">
      <div class="progress-bar-inner" id="progress-bar" style="width:0%"></div>
    </div>
  </div>

  <!-- HitL gate — shown when approval needed -->
  <div class="hitl-gate" id="hitl-gate">
    <div class="hitl-header">
      <span class="hitl-icon">🛑</span>
      <div>
        <div class="hitl-title">Production action requires your approval</div>
        <div class="hitl-subtitle">
          The system has diagnosed the incident and prepared a remediation plan.
          Review and approve before anything runs in production.
        </div>
      </div>
    </div>

    <div class="hitl-body">
      <div>
        <div class="hitl-section-title">What will happen if you approve</div>
        <div class="hitl-action-box">
          <strong>ROLLBACK</strong> — Risk: <span style="color:var(--red);font-weight:700">HIGH</span>
          <code id="hitl-command">kubectl rollout undo deployment/mcp-gateway -n mcp-context-forge
kubectl rollout status deployment/mcp-gateway --timeout=120s</code>
        </div>
      </div>
      <div>
        <div class="hitl-section-title">Why the system recommends this</div>
        <div class="hitl-evidence-box">
          <div class="hitl-evidence-item">100% error rate — FAIL_FAST pattern detected</div>
          <div class="hitl-evidence-item">p99 latency: 8ms vs 142ms baseline (calls rejected instantly)</div>
          <div class="hitl-evidence-item">KAN-142: same pattern, resolved with rollback in 28 min</div>
          <div class="hitl-evidence-item">KAN-118: same pattern, config rollback resolved in 45 min</div>
        </div>
      </div>
    </div>

    <div class="hitl-approve-row">
      <div class="hitl-name-wrap">
        <label class="hitl-name-label">Your name (for the audit record)</label>
        <input class="hitl-name-input" id="sre-name" value="sre-lead-demo" placeholder="Your name"/>
      </div>
      <div class="hitl-btns">
        <button class="btn btn-green" onclick="approve('APPROVED')">✅ Approve</button>
        <button class="btn btn-red"   onclick="approve('REJECTED')">✗ Reject</button>
      </div>
    </div>

    <div class="nist-badge">
      🔒 <strong>NIST AI RMF</strong> — this gate is structurally enforced.
      The workflow cannot proceed without a recorded human decision.
      Approval ID: <span id="hitl-approval-id" style="font-family:monospace;margin-left:4px"></span>
    </div>
  </div>

  <!-- Resolved banner -->
  <div class="summary-card" id="summary-card">
    <div class="summary-header">
      <span style="font-size:24px" id="summary-icon">✅</span>
      <div>
        <div class="summary-title" id="summary-title">Incident resolved</div>
        <div style="font-size:13px;color:var(--muted)" id="summary-sub"></div>
      </div>
    </div>
    <div class="summary-grid" id="summary-grid"></div>
  </div>

  <!-- Phase pipeline -->
  <div class="section-label">What the system is doing</div>
  <div class="pipeline" id="pipeline"></div>

  <!-- Generated playbook -->
  <div class="playbook-card" id="playbook-card">
    <div class="playbook-header">
      📋 <span class="playbook-title">Remediation Playbook</span>
      <span style="margin-left:auto;font-size:11px;color:var(--muted)">Generated by AI · Review before executing</span>
    </div>
    <div class="playbook-body" id="playbook-body">—</div>
  </div>

  <!-- DORA metrics -->
  <div class="section-label">Productivity metrics</div>
  <div class="metrics-row">
    <div class="metric-card">
      <div class="metric-number" id="m-mttr" style="color:var(--green)">—</div>
      <div class="metric-label">MTTR</div>
      <div class="metric-target" id="m-mttr-sub" style="color:var(--muted)">target ≤ 30 min</div>
    </div>
    <div class="metric-card">
      <div class="metric-number" id="m-total" style="color:var(--accent)">0</div>
      <div class="metric-label">Incidents</div>
      <div class="metric-target" id="m-resolved-sub" style="color:var(--muted)">0 resolved</div>
    </div>
    <div class="metric-card">
      <div class="metric-number" id="m-approval" style="color:var(--purple)">—</div>
      <div class="metric-label">Approval rate</div>
      <div class="metric-target" style="color:var(--muted)">APPROVED / total</div>
    </div>
    <div class="metric-card">
      <div class="metric-number" id="m-agents" style="color:var(--yellow)">0</div>
      <div class="metric-label">Agents / incident</div>
      <div class="metric-target" style="color:var(--muted)">SPACE · Collaboration</div>
    </div>
  </div>

  <!-- Audit log -->
  <div class="section-label">Event log</div>
  <div class="audit-card">
    <div class="audit-header">
      🔏 <span class="audit-title">Audit trail</span>
      <span style="margin-left:auto;font-size:11px;color:var(--muted)">Every event recorded · tamper-evident</span>
    </div>
    <div class="audit-body" id="audit-body">
      <div class="audit-entry">
        <span class="audit-time">—</span>
        <span class="audit-dot dot-blue"></span>
        <span class="audit-msg" style="color:var(--muted)">Waiting for incident trigger…</span>
      </div>
    </div>
  </div>

  <!-- Footer -->
  <div class="footer-links">
    <span>Built with</span>
    <a href="https://langchain-ai.github.io/langgraph/" target="_blank" class="footer-link">LangGraph</a>
    <a href="https://faiss.ai/" target="_blank" class="footer-link">FAISS</a>
    <a href="https://github.com/facebookresearch/faiss" target="_blank" class="footer-link">FAISS</a>
    <a href="https://docs.confident-ai.com/" target="_blank" class="footer-link">DeepEval</a>
    <a href="https://opentelemetry.io/" target="_blank" class="footer-link">OpenTelemetry</a>
    <a href="__REPO_URL__" target="_blank" class="footer-link">GitHub ↗</a>
  </div>

</div><!-- /main -->

<script>
const API = '';
let currentRunId = null;
let eventSource  = null;

// ── Phase definitions ────────────────────────────────────────────────────
const PHASES = [
  { id:'instana',        icon:'🔍', name:'Diagnose incident',
    desc:'Query IBM Instana — error rate, latency, blast radius, root cause' },
  { id:'jira',           icon:'📋', name:'Find historical precedents',
    desc:'Search Jira for similar past incidents and their resolutions' },
  { id:'rag',            icon:'📚', name:'Retrieve runbooks',
    desc:'Search knowledge base (FAISS) for relevant runbooks and postmortems' },
  { id:'playbook',       icon:'📝', name:'Generate remediation playbook',
    desc:'LLM compiles diagnosis + history + runbook into a step-by-step plan' },
  { id:'teams',          icon:'💬', name:'Open war room',
    desc:'Create Microsoft Teams channel and post the playbook' },
  { id:'hitl',           icon:'🛑', name:'Request your approval',
    desc:'No production action runs without explicit human sign-off' },
  { id:'record_decision',icon:'🔏', name:'Record decision',
    desc:'Store the approval or rejection in the audit trail' },
];

const PHASE_COUNT = PHASES.length;
let doneCount = 0;

// ── Build pipeline HTML ──────────────────────────────────────────────────
function buildPipeline() {
  doneCount = 0;
  const el = document.getElementById('pipeline');
  el.innerHTML = PHASES.map((p, i) => `
    ${i > 0 ? `<div class="phase-connector" id="conn-${i}"></div>` : ''}
    <div class="phase-card" id="pc-${p.id}">
      <div class="phase-header">
        <div class="phase-icon-wrap" id="pi-${p.id}">${p.icon}</div>
        <div class="phase-info">
          <div class="phase-name">${p.name}</div>
          <div class="phase-desc">${p.desc}</div>
        </div>
        <div class="phase-status">
          <span class="status-badge badge-waiting" id="pb-${p.id}">Waiting</span>
        </div>
      </div>
      <div class="phase-result" id="pr-${p.id}"></div>
    </div>`
  ).join('');
}

function setPhaseState(phaseId, state, resultHTML) {
  const card   = document.getElementById(`pc-${phaseId}`);
  const badge  = document.getElementById(`pb-${phaseId}`);
  const result = document.getElementById(`pr-${phaseId}`);
  if (!card) return;

  card.className  = `phase-card state-${state}`;
  const badgeMap  = { waiting:'badge-waiting', running:'badge-running', done:'badge-done', blocked:'badge-blocked', error:'badge-error' };
  const labelMap  = { waiting:'Waiting', running:'<span class="spin">⟳</span> Running…', done:'✓ Done', blocked:'⏸ Waiting for you', error:'✗ Error' };
  badge.className = `status-badge ${badgeMap[state]}`;
  badge.innerHTML = labelMap[state] || state;

  if (resultHTML) { result.innerHTML = resultHTML; result.classList.add('show'); }

  // connector above this node
  const idx = PHASES.findIndex(p => p.id === phaseId);
  if (idx > 0) {
    const conn = document.getElementById(`conn-${idx}`);
    if (conn && state === 'done') conn.classList.add('done');
  }
}

// ── Result renderers ─────────────────────────────────────────────────────
function renderResult(phaseId, d) {
  if (phaseId === 'instana') return `
    <div class="result-grid">
      <div class="result-item">
        <div class="result-label">Failure pattern</div>
        <div class="result-value val-yellow">${d.pattern || '—'}</div>
      </div>
      <div class="result-item">
        <div class="result-label">Severity</div>
        <div class="result-value val-red">${d.severity || '—'}</div>
      </div>
      <div class="result-item">
        <div class="result-label">Error rate (vs 1.7% baseline)</div>
        <div class="result-value val-red">${d.error_rate}%</div>
      </div>
      <div class="result-item">
        <div class="result-label">p99 latency (vs ${d.latency_baseline}ms baseline)</div>
        <div class="result-value val-red">${d.latency_p99}ms</div>
      </div>
      <div class="result-item">
        <div class="result-label">Services affected</div>
        <div class="result-value">${d.blast_radius} of ${d.services_analyzed}</div>
      </div>
    </div>`;

  if (phaseId === 'jira') return `
    <div class="result-grid">
      <div class="result-item">
        <div class="result-label">Similar past incidents</div>
        <div class="result-value val-green">${d.precedents_found} found</div>
      </div>
      <div class="result-item">
        <div class="result-label">Closest precedent</div>
        <div class="result-value val-blue val-mono">${d.best_precedent || '—'}</div>
      </div>
      <div class="result-item">
        <div class="result-label">Historical resolution time</div>
        <div class="result-value val-green">${d.best_precedent_mttr} min</div>
      </div>
      <div class="result-item">
        <div class="result-label">Ticket created</div>
        <div class="result-value"><a href="${d.ticket_url}" target="_blank" style="color:var(--accent)">${d.ticket_created} ↗</a></div>
      </div>
    </div>`;

  if (phaseId === 'rag') return `
    <div class="result-grid">
      <div class="result-item">
        <div class="result-label">Documents retrieved</div>
        <div class="result-value val-green">${d.docs_retrieved ?? 0}</div>
      </div>
      <div class="result-item">
        <div class="result-label">Most relevant source</div>
        <div class="result-value val-mono" style="font-size:11px">${d.top_source ?? 'n/a'}</div>
      </div>
    </div>
    <div style="font-size:12px;color:var(--muted);margin-top:8px;line-height:1.6">"${(d.excerpt||'').substring(0,140)}…"</div>`;

  if (phaseId === 'playbook') return `
    <div class="result-grid">
      <div class="result-item">
        <div class="result-label">Sections generated</div>
        <div class="result-value val-green">${(d.sections||[]).length} / 6</div>
      </div>
      <div class="result-item">
        <div class="result-label">kubectl commands</div>
        <div class="result-value val-green">${d.has_kubectl ? '✓ included' : '✗ missing'}</div>
      </div>
    </div>
    <div style="font-size:12px;color:var(--muted);margin-top:6px">
      Sections: ${(d.sections||[]).join(' · ')}
    </div>`;

  if (phaseId === 'teams') return `
    <div class="result-grid">
      <div class="result-item">
        <div class="result-label">War room channel</div>
        <div class="result-value"><a href="${d.channel_url}" target="_blank" style="color:var(--accent)">${d.channel_name} ↗</a></div>
      </div>
      <div class="result-item">
        <div class="result-label">Playbook posted</div>
        <div class="result-value val-green">${d.playbook_posted ? '✓ yes' : '✗ no'}</div>
      </div>
    </div>`;

  if (phaseId === 'hitl') return `
    <div style="font-size:12px;color:var(--yellow)">
      ⏸ Workflow paused — awaiting your decision above
    </div>`;

  if (phaseId === 'record_decision') return `
    <div class="result-grid">
      <div class="result-item">
        <div class="result-label">Decision</div>
        <div class="result-value ${d.decision === 'APPROVED' ? 'val-green' : 'val-red'}">${d.decision}</div>
      </div>
      <div class="result-item">
        <div class="result-label">Recorded by</div>
        <div class="result-value">${d.decided_by}</div>
      </div>
    </div>`;

  return '';
}

// ── Trigger ───────────────────────────────────────────────────────────────
async function triggerIncident() {
  const incId = document.getElementById('incident-id-input').value.trim();
  if (!incId) return;

  buildPipeline();
  doneCount = 0;
  document.getElementById('hitl-gate').classList.remove('show');
  document.getElementById('summary-card').classList.remove('show');
  document.getElementById('playbook-card').classList.remove('show');
  document.getElementById('progress-wrap').classList.add('show');
  document.getElementById('trigger-btn').disabled = true;
  setStatus('running', 'Running…');
  if (eventSource) eventSource.close();

  const resp = await fetch(`${API}/incidents`, {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({incident_id: incId})
  });
  const data = await resp.json();
  currentRunId = data.run_id;
  addAudit('Incident triggered', 'blue', `run_id: ${currentRunId}`);

  eventSource = new EventSource(`${API}/incidents/${currentRunId}/stream`);

  eventSource.addEventListener('phase_start', e => {
    const d = JSON.parse(e.data);
    setPhaseState(d.phase, 'running');
    updateProgress(d.phase, false);
    addAudit(PHASES.find(p=>p.id===d.phase)?.name || d.phase, 'blue');
  });

  eventSource.addEventListener('phase_complete', e => {
    const d = JSON.parse(e.data);
    setPhaseState(d.phase, 'done', renderResult(d.phase, d.result));
    doneCount++;
    updateProgress(d.phase, true);
    if (d.phase === 'playbook') loadPlaybook();
    addAudit((PHASES.find(p=>p.id===d.phase)?.name || d.phase) + ' — done', 'green');
  });

  eventSource.addEventListener('awaiting_approval', e => {
    const d = JSON.parse(e.data);
    setPhaseState('hitl', 'blocked', renderResult('hitl', {}));
    document.getElementById('hitl-approval-id').textContent = d.approval_id || '';
    document.getElementById('hitl-gate').classList.add('show');
    document.getElementById('trigger-btn').disabled = false;
    setStatus('waiting', 'Waiting for approval');
    updateProgress('hitl', true);
    addAudit('Waiting for your approval', 'yellow');
    // scroll to gate
    document.getElementById('hitl-gate').scrollIntoView({behavior:'smooth', block:'center'});
  });

  eventSource.addEventListener('resolved', e => {
    const d = JSON.parse(e.data);
    setPhaseState('record_decision', 'done', renderResult('record_decision', {
      decision: d.decision, decided_by: d.decided_by
    }));
    document.getElementById('hitl-gate').classList.remove('show');
    showSummary(d);
    setStatus(d.decision === 'APPROVED' ? 'done' : 'idle',
              d.decision === 'APPROVED' ? 'Resolved' : 'Rejected');
    updateProgress('record_decision', true);
    addAudit(`Decision: ${d.decision} by ${d.decided_by}`,
             d.decision === 'APPROVED' ? 'green' : 'red');
    eventSource.close();
    loadDORA();
  });

  // Custom 'error' event sent by the server (JSON payload with .error field)
  eventSource.addEventListener('error', e => {
    if (!e.data) return; // network close after awaiting_approval — not a real error
    try {
      const d = JSON.parse(e.data);
      addAudit('Error: ' + (d.error || 'unknown'), 'red');
      document.getElementById('trigger-btn').disabled = false;
      setStatus('idle', 'Error');
    } catch (_) {}
    eventSource.close();
  });

  // Native EventSource connection error (network close, server restart, etc.)
  eventSource.onerror = () => {
    // If we are already in awaiting_approval state, the server closed the stream
    // intentionally — this is NOT an error, just the SSE stream ending normally.
    const phase = document.getElementById('status-pill').textContent;
    if (phase === 'Waiting for approval') return; // expected close — ignore
    eventSource.close();
  };
}

// ── Approve ───────────────────────────────────────────────────────────────
async function approve(decision) {
  if (!currentRunId) return;
  const sre = document.getElementById('sre-name').value.trim() || 'sre-demo';
  await fetch(`${API}/incidents/${currentRunId}/approve`, {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({decision, decided_by: sre, notes: `Demo: ${decision}`})
  });
  addAudit(`${decision} submitted by ${sre}`, decision === 'APPROVED' ? 'green' : 'red');
}

// ── Progress ──────────────────────────────────────────────────────────────
function updateProgress(phaseId, done) {
  const idx = PHASES.findIndex(p => p.id === phaseId);
  const pct  = Math.round(((done ? idx + 1 : idx) / PHASE_COUNT) * 100);
  document.getElementById('progress-bar').style.width = pct + '%';
  document.getElementById('progress-label-pct').textContent = pct + '%';
  const phase = PHASES[idx];
  document.getElementById('progress-label-text').textContent =
    done ? `✓ ${phase?.name}` : `${phase?.name}…`;
}

// ── Playbook ──────────────────────────────────────────────────────────────
async function loadPlaybook() {
  if (!currentRunId) return;
  const r = await fetch(`${API}/incidents/${currentRunId}/playbook`);
  const d = await r.json();
  const pb = d.playbook || '';
  if (pb) {
    document.getElementById('playbook-body').textContent = pb;
    document.getElementById('playbook-card').classList.add('show');
  }
}

// ── Summary ───────────────────────────────────────────────────────────────
function showSummary(d) {
  const card = document.getElementById('summary-card');
  document.getElementById('summary-icon').textContent = d.decision === 'APPROVED' ? '✅' : '🚫';
  document.getElementById('summary-title').textContent =
    d.decision === 'APPROVED' ? 'Incident resolved — action approved' : 'Action rejected';
  document.getElementById('summary-sub').textContent =
    `Decision by ${d.decided_by} · Audit entry recorded`;
  document.getElementById('summary-grid').innerHTML = `
    <div class="summary-item">
      <div class="summary-item-label">Incident</div>
      <div class="summary-item-value" style="font-size:11px;font-family:monospace">${document.getElementById('incident-id-input').value.substring(0,16)}…</div>
    </div>
    <div class="summary-item">
      <div class="summary-item-label">Decision</div>
      <div class="summary-item-value" style="color:${d.decision==='APPROVED'?'var(--green)':'var(--red)'}">${d.decision}</div>
    </div>
    <div class="summary-item">
      <div class="summary-item-label">Decided by</div>
      <div class="summary-item-value">${d.decided_by}</div>
    </div>`;
  card.classList.add('show');
}

// ── Status pill ───────────────────────────────────────────────────────────
function setStatus(state, label) {
  const el = document.getElementById('status-pill');
  el.textContent = label;
  el.className = `pill pill-${state}`;
}

// ── Audit log ─────────────────────────────────────────────────────────────
function addAudit(msg, color, detail) {
  const body = document.getElementById('audit-body');
  const time = new Date().toLocaleTimeString('en-GB', {hour12:false});
  const dotClass = {blue:'dot-blue', green:'dot-green', yellow:'dot-yellow', red:'dot-red', purple:'dot-purple'}[color] || 'dot-blue';
  const entry = document.createElement('div');
  entry.className = 'audit-entry';
  entry.innerHTML = `
    <span class="audit-time">${time}</span>
    <span class="audit-dot ${dotClass}"></span>
    <span class="audit-msg">${msg}${detail ? `<span style="color:var(--muted);margin-left:6px;font-size:11px;font-family:monospace">${detail}</span>` : ''}</span>`;
  body.appendChild(entry);
  body.scrollTop = body.scrollHeight;
}

// ── DORA metrics ──────────────────────────────────────────────────────────
async function loadDORA() {
  try {
    const r = await fetch(`${API}/metrics/dora`);
    const d = await r.json();
    const mttr    = d.dora?.mttr?.avg_minutes;
    const mttrSec = d.dora?.mttr?.avg_seconds;
    const meets   = mttr != null && mttr <= 30;
    // Show seconds in demo (sub-minute runs), minutes in production
    const mttrDisplay = (mttr != null && mttr < 1 && mttrSec != null)
      ? mttrSec + 's'
      : (mttr != null ? mttr + '' : '—');
    document.getElementById('m-mttr').textContent = mttrDisplay;
    document.getElementById('m-mttr').style.color = meets ? 'var(--green)' : 'var(--yellow)';
    document.getElementById('m-mttr-sub').textContent = meets ? '✓ meets ≤30 min target' : '⚠ above 30 min target';
    document.getElementById('m-total').textContent = d.incidents_tracked || 0;
    document.getElementById('m-resolved-sub').textContent = `${d.incidents_resolved||0} resolved`;
    const ap = d.space?.satisfaction?.approval_rate_pct;
    document.getElementById('m-approval').textContent = ap != null ? ap + '%' : '—';
    const ag = d.space?.collaboration?.avg_agents_per_incident;
    document.getElementById('m-agents').textContent = ag != null ? ag : 0;
  } catch(e) {}
}

// ── Init ──────────────────────────────────────────────────────────────────
buildPipeline();
loadDORA();
setInterval(loadDORA, 8000);
</script>
</body>
</html>
"""

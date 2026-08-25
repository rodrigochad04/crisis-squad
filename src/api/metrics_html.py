"""Metrics dashboard HTML — DORA, SPACE, Traces, Evaluation.

A dedicated page at /metrics that pulls live data from the API
and renders charts + tables without any external dependencies.
All charts are drawn with inline SVG via JavaScript.
"""

METRICS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agentic SRE — Metrics</title>
<style>
:root {
  --bg:       #f6f8fa;
  --surface:  #ffffff;
  --border:   #d0d7de;
  --border2:  #e6eaef;
  --text:     #1f2328;
  --muted:    #636c76;
  --accent:   #0969da;
  --green:    #1a7f37;
  --green-bg: #dafbe1;
  --red:      #cf222e;
  --red-bg:   #ffebe9;
  --yellow:   #9a6700;
  --yellow-bg:#fff8c5;
  --blue-bg:  #ddf4ff;
  --purple:   #8250df;
  --purple-bg:#fbefff;
  --shadow:   0 1px 3px rgba(0,0,0,.08), 0 0 0 1px rgba(0,0,0,.04);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: -apple-system,"Segoe UI",sans-serif; font-size: 14px; line-height: 1.6; }

/* Header */
.header {
  background: var(--surface); border-bottom: 1px solid var(--border);
  padding: 0 32px; height: 56px;
  display: flex; align-items: center; gap: 12px;
  position: sticky; top: 0; z-index: 100;
}
.header-logo { font-size: 16px; font-weight: 700; }
.header-right { margin-left: auto; display: flex; gap: 8px; align-items: center; }
.header-link { font-size: 12px; color: var(--muted); text-decoration: none; padding: 4px 8px; border-radius: 6px; }
.header-link:hover { background: var(--border2); color: var(--text); }
.header-link.active { background: var(--blue-bg); color: var(--accent); font-weight: 600; }
.pill { font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 20px; letter-spacing: .3px; }
.pill-demo { background: var(--yellow-bg); color: var(--yellow); border: 1px solid #d4a72c; }

/* Layout */
.main { max-width: 1000px; margin: 0 auto; padding: 32px 20px 80px; }

/* Section label */
.section-label {
  font-size: 11px; font-weight: 700; color: var(--muted);
  text-transform: uppercase; letter-spacing: 1px;
  margin-bottom: 12px; margin-top: 36px;
  display: flex; align-items: center; gap: 8px;
}
.section-label::after { content: ''; flex: 1; height: 1px; background: var(--border2); }

/* KPI row */
.kpi-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 4px; }
.kpi-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 18px 16px; text-align: center;
  box-shadow: var(--shadow);
}
.kpi-number { font-size: 32px; font-weight: 800; letter-spacing: -1.5px; line-height: 1; }
.kpi-label  { font-size: 11px; color: var(--muted); margin-top: 6px; font-weight: 600; text-transform: uppercase; letter-spacing: .5px; }
.kpi-sub    { font-size: 11px; margin-top: 4px; }
.kpi-good   { color: var(--green); }
.kpi-warn   { color: var(--yellow); }
.kpi-neutral{ color: var(--accent); }
.kpi-purple { color: var(--purple); }

/* Chart card */
.chart-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; overflow: hidden;
  box-shadow: var(--shadow); margin-bottom: 16px;
}
.chart-header {
  padding: 14px 18px; border-bottom: 1px solid var(--border2);
  display: flex; align-items: center; gap: 8px;
  background: var(--bg);
}
.chart-title { font-weight: 700; font-size: 13px; }
.chart-sub   { font-size: 11px; color: var(--muted); margin-left: auto; }
.chart-body  { padding: 20px; }

/* Bar chart */
.bar-chart { display: flex; flex-direction: column; gap: 10px; }
.bar-row   { display: flex; align-items: center; gap: 10px; }
.bar-label { font-size: 12px; color: var(--muted); min-width: 120px; text-align: right; }
.bar-wrap  { flex: 1; background: var(--border2); border-radius: 4px; height: 20px; overflow: hidden; }
.bar-fill  { height: 100%; border-radius: 4px; transition: width .5s ease; display: flex; align-items: center; justify-content: flex-end; padding-right: 6px; }
.bar-val   { font-size: 11px; font-weight: 700; color: #fff; }
.bar-val-out { font-size: 11px; color: var(--muted); min-width: 40px; }

/* Phase timing */
.phase-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.phase-item {
  background: var(--bg); border: 1px solid var(--border2);
  border-radius: 8px; padding: 12px;
}
.phase-item-name  { font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.phase-item-ms    { font-size: 20px; font-weight: 800; color: var(--accent); letter-spacing: -0.5px; }
.phase-item-label { font-size: 11px; color: var(--muted); }

/* Table */
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; font-size: 11px; color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: .5px; padding: 8px 12px; border-bottom: 2px solid var(--border); }
td { padding: 10px 12px; border-bottom: 1px solid var(--border2); vertical-align: top; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: var(--bg); }
.badge { display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 20px; }
.badge-green  { background: var(--green-bg); color: var(--green); }
.badge-red    { background: var(--red-bg); color: var(--red); }
.badge-yellow { background: var(--yellow-bg); color: var(--yellow); }
.badge-blue   { background: var(--blue-bg); color: var(--accent); }
.badge-purple { background: var(--purple-bg); color: var(--purple); }

/* Eval metrics grid */
.eval-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.eval-item {
  background: var(--bg); border: 1px solid var(--border2);
  border-radius: 8px; padding: 14px;
}
.eval-name       { font-size: 13px; font-weight: 700; margin-bottom: 4px; }
.eval-desc       { font-size: 12px; color: var(--muted); margin-bottom: 10px; line-height: 1.5; }
.eval-bar-wrap   { background: var(--border2); border-radius: 4px; height: 8px; overflow: hidden; margin-bottom: 4px; }
.eval-bar-fill   { height: 100%; border-radius: 4px; }
.eval-threshold  { font-size: 11px; color: var(--muted); }

/* Gauge SVG */
.gauge-row { display: flex; justify-content: space-around; flex-wrap: wrap; gap: 20px; padding: 8px 0; }
.gauge-item { text-align: center; }
.gauge-label { font-size: 12px; color: var(--muted); margin-top: 6px; font-weight: 600; }

/* Empty state */
.empty-state { text-align: center; padding: 40px 20px; color: var(--muted); }
.empty-icon  { font-size: 32px; margin-bottom: 10px; }
.empty-text  { font-size: 13px; }
.empty-hint  { font-size: 12px; margin-top: 6px; }

/* Refresh button */
.btn-refresh {
  border: 1px solid var(--border); border-radius: 8px; cursor: pointer;
  font-size: 12px; font-weight: 600; padding: 6px 14px;
  background: var(--surface); color: var(--text); transition: .15s;
}
.btn-refresh:hover { background: var(--bg); }

/* Run eval button */
.btn-run-eval {
  border: 1px solid var(--accent); border-radius: 8px; cursor: pointer;
  font-size: 12px; font-weight: 700; padding: 6px 16px;
  background: var(--accent); color: #fff; transition: .15s;
  white-space: nowrap;
}
.btn-run-eval:hover:not(:disabled) { opacity: .85; }
.btn-run-eval:disabled { opacity: .5; cursor: not-allowed; }

/* Spinner */
.spin { display: inline-block; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg) } }

/* Monospace */
.mono { font-family: monospace; font-size: 12px; }
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <div class="header-logo">⚡ Agentic SRE</div>
  <span class="pill pill-demo">DEMO MODE</span>
  <div class="header-right">
    <a href="/"       class="header-link">Dashboard</a>
    <a href="/metrics" class="header-link active">Metrics</a>
    <a href="/docs"   class="header-link">API docs ↗</a>
    <button class="btn-refresh" onclick="loadAll()">↻ Refresh</button>
  </div>
</div>

<div class="main">

  <!-- Page title -->
  <div style="margin-bottom: 28px;">
    <div style="font-size:22px;font-weight:800;letter-spacing:-.5px">Engineering Productivity Metrics</div>
    <div style="font-size:13px;color:var(--muted);margin-top:4px">
      DORA · SPACE · Phase timing · Evaluation harness — updated live from active incidents
    </div>
  </div>

  <!-- KPI row: top-level numbers -->
  <div class="section-label">At a glance</div>
  <div class="kpi-row" id="kpi-row">
    <div class="kpi-card"><div class="kpi-number kpi-neutral" id="k-total">—</div><div class="kpi-label">Incidents handled</div><div class="kpi-sub" style="color:var(--muted)" id="k-total-sub">this session</div></div>
    <div class="kpi-card"><div class="kpi-number kpi-good"    id="k-mttr">—</div><div class="kpi-label">Avg MTTR</div><div class="kpi-sub" id="k-mttr-sub" style="color:var(--muted)">target ≤ 30 min</div></div>
    <div class="kpi-card"><div class="kpi-number kpi-purple"  id="k-approval">—</div><div class="kpi-label">Approval rate</div><div class="kpi-sub" style="color:var(--muted)">APPROVED / total</div></div>
    <div class="kpi-card"><div class="kpi-number kpi-neutral" id="k-agents">—</div><div class="kpi-label">Agents / incident</div><div class="kpi-sub" style="color:var(--muted)">SPACE · Collaboration</div></div>
  </div>

  <!-- DORA section -->
  <div class="section-label">DORA metrics</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">

    <!-- MTTR over time (bar chart) -->
    <div class="chart-card">
      <div class="chart-header">
        📉 <span class="chart-title">MTTR per incident</span>
        <span class="chart-sub">Mean Time to Recovery</span>
      </div>
      <div class="chart-body" id="mttr-chart">
        <div class="empty-state"><div class="empty-icon">📭</div><div class="empty-text">No incidents yet</div><div class="empty-hint">Trigger one from the <a href="/" style="color:var(--accent)">dashboard</a></div></div>
      </div>
    </div>

    <!-- Decisions pie / summary -->
    <div class="chart-card">
      <div class="chart-header">
        ✅ <span class="chart-title">Human decisions</span>
        <span class="chart-sub">APPROVED vs REJECTED</span>
      </div>
      <div class="chart-body" id="decisions-chart">
        <div class="empty-state"><div class="empty-icon">📭</div><div class="empty-text">No decisions yet</div><div class="empty-hint">Approve or reject an incident first</div></div>
      </div>
    </div>

  </div>

  <!-- Phase timing -->
  <div class="chart-card">
    <div class="chart-header">
      ⏱ <span class="chart-title">Phase durations (most recent incident)</span>
      <span class="chart-sub">Milliseconds per agent node</span>
    </div>
    <div class="chart-body" id="phase-chart">
      <div class="empty-state"><div class="empty-icon">📭</div><div class="empty-text">No phase data yet</div></div>
    </div>
  </div>

  <!-- Incident history table -->
  <div class="section-label">Incident history</div>
  <div class="chart-card">
    <div class="chart-header">
      🗂 <span class="chart-title">All incidents this session</span>
      <span class="chart-sub" id="incident-count">—</span>
    </div>
    <div class="chart-body" style="padding:0">
      <div id="incident-table">
        <div class="empty-state" style="padding:30px"><div class="empty-icon">📭</div><div class="empty-text">No incidents yet</div></div>
      </div>
    </div>
  </div>

  <!-- SPACE section -->
  <div class="section-label">SPACE metrics</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">

    <div class="chart-card">
      <div class="chart-header">🤝 <span class="chart-title">Collaboration</span><span class="chart-sub">Agents per incident</span></div>
      <div class="chart-body" id="space-collab">
        <div class="empty-state"><div class="empty-icon">📭</div><div class="empty-text">No data yet</div></div>
      </div>
    </div>

    <div class="chart-card">
      <div class="chart-header">⚡ <span class="chart-title">Performance vs Target</span><span class="chart-sub">MTTR target = 30 min</span></div>
      <div class="chart-body" id="space-perf">
        <div class="empty-state"><div class="empty-icon">📭</div><div class="empty-text">No data yet</div></div>
      </div>
    </div>

  </div>

  <!-- Evaluation section -->
  <div class="section-label">Evaluation harness — DeepEval</div>
  <div class="chart-card" id="eval-card">
    <div class="chart-header">
      🧪 <span class="chart-title">Quality metrics</span>
      <span class="chart-sub" style="margin-left:auto">
        <button class="btn-run-eval" id="run-eval-btn" onclick="runEval()">
          ▶ Run evaluation
        </button>
      </span>
    </div>
    <div class="chart-body">
      <div class="eval-grid" id="eval-grid">
        <div class="empty-state" style="grid-column:1/-1"><div class="empty-icon"><span class="spin">⟳</span></div></div>
      </div>
      <!-- Live output panel — hidden until Run is clicked -->
      <div id="eval-run-panel" style="display:none;margin-top:16px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <span id="eval-run-status" style="font-size:12px;font-weight:700;color:var(--muted)">Idle</span>
          <span id="eval-run-summary" style="font-size:12px;color:var(--muted)"></span>
        </div>
        <div id="eval-run-output"
             style="background:#0d1117;color:#c9d1d9;font-family:monospace;font-size:11.5px;
                    line-height:1.7;padding:14px 16px;border-radius:8px;
                    max-height:340px;overflow-y:auto;white-space:pre-wrap;"></div>
      </div>
    </div>
  </div>

  <!-- Footer -->
  <div style="padding:20px 0;border-top:1px solid var(--border2);font-size:12px;color:var(--muted);display:flex;gap:20px;flex-wrap:wrap;margin-top:20px">
    <span>Built with</span>
    <a href="https://langchain-ai.github.io/langgraph/" target="_blank" style="color:var(--muted);text-decoration:none">LangGraph</a>
    <a href="https://opentelemetry.io/" target="_blank" style="color:var(--muted);text-decoration:none">OpenTelemetry</a>
    <a href="https://docs.confident-ai.com/" target="_blank" style="color:var(--muted);text-decoration:none">DeepEval</a>
    <a href="__REPO_URL__" target="_blank" style="color:var(--muted);text-decoration:none">GitHub ↗</a>
  </div>

</div>

<script>
const API = '';

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtMttr(min, sec) {
  if (min == null) return '—';
  if (min < 1 && sec != null) return sec + 's';
  return min + ' min';
}

function fmtTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString('en-GB', {hour12: false});
}

function barColor(pct, isGood) {
  if (isGood) return pct >= 80 ? '#1a7f37' : pct >= 50 ? '#9a6700' : '#cf222e';
  return '#0969da';
}

// ── SVG gauge (arc) ────────────────────────────────────────────────────────
function svgGauge(value, max, color, label, size) {
  size = size || 80;
  const r = size * 0.38;
  const cx = size / 2, cy = size / 2;
  const pct = Math.min(value / max, 1);
  // Arc from -135deg to 135deg (270deg sweep)
  const startAngle = -135 * Math.PI / 180;
  const endAngle   = startAngle + pct * 270 * Math.PI / 180;
  const x1 = cx + r * Math.cos(startAngle), y1 = cy + r * Math.sin(startAngle);
  const x2 = cx + r * Math.cos(endAngle),   y2 = cy + r * Math.sin(endAngle);
  const largeArc = pct > 0.5 ? 1 : 0;
  const fullEnd  = startAngle + 270 * Math.PI / 180;
  const fx1 = cx + r * Math.cos(startAngle), fy1 = cy + r * Math.sin(startAngle);
  const fx2 = cx + r * Math.cos(fullEnd),    fy2 = cy + r * Math.sin(fullEnd);
  return `
    <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
      <path d="M${fx1.toFixed(1)},${fy1.toFixed(1)} A${r},${r} 0 1 1 ${fx2.toFixed(1)},${fy2.toFixed(1)}"
            stroke="#e6eaef" stroke-width="${size*0.09}" fill="none" stroke-linecap="round"/>
      ${pct > 0 ? `<path d="M${x1.toFixed(1)},${y1.toFixed(1)} A${r},${r} 0 ${largeArc} 1 ${x2.toFixed(1)},${y2.toFixed(1)}"
            stroke="${color}" stroke-width="${size*0.09}" fill="none" stroke-linecap="round"/>` : ''}
      <text x="${cx}" y="${cy + 5}" text-anchor="middle" font-size="${size*0.18}" font-weight="800" fill="${color}">${label}</text>
    </svg>`;
}

// ── Horizontal bar ─────────────────────────────────────────────────────────
function hBar(label, value, maxVal, color, unit) {
  const pct = maxVal > 0 ? Math.min(value / maxVal * 100, 100) : 0;
  const display = unit ? value + unit : value;
  return `
    <div class="bar-row">
      <span class="bar-label">${label}</span>
      <div class="bar-wrap">
        <div class="bar-fill" style="width:${pct}%;background:${color}">
          ${pct > 20 ? `<span class="bar-val">${display}</span>` : ''}
        </div>
      </div>
      ${pct <= 20 ? `<span class="bar-val-out">${display}</span>` : '<span class="bar-val-out"></span>'}
    </div>`;
}

// ── Load DORA data ─────────────────────────────────────────────────────────
async function loadDORA() {
  const r   = await fetch(`${API}/metrics/dora`);
  const d   = await r.json();
  const dora  = d.dora  || {};
  const space = d.space || {};
  const mttr  = dora.mttr || {};

  // KPI row
  const avgMin = mttr.avg_minutes;
  const avgSec = mttr.avg_seconds;
  const meets  = avgMin != null && avgMin <= 30;
  document.getElementById('k-total').textContent = d.incidents_tracked || 0;
  document.getElementById('k-total-sub').textContent = `${d.incidents_resolved || 0} resolved`;
  document.getElementById('k-mttr').textContent = fmtMttr(avgMin, avgSec);
  document.getElementById('k-mttr').style.color = meets ? 'var(--green)' : 'var(--yellow)';
  document.getElementById('k-mttr-sub').textContent = meets ? '✓ meets target' : '⚠ above 30 min';
  const ap = space.satisfaction?.approval_rate_pct;
  document.getElementById('k-approval').textContent = ap != null ? ap + '%' : '—';
  const ag = space.collaboration?.avg_agents_per_incident;
  document.getElementById('k-agents').textContent = ag != null ? ag : '—';

  // MTTR per-incident bar chart
  const perInc = d.per_incident || [];
  if (perInc.length) {
    const maxMttr = Math.max(...perInc.map(i => i.mttr_minutes || 0), 1);
    document.getElementById('mttr-chart').innerHTML = `
      <div class="bar-chart">
        ${perInc.map((inc, idx) => {
          const m = inc.mttr_minutes;
          const s = inc.mttr_seconds;
          const label = `#${idx + 1} ${(inc.incident_id || '').substring(0, 12)}`;
          const display = fmtMttr(m, s);
          const color = (m != null && m <= 30) ? '#1a7f37' : '#9a6700';
          return hBar(label, m || 0, maxMttr, color, '');
        }).join('')}
        <div style="font-size:11px;color:var(--muted);margin-top:8px">
          Target: ≤ 30 min · Red dashed line at 30 min
        </div>
      </div>`;
  }

  // Decisions chart
  const approved = space.satisfaction?.approved || 0;
  const rejected = space.satisfaction?.rejected || 0;
  const total = approved + rejected;
  if (total > 0) {
    const apPct = total > 0 ? Math.round(approved / total * 100) : 0;
    const rejPct = 100 - apPct;
    document.getElementById('decisions-chart').innerHTML = `
      <div style="display:flex;gap:24px;align-items:center;flex-wrap:wrap">
        <div>
          ${svgGauge(approved, total, '#1a7f37', approved + '', 100)}
          <div style="font-size:12px;font-weight:700;color:var(--green);text-align:center">APPROVED</div>
        </div>
        <div>
          ${svgGauge(rejected, total, '#cf222e', rejected + '', 100)}
          <div style="font-size:12px;font-weight:700;color:var(--red);text-align:center">REJECTED</div>
        </div>
        <div style="flex:1;min-width:160px">
          <div style="margin-bottom:12px">
            <div style="font-size:11px;color:var(--muted);margin-bottom:4px;font-weight:700;text-transform:uppercase;letter-spacing:.5px">Approval rate</div>
            <div class="bar-wrap" style="height:24px">
              <div class="bar-fill" style="width:${apPct}%;background:var(--green)">
                ${apPct > 15 ? `<span class="bar-val">${apPct}%</span>` : ''}
              </div>
            </div>
          </div>
          <div style="font-size:12px;color:var(--muted)">
            ${approved} approved · ${rejected} rejected · ${total} total
          </div>
          <div style="font-size:11px;color:var(--muted);margin-top:6px">
            High approval rate = good AI recommendations
          </div>
        </div>
      </div>`;
  }

  // Phase timing (most recent incident)
  const lastInc = perInc[perInc.length - 1];
  if (lastInc?.phase_durations_ms && Object.keys(lastInc.phase_durations_ms).length > 0) {
    const phases = lastInc.phase_durations_ms;
    const icons  = {instana:'🔍', jira:'📋', rag:'📚', playbook:'📝', teams:'💬', hitl:'🛑', record_decision:'🔏'};
    const maxMs  = Math.max(...Object.values(phases), 1);
    document.getElementById('phase-chart').innerHTML = `
      <div style="margin-bottom:16px">
        <div class="bar-chart">
          ${Object.entries(phases).map(([phase, ms]) => {
            const label = `${icons[phase] || '⚙'} ${phase}`;
            return hBar(label, ms, maxMs, '#0969da', 'ms');
          }).join('')}
        </div>
      </div>
      <div class="phase-grid">
        ${Object.entries(phases).map(([phase, ms]) => `
          <div class="phase-item">
            <div class="phase-item-name">${icons[phase] || '⚙'} ${phase}</div>
            <div class="phase-item-ms">${ms}<span style="font-size:12px;font-weight:400;color:var(--muted)">ms</span></div>
            <div class="phase-item-label">Duration</div>
          </div>`).join('')}
      </div>`;
  }

  // Incident history table
  document.getElementById('incident-count').textContent = `${perInc.length} incident${perInc.length !== 1 ? 's' : ''}`;
  if (perInc.length) {
    document.getElementById('incident-table').innerHTML = `
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Run ID</th>
              <th>Incident</th>
              <th>Service</th>
              <th>Started</th>
              <th>MTTR</th>
              <th>Decision</th>
              <th>Agents</th>
            </tr>
          </thead>
          <tbody>
            ${perInc.map(inc => {
              const decBadge = inc.approval_decision === 'APPROVED'
                ? `<span class="badge badge-green">APPROVED</span>`
                : inc.approval_decision === 'REJECTED'
                ? `<span class="badge badge-red">REJECTED</span>`
                : `<span class="badge badge-yellow">PENDING</span>`;
              return `<tr>
                <td class="mono">${(inc.run_id||'').substring(0,8)}</td>
                <td class="mono" style="font-size:11px">${(inc.incident_id||'').substring(0,18)}…</td>
                <td>${inc.service || '—'}</td>
                <td>${fmtTime(inc.started_at)}</td>
                <td style="font-weight:700;color:${inc.mttr_minutes<=30?'var(--green)':'var(--yellow)'}">${fmtMttr(inc.mttr_minutes, inc.mttr_seconds)}</td>
                <td>${decBadge}</td>
                <td style="color:var(--accent);font-weight:700">${(inc.agents_involved||[]).length}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>`;
  }

  // SPACE — collaboration gauge
  if (ag != null) {
    const agPct = Math.min(ag / 7 * 100, 100);
    document.getElementById('space-collab').innerHTML = `
      <div style="display:flex;align-items:center;gap:24px;flex-wrap:wrap">
        <div class="gauge-item">
          ${svgGauge(ag, 7, '#8250df', ag + '', 110)}
          <div class="gauge-label">avg agents / incident</div>
        </div>
        <div style="flex:1;min-width:160px">
          <div style="font-size:13px;margin-bottom:12px;line-height:1.6">
            <strong>${ag}</strong> specialist agents coordinated per incident
            on average. Each agent has a dedicated tool set and system prompt.
          </div>
          <div style="font-size:11px;color:var(--muted)">
            SPACE framework — Collaboration dimension.<br>
            7 agents max: instana · jira · rag · playbook · teams · hitl · audit
          </div>
        </div>
      </div>`;
  }

  // SPACE — performance vs target
  if (avgMin != null) {
    const target = 30;
    const pctOfTarget = Math.min(avgMin / target * 100, 150);
    const good = avgMin <= target;
    document.getElementById('space-perf').innerHTML = `
      <div style="margin-bottom:16px">
        <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:6px">
          <span style="font-weight:700">${fmtMttr(avgMin, avgSec)} avg MTTR</span>
          <span style="color:var(--muted)">target: 30 min</span>
        </div>
        <div class="bar-wrap" style="height:28px">
          <div class="bar-fill" style="width:${Math.min(pctOfTarget, 100)}%;background:${good?'#1a7f37':'#9a6700'}">
            ${pctOfTarget > 20 ? `<span class="bar-val">${fmtMttr(avgMin, avgSec)}</span>` : ''}
          </div>
        </div>
        <div style="font-size:11px;color:var(--muted);margin-top:4px">
          30 min target line ────────────────────────────
        </div>
      </div>
      <div style="padding:12px;background:var(--${good?'green':'yellow'}-bg);border-radius:8px;border:1px solid ${good?'#57ab5a':'#d4a72c'}">
        <span style="font-size:13px;font-weight:700;color:var(--${good?'green':'yellow'})">
          ${good ? '✓ Meets SLO' : '⚠ Above target'}
        </span>
        <div style="font-size:12px;color:var(--muted);margin-top:4px">
          ${good
            ? `MTTR of ${fmtMttr(avgMin, avgSec)} is within the ≤30 min SLO.`
            : `MTTR of ${fmtMttr(avgMin, avgSec)} exceeds the 30 min target.`}
        </div>
      </div>`;
  }
}

// ── Load eval metrics ──────────────────────────────────────────────────────
async function loadEval() {
  const r = await fetch(`${API}/eval/report`);
  const d = await r.json();
  const evalMetrics = d.metrics || [];
  const colorMap = { 1.0: '#1a7f37', 0.8: '#0969da', 0.7: '#8250df' };
  const cards = evalMetrics.map(m => {
    const color = colorMap[m.threshold] || '#636c76';
    const pct   = Math.round(m.threshold * 100);
    return `
      <div class="eval-item">
        <div class="eval-name">${m.name}</div>
        <div class="eval-desc">${m.description}</div>
        <div class="eval-bar-wrap">
          <div class="eval-bar-fill" style="width:${pct}%;background:${color}"></div>
        </div>
        <div class="eval-threshold">
          Threshold: <strong>${pct}%</strong> ·
          <span style="font-size:11px;color:var(--muted)">${m.implementation}</span>
        </div>
      </div>`;
  }).join('');

  const hint = `
    <div style="grid-column:1/-1;margin-top:4px;padding:12px;background:var(--blue-bg);border-radius:8px;border:1px solid #b6e0fe;font-size:12px;color:var(--accent)">
      💡 Run <code style="background:rgba(0,0,0,.06);padding:1px 6px;border-radius:4px">pytest evaluation/ -v</code>
      to execute live evaluations with DeepEval.
      LLM-graded tests use <strong>Groq</strong> as judge when <code style="background:rgba(0,0,0,.06);padding:1px 6px;border-radius:4px">GROQ_API_KEY</code> is set — no OpenAI required.
    </div>`;

  // Replace the entire grid content in one shot — no cumulative appends
  document.getElementById('eval-grid').innerHTML = cards + hint;
}

// ── Run evaluation suite ───────────────────────────────────────────────────
async function runEval() {
  const btn    = document.getElementById('run-eval-btn');
  const panel  = document.getElementById('eval-run-panel');
  const output = document.getElementById('eval-run-output');
  const status = document.getElementById('eval-run-status');
  const summary= document.getElementById('eval-run-summary');

  btn.disabled = true;
  btn.textContent = '⟳ Running…';
  panel.style.display = 'block';
  output.innerHTML = '';
  status.textContent = 'Running…';
  status.style.color = 'var(--accent)';
  summary.textContent = '';

  function esc(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // Pretty-print a single pytest output line
  function renderLine(raw) {
    const e = esc(raw);

    // Test result lines: "module::TestClass::test_name PASSED [ 11%]"
    const testMatch = raw.match(/^(evaluation\S+)\s+(PASSED|FAILED|SKIPPED|ERROR)\s+\[\s*(\d+)%\]/);
    if (testMatch) {
      const [, path, result, pct] = testMatch;
      // shorten path: keep only ClassName::test_name
      const short = path.replace(/^evaluation\/test_agents\.py::/, '');
      const colors = { PASSED:'#3fb950', FAILED:'#f85149', SKIPPED:'#d29922', ERROR:'#f85149' };
      const icons  = { PASSED:'✓', FAILED:'✗', SKIPPED:'–', ERROR:'!' };
      const col = colors[result] || '#c9d1d9';
      const icon = icons[result] || '?';
      return `<div style="display:flex;align-items:baseline;gap:8px;padding:2px 0">` +
        `<span style="color:${col};font-weight:700;min-width:14px">${icon}</span>` +
        `<span style="color:#c9d1d9;flex:1">${esc(short)}</span>` +
        `<span style="color:${col};font-weight:700;font-size:10px;min-width:52px;text-align:right">${result}</span>` +
        `<span style="color:#484f58;font-size:10px;min-width:36px;text-align:right">[${pct}%]</span>` +
        `</div>`;
    }

    // Summary line: "=== 18 passed, 4 warnings in 19.92s ==="
    if (raw.match(/=+.*\d+ (passed|failed)/)) {
      const allPass = !raw.includes('failed') && !raw.includes('error');
      const col = allPass ? '#3fb950' : '#f85149';
      return `<div style="margin-top:10px;padding:10px 12px;background:rgba(${allPass?'63,185,80':'248,81,73'},.12);border-radius:6px;border:1px solid ${allPass?'#238636':'#da3633'}">` +
        `<span style="color:${col};font-weight:700;font-size:12px">${e}</span>` +
        `</div>`;
    }

    // Section separators or blank lines — dim them
    if (raw.match(/^=+$/) || raw.trim() === '') return '';
    if (raw.startsWith('collecting') || raw.startsWith('platform') || raw.startsWith('rootdir')) {
      return `<div style="color:#484f58;font-size:10.5px">${e}</div>`;
    }

    // Default
    return `<div style="color:#8b949e">${e}</div>`;
  }

  try {
    const resp = await fetch(`${API}/eval/run`, { method: 'POST' });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      const parts = buf.split('\n\n');
      buf = parts.pop();

      for (const chunk of parts) {
        const eventMatch = chunk.match(/^event:\s*(\w+)/m);
        const dataMatch  = chunk.match(/^data:\s*(.+)/m);
        if (!eventMatch || !dataMatch) continue;

        const evType = eventMatch[1];
        let data;
        try { data = JSON.parse(dataMatch[1]); } catch { continue; }

        if (evType === 'line') {
          const rendered = renderLine(data.line);
          if (rendered) output.innerHTML += rendered;
          output.scrollTop = output.scrollHeight;
        } else if (evType === 'done') {
          const ok = data.result === 'passed';
          status.textContent = ok ? '✓ All tests passed' : '✗ Some tests failed';
          status.style.color = ok ? 'var(--green)' : 'var(--red)';
          const dur = data.duration ? ` in ${data.duration}s` : '';
          summary.textContent = `${data.passed} passed · ${data.failed} failed${dur}`;
          btn.textContent = '▶ Run again';
          btn.disabled = false;
        }
      }
    }
  } catch (e) {
    status.textContent = 'Connection error';
    status.style.color = 'var(--red)';
    output.innerHTML += `<div style="color:#f85149">[Error: ${esc(e.message)}]</div>`;
    btn.textContent = '▶ Run evaluation';
    btn.disabled = false;
  }
}

// ── Load all ───────────────────────────────────────────────────────────────
async function loadAll() {
  try { await loadDORA(); } catch(e) { console.warn('DORA load error', e); }
  try { await loadEval(); } catch(e) { console.warn('Eval load error', e); }
}

// Init
loadAll();
setInterval(loadAll, 10000);  // 10s is enough — eval metrics don't change often
</script>
</body>
</html>
"""

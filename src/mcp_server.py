"""GCB Crisis Squad — MCP Server

Exposes the incident response system as a Model Context Protocol (MCP) server,
allowing agentic coding tools (Claude Code, Cursor, Kiro, Codex, etc.) to call
the system directly from their chat interface.

Tools exposed
-------------
  trigger_incident        Start an autonomous incident response pipeline
  get_dora_metrics        Retrieve current DORA + SPACE + cost metrics
  approve_incident        Submit a Human-in-the-Loop decision (APPROVED / REJECTED)
  list_incidents          List all tracked incidents with status
  generate_spec           Convert a feature description into a structured spec

Transport
---------
  stdio   — default, works with any MCP-capable tool (Claude Code, Cursor, etc.)
  SSE     — for remote/browser clients (run with --transport sse)

Usage
-----
  # stdio (Claude Code / Cursor / Codex)
  python -m src.mcp_server

  # SSE (remote, HTTP)
  python -m src.mcp_server --transport sse --port 8001

  # Register in Claude Code (~/.claude.json or project .mcp.json):
  {
    "mcpServers": {
      "crisis-squad": {
        "command": "python",
        "args": ["-m", "src.mcp_server"],
        "cwd": "/path/to/crisis-squad",
        "env": { "DEMO_MODE": "true" }
      }
    }
  }

  # Register in Cursor (settings → MCP Servers):
  {
    "crisis-squad": {
      "command": "python -m src.mcp_server",
      "cwd": "/path/to/crisis-squad"
    }
  }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from typing import Any

from mcp.server.mcpserver import MCPServer

# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

mcp = MCPServer(
    "crisis-squad",
    title="GCB Autonomous Crisis Squad",
    description=(
        "AI-native incident response system. "
        "Trigger autonomous pipelines, inspect DORA metrics, and approve "
        "Human-in-the-Loop gates — all from your agentic coding tool."
    ),
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Lazy imports — keep import time fast; only load heavy deps on first call
# ---------------------------------------------------------------------------


def _get_incidents_store() -> dict[str, dict]:
    """Return the shared incident store from the FastAPI server (if running)."""
    try:
        from src.api.server import _incidents  # noqa: PLC0415

        return _incidents
    except Exception:  # noqa: BLE001
        return {}


def _get_metrics() -> dict[str, Any]:
    try:
        from src.evaluation.cost_tracker import cost_tracker  # noqa: PLC0415
        from src.metrics.dora import metrics  # noqa: PLC0415

        data = metrics.dora_metrics()
        data["llm_cost"] = cost_tracker.summary()
        return data
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _api_base_url() -> str:
    return os.getenv("GCB_API_URL", "http://localhost:8000").rstrip("/")


def _auth_headers() -> dict[str, str]:
    """Bearer header for the API, when one is configured.

    Set GCB_API_TOKEN in the MCP server env block to match the API's
    API_SECRET_KEY. Without it, calls to a hardened API return 401 — which is
    the intended behaviour, not a bug.
    """
    token = os.getenv("GCB_API_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


# ---------------------------------------------------------------------------
# Tool: trigger_incident
# ---------------------------------------------------------------------------


@mcp.tool(
    name="trigger_incident",
    title="Trigger incident response",
    description=(
        "Run the 7-node incident response graph for the given incident_id. "
        "The pipeline runs: Instana diagnosis → Jira precedents → RAG runbook → "
        "LLM playbook → Teams war room → HitL gate (pauses for approval). "
        "Returns a run_id you can use to stream events or submit approval."
    ),
)
async def trigger_incident(incident_id: str) -> str:
    """
    Args:
        incident_id: The Instana incident identifier (e.g. 'QKTtAivDTAaKvCGqvQOWpA').
                     Use 'QKTtAivDTAaKvCGqvQOWpA' for the built-in demo incident.
    """
    import httpx  # noqa: PLC0415

    base_url = _api_base_url()
    try:
        async with httpx.AsyncClient(timeout=10, headers=_auth_headers()) as client:
            resp = await client.post(
                f"{base_url}/incidents",
                json={"incident_id": incident_id},
            )
            resp.raise_for_status()
            data = resp.json()
            run_id = data.get("run_id", "unknown")
            return (
                f"✅ Incident response started.\n"
                f"  run_id:      {run_id}\n"
                f"  incident_id: {incident_id}\n"
                f"  stream:      {base_url}/incidents/{run_id}/stream\n"
                f"  dashboard:   {base_url}/\n\n"
                f"The pipeline is now running autonomously. It will pause at the "
                f"Human-in-the-Loop gate. Use `approve_incident` with this run_id "
                f"to submit your decision once you see the playbook."
            )
    except Exception:  # noqa: BLE001
        # Fallback: run the graph directly if the API server is not running
        return await _trigger_direct(incident_id)


async def _trigger_direct(incident_id: str) -> str:
    """Run the graph directly without the HTTP server (standalone mode)."""
    try:
        from langchain_core.runnables import RunnableConfig  # noqa: PLC0415

        from src.graph.crisis_graph import default_state, get_graph  # noqa: PLC0415
        from src.metrics.dora import metrics  # noqa: PLC0415

        run_id = str(uuid.uuid4())[:8]
        thread_id = f"mcp-{run_id}"
        metrics.record_incident_start(incident_id, run_id)

        graph = get_graph()
        state = default_state(incident_id)
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        # Run up to the interrupt
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: graph.invoke(state, config=config)
        )

        return (
            f"✅ Incident pipeline ran in standalone mode (no API server).\n"
            f"  run_id:      {run_id}\n"
            f"  incident_id: {incident_id}\n"
            f"  thread_id:   {thread_id}\n\n"
            f"The graph has paused at the HitL gate. "
            f"Start the API server (`uvicorn src.api.server:app`) to use the full dashboard."
        )
    except Exception as exc:  # noqa: BLE001
        return f"❌ Failed to trigger incident: {exc}"


# ---------------------------------------------------------------------------
# Tool: get_dora_metrics
# ---------------------------------------------------------------------------


@mcp.tool(
    name="get_dora_metrics",
    title="Get DORA + SPACE metrics",
    description=(
        "Retrieve current engineering productivity metrics: DORA (MTTR, Deployment Frequency, "
        "Change Failure Rate) and SPACE (Satisfaction, Performance, Activity, Collaboration, "
        "Efficiency), plus LLM token usage and estimated USD cost per incident run."
    ),
)
async def get_dora_metrics(format: str = "summary") -> str:
    """
    Args:
        format: 'summary' for a concise text view, 'json' for full structured data.
    """
    import httpx  # noqa: PLC0415

    base_url = _api_base_url()
    try:
        async with httpx.AsyncClient(timeout=5, headers=_auth_headers()) as client:
            resp = await client.get(f"{base_url}/metrics/dora")
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001
        data = _get_metrics()

    if format == "json":
        return json.dumps(data, indent=2, default=str)

    # Build a concise human-readable summary
    dora = data.get("dora", {})
    space = data.get("space", {})
    cost = data.get("llm_cost", {})

    mttr = dora.get("mttr", {})
    avg_secs = mttr.get("avg_seconds")
    avg_mins = mttr.get("avg_minutes")
    mttr_str = (
        f"{avg_secs}s" if avg_secs and avg_secs < 120 else (f"{avg_mins}min" if avg_mins else "—")
    )

    lines = [
        "## DORA Metrics",
        f"  MTTR (avg):               {mttr_str}  (target: {mttr.get('target_minutes', 30)}min)",
        f"  Change Failure Rate:      {dora.get('change_failure_rate', {}).get('value_pct', '—')}%",
        f"  Incidents tracked:        {data.get('incidents_tracked', 0)}",
        f"  Incidents resolved:       {data.get('incidents_resolved', 0)}",
        "",
        "## SPACE Metrics",
        f"  Approval rate:            {space.get('satisfaction', {}).get('approval_rate_pct', '—')}%",
        f"  Avg agents per incident:  {space.get('collaboration', {}).get('avg_agents_per_incident', '—')}",
        f"  Meets MTTR target:        {space.get('performance', {}).get('meets_target', '—')}",
        "",
        "## LLM Cost",
        f"  Total calls:              {cost.get('total_calls', 0)}",
        f"  Total tokens:             {cost.get('total_tokens', 0):,}",
        f"  Total cost (est.):        ${cost.get('total_cost_usd', 0.0):.6f} USD",
        f"  Avg cost per call:        ${cost.get('avg_cost_per_call_usd', 0.0):.6f} USD",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: approve_incident
# ---------------------------------------------------------------------------


@mcp.tool(
    name="approve_incident",
    title="Approve or reject a HitL gate",
    description=(
        "Submit a Human-in-the-Loop decision for a paused incident pipeline. "
        "The pipeline will resume (APPROVED) or terminate (REJECTED) based on your decision. "
        "This is the structural governance gate — no production action is taken without it."
    ),
)
async def approve_incident(
    run_id: str,
    decision: str,
    decided_by: str = "mcp-user",
    notes: str = "",
) -> str:
    """
    Args:
        run_id:     The run_id returned by trigger_incident.
        decision:   'APPROVED' or 'REJECTED'.
        decided_by: Your name or role (recorded in the audit trail).
        notes:      Optional notes recorded alongside the decision.
    """
    decision = decision.upper().strip()
    if decision not in ("APPROVED", "REJECTED"):
        return "❌ decision must be 'APPROVED' or 'REJECTED'."

    import httpx  # noqa: PLC0415

    base_url = _api_base_url()
    try:
        async with httpx.AsyncClient(timeout=10, headers=_auth_headers()) as client:
            resp = await client.post(
                f"{base_url}/incidents/{run_id}/approve",
                json={"decision": decision, "decided_by": decided_by, "notes": notes},
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "unknown")
            return (
                f"{'✅' if decision == 'APPROVED' else '🛑'} Decision recorded.\n"
                f"  run_id:     {run_id}\n"
                f"  decision:   {decision}\n"
                f"  decided_by: {decided_by}\n"
                f"  status:     {status}\n"
                + (f"  notes:      {notes}\n" if notes else "")
                + f"\nThe pipeline will now {'complete remediation' if decision == 'APPROVED' else 'stop — no production changes made'}."
            )
    except Exception as exc:  # noqa: BLE001
        return f"❌ Failed to record decision: {exc}"


# ---------------------------------------------------------------------------
# Tool: list_incidents
# ---------------------------------------------------------------------------


@mcp.tool(
    name="list_incidents",
    title="List tracked incidents",
    description=(
        "List all incident runs tracked in this session, with their status, "
        "HitL decision, MTTR, and agents involved."
    ),
)
async def list_incidents() -> str:
    import httpx  # noqa: PLC0415

    base_url = _api_base_url()
    try:
        async with httpx.AsyncClient(timeout=5, headers=_auth_headers()) as client:
            resp = await client.get(f"{base_url}/incidents")
            resp.raise_for_status()
            incidents = resp.json().get("incidents", [])
    except Exception:  # noqa: BLE001
        # Fallback to in-process store
        store = _get_incidents_store()
        incidents = list(store.values())

    if not incidents:
        return "No incidents tracked yet. Use `trigger_incident` to start one."

    lines = [f"## Incidents ({len(incidents)} total)\n"]
    for inc in incidents:
        run_id = inc.get("run_id", "?")
        iid = inc.get("incident_id", "?")
        phase = inc.get("phase", "unknown")
        decision = inc.get("approval_decision", "PENDING")
        mttr = inc.get("mttr_seconds")
        mttr_str = f"{mttr}s" if mttr else "in progress"
        lines.append(
            f"  • {run_id[:8]}…  incident={iid[:12]}  "
            f"phase={phase}  decision={decision}  mttr={mttr_str}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: generate_spec
# ---------------------------------------------------------------------------


@mcp.tool(
    name="generate_spec",
    title="Generate implementation spec from feature description",
    description=(
        "Convert a free-form feature description (from a PO, ticket, or chat message) "
        "into a structured implementation specification with intent, acceptance criteria, "
        "constraints, and atomic implementation tasks. "
        "Useful for bridging the gap between product intent and engineering execution."
    ),
)
async def generate_spec(description: str) -> str:
    """
    Args:
        description: Free-form feature or requirement description. Can be a user story,
                     a Jira ticket title, a Slack message, or any natural language.
                     Example: 'As a SRE, I want to export incident reports as PDF.'
    """
    import httpx  # noqa: PLC0415

    base_url = _api_base_url()
    try:
        async with httpx.AsyncClient(timeout=60, headers=_auth_headers()) as client:
            resp = await client.post(
                f"{base_url}/spec/generate",
                json={"description": description},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001
        # Run directly if API is not available
        try:
            from src.agents.specification_agent import SpecificationAgent  # noqa: PLC0415

            agent = SpecificationAgent()
            result = agent.generate(description)
            data = result.to_dict()
        except Exception as exc2:  # noqa: BLE001
            return f"❌ Spec generation failed: {exc2}"

    lines = []
    if data.get("warnings"):
        for w in data["warnings"]:
            lines.append(f"> ⚠️  {w}")
        lines.append("")

    lines.append(f"**Intent:** {data.get('intent', '—')}")
    lines.append("")

    if data.get("clarifying_questions"):
        lines.append("**Open questions before implementation:**")
        for q in data["clarifying_questions"]:
            lines.append(f"  - {q}")
        lines.append("")

    if data.get("acceptance_criteria"):
        lines.append("**Acceptance criteria:**")
        for c in data["acceptance_criteria"]:
            lines.append(f"  - [ ] {c}")
        lines.append("")

    spec = data.get("spec_markdown", "")
    if spec:
        lines.append(spec)

    if data.get("tasks"):
        lines.append("\n**Implementation tasks:**")
        for t in data["tasks"]:
            est = t.get("estimated_minutes", "?")
            dep = f" ← {', '.join(t['depends_on'])}" if t.get("depends_on") else ""
            lines.append(f"  - **{t['id']}** {t['title']} (~{est}min){dep}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GCB Crisis Squad MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument("--port", type=int, default=8001, help="Port for SSE/HTTP transport")
    parser.add_argument("--host", default="0.0.0.0", help="Host for SSE/HTTP transport")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.transport == "stdio":
        asyncio.run(mcp.run_stdio_async())
    elif args.transport == "sse":
        import uvicorn  # noqa: PLC0415

        uvicorn.run(mcp.sse_app(), host=args.host, port=args.port, log_level="info")
    else:
        import uvicorn  # noqa: PLC0415

        uvicorn.run(mcp.streamable_http_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()

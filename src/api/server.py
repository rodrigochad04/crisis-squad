"""FastAPI server — REST API + Server-Sent Events + static dashboard.

Every incident run is executed by the compiled LangGraph in
`src/graph/crisis_graph.py`. This module never re-implements the pipeline: it
starts the graph, relays each node's structured output over SSE, and — when a
human decides — writes that decision into the checkpoint and resumes the graph
past the governance interrupt.

Endpoints:
  GET  /                          -> Dashboard HTML
  POST /incidents                 -> Trigger incident response          [auth]
  POST /incidents/{id}/approve    -> Record human decision              [auth]
  GET  /incidents/{id}            -> Get incident state
  GET  /incidents/{id}/stream     -> SSE stream of node events
  GET  /incidents                 -> List all incidents
  GET  /incidents/{id}/playbook   -> Generated playbook
  GET  /metrics/dora              -> DORA + SPACE metrics JSON
  GET  /metrics/cost              -> LLM token usage + estimated USD cost
  GET  /metrics/traces            -> OpenTelemetry spans (in-memory)
  GET  /eval/report               -> Evaluation harness results summary
  POST /eval/run                  -> Run the evaluation suite (SSE)     [auth]
  POST /spec/generate             -> Specification-to-implementation agent
  GET  /graph/definition          -> Compiled graph topology (introspected)
  GET  /health                    -> Health check
  GET  /docs                      -> Swagger UI
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from src.config import settings
from src.evaluation.cost_tracker import cost_tracker
from src.graph.crisis_graph import (
    NODE_SEQUENCE,
    default_state,
    get_graph,
    warm_retriever,
)
from src.graph.crisis_graph import (
    graph_definition as _graph_definition,
)
from src.metrics.dora import metrics
from src.observability.tracing import get_finished_spans

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Warm the retriever so the first incident is not blocked on a model download."""
    warm_retriever()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="GCB Autonomous Crisis Squad",
    description=(
        "AI-native incident response — multi-agent with Human-in-the-Loop governance.\n\n"
        "**Stack:** LangGraph · FAISS · OpenTelemetry · DeepEval\n\n"
        "Open `/` for the live dashboard."
    ),
    version="0.2.0",
)

# CORS is intentionally narrow. The dashboard is served from the same origin, so
# a wildcard would only widen the attack surface on the approval endpoint.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
security = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# In-memory incident index (the graph checkpointer owns the authoritative state)
# ---------------------------------------------------------------------------
_incidents: dict[str, dict] = {}
_event_queues: dict[str, list[asyncio.Queue]] = {}
_approval_locks: dict[str, asyncio.Lock] = {}

_PLACEHOLDER_SECRETS = {"", "change-me-in-production", "demo-secret-key"}


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> str:
    """Bearer-token guard for every state-changing endpoint.

    Enforcement is on by default. It can only be disabled by explicitly setting
    API_AUTH_ENABLED=false, which is what `.env.demo` does for a local demo — so
    an unauthenticated approval endpoint is always a deliberate, visible choice
    rather than the accident of an unused dependency.
    """
    if not settings.api_auth_enabled:
        return "auth-disabled"
    if settings.api_secret_key in _PLACEHOLDER_SECRETS:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "API_AUTH_ENABLED is true but API_SECRET_KEY is still a placeholder. "
                "Set a real secret, or set API_AUTH_ENABLED=false for a local demo."
            ),
        )
    if not credentials or credentials.credentials != settings.api_secret_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TriggerRequest(BaseModel):
    incident_id: str = Field(..., min_length=1, examples=["QKTtAivDTAaKvCGqvQOWpA"])
    thread_id: str | None = None


class ApprovalRequest(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    decided_by: str = Field(..., min_length=1, examples=["sre-lead"])
    notes: str = ""


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


async def _emit(run_id: str, event_type: str, data: dict) -> None:
    """Fan an SSE event out to every listener subscribed to this run."""
    for queue in _event_queues.get(run_id, []):
        await queue.put({"type": event_type, "data": data})


async def _sse_generator(run_id: str) -> AsyncGenerator[str, None]:
    queue: asyncio.Queue = asyncio.Queue()
    _event_queues.setdefault(run_id, []).append(queue)
    # Replay what already happened, so a late subscriber still sees the full run.
    for past in _incidents.get(run_id, {}).get("events", []):
        await queue.put(past)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=25.0)
                yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
                if event["type"] in ("resolved", "error"):
                    break
            except TimeoutError:
                yield "event: ping\ndata: {}\n\n"
    except asyncio.CancelledError:  # pragma: no cover - client disconnect
        pass
    finally:
        listeners = _event_queues.get(run_id, [])
        if queue in listeners:
            listeners.remove(queue)


async def _record_event(run_id: str, event_type: str, data: dict) -> None:
    """Persist an event for replay, then broadcast it."""
    _incidents.setdefault(run_id, {}).setdefault("events", []).append(
        {"type": event_type, "data": data}
    )
    await _emit(run_id, event_type, data)


# ---------------------------------------------------------------------------
# Graph runner
# ---------------------------------------------------------------------------

_NODE_LABELS = dict(NODE_SEQUENCE)
# The dashboard's phase rows are keyed on short ids; the graph node is
# `teams_war_room`. Keep the translation in one place.
_UI_PHASE = {"teams_war_room": "teams"}


async def _run_graph(run_id: str, incident_id: str, thread_id: str) -> None:
    """Stream the compiled graph, relaying node events to the browser as they happen.

    The graph is synchronous, so it runs in a worker thread and pushes each node
    update back onto the event loop as it completes. Collecting the whole stream
    first and replaying it would be simpler, but the dashboard would then sit
    blank for the entire run and light up all at once at the end.

    The graph halts on its own at `interrupt_after=["hitl"]`; nothing in this
    function can carry it past the gate.
    """
    record = _incidents[run_id]
    metrics.record_incident_start(incident_id, run_id)
    graph = get_graph()
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 50,
    }
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _worker() -> None:
        try:
            for chunk in graph.stream(
                default_state(incident_id), config=config, stream_mode="updates"
            ):
                for node, update in chunk.items():
                    # LangGraph emits a synthetic "__interrupt__" chunk when it
                    # stops at the gate; its payload is a tuple, not a node update.
                    if isinstance(update, dict):
                        loop.call_soon_threadsafe(queue.put_nowait, ("update", node, update))
            loop.call_soon_threadsafe(queue.put_nowait, ("done", "", {}))
        except Exception as exc:  # noqa: BLE001 — relayed to the client below
            loop.call_soon_threadsafe(queue.put_nowait, ("error", "", exc))

    loop.run_in_executor(None, _worker)

    async def _start_phase(node: str) -> None:
        record["phase"] = node
        record["last_updated"] = _utcnow()
        metrics.record_phase_start(run_id, node)
        await _record_event(
            run_id,
            "phase_start",
            {
                "phase": _UI_PHASE.get(node, node),
                "label": _NODE_LABELS.get(node, node),
                "timestamp": _utcnow(),
            },
        )

    order = [name for name, _ in NODE_SEQUENCE]
    await _start_phase(order[0])

    while True:
        kind, node, payload = await queue.get()

        if kind == "error":
            record["phase"] = "ERROR"
            record["error"] = f"{type(payload).__name__}: {payload}"
            record["last_updated"] = _utcnow()
            await _record_event(run_id, "error", {"error": record["error"], "timestamp": _utcnow()})
            return

        if kind == "update":
            metrics.record_agent_invoked(run_id, node)
            metrics.record_phase_end(run_id, node)
            for event in payload.get("ui_events", []):
                await _record_event(
                    run_id,
                    "phase_complete",
                    {
                        "phase": event["phase"],
                        "label": event.get("label", _NODE_LABELS.get(node, node)),
                        "result": event.get("result", {}),
                        "timestamp": _utcnow(),
                    },
                )
            # Announce the next node so the dashboard can show it as running.
            if node in order:
                idx = order.index(node)
                if idx + 1 < len(order) and order[idx + 1] != "record_decision":
                    await _start_phase(order[idx + 1])
            continue

        break  # kind == "done"

    snapshot = graph.get_state(config)
    values = dict(snapshot.values)
    record.update(
        {
            "phase": values.get("phase", "AWAITING_APPROVAL"),
            "approval_status": values.get("approval_status", "PENDING"),
            "approval_id": values.get("approval_id", ""),
            "service_name": values.get("service_name", ""),
            "playbook": values.get("playbook", ""),
            "instana_details": values.get("instana_raw", {}),
            "jira_results": values.get("jira_raw", {}),
            "channel_id": values.get("war_room_channel_id", ""),
            "kb_sources": values.get("kb_sources", []),
            "next_nodes": list(snapshot.next),
            "last_updated": _utcnow(),
        }
    )
    await _record_event(
        run_id,
        "awaiting_approval",
        {
            "message": "Workflow paused at the governance gate — awaiting a human decision",
            "approval_id": record["approval_id"],
            "interrupted_before": list(snapshot.next),
            "timestamp": _utcnow(),
        },
    )


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", tags=["ops"])
def health():
    from src.graph.crisis_graph import llm_available

    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "auth_enabled": settings.api_auth_enabled,
        "llm_configured": llm_available(),
        "llm_model": settings.llm_model,
        "timestamp": _utcnow(),
    }


@app.post("/incidents", status_code=202, tags=["incidents"])
async def trigger_incident(body: TriggerRequest, _: str = Depends(require_auth)):
    """Start a run. Returns immediately; follow progress on the SSE stream."""
    run_id = str(uuid.uuid4())[:8]
    thread_id = body.thread_id or f"{body.incident_id}-{run_id}"
    _incidents[run_id] = {
        "run_id": run_id,
        "incident_id": body.incident_id,
        "thread_id": thread_id,
        "phase": "STARTING",
        "approval_status": "NOT_REQUESTED",
        "approval_id": "",
        "decided_by": None,
        "started_at": _utcnow(),
        "last_updated": _utcnow(),
        "instana_details": None,
        "jira_results": None,
        "playbook": None,
        "channel_id": None,
        "events": [],
    }
    _event_queues[run_id] = []
    _approval_locks[run_id] = asyncio.Lock()
    asyncio.create_task(_run_graph(run_id, body.incident_id, thread_id))
    return {"run_id": run_id, "incident_id": body.incident_id, "status": "ACCEPTED"}


@app.get("/incidents/{run_id}/stream", tags=["incidents"])
async def stream_incident(run_id: str):
    """Server-Sent Events stream of node completions for a run."""
    if run_id not in _incidents:
        raise HTTPException(404, "Incident run not found")
    return StreamingResponse(
        _sse_generator(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/incidents/{run_id}/approve", tags=["incidents"])
async def approve_incident(run_id: str, body: ApprovalRequest, _: str = Depends(require_auth)):
    """Record a human decision and resume the graph past the governance gate.

    Guarded three ways, because "the gate is structural" has to survive a hostile
    client and not just a well-behaved dashboard:

    1. Bearer token — an anonymous caller cannot approve a production action.
    2. State check — the run must actually be paused at the gate. A decision that
       arrives before the gate is reached, or for a run that errored, is rejected.
    3. Single decision — the first decision wins. A second call gets 409, so the
       audit trail cannot be overwritten by a later, contradicting decision.
    """
    record = _incidents.get(run_id)
    if not record:
        raise HTTPException(404, "Incident run not found")

    lock = _approval_locks.setdefault(run_id, asyncio.Lock())
    async with lock:
        if record.get("approval_status") in ("APPROVED", "REJECTED"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Run {run_id} was already decided: "
                    f"{record['approval_status']} by {record.get('decided_by')!r} "
                    f"at {record.get('decided_at')}. Decisions are immutable."
                ),
            )
        if record.get("phase") == "ERROR":
            raise HTTPException(409, f"Run {run_id} failed and has no gate to approve.")
        if record.get("approval_status") != "PENDING" or not record.get("approval_id"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Run {run_id} has not reached the Human-in-the-Loop gate "
                    f"(phase={record.get('phase')!r}). Nothing to approve yet."
                ),
            )

        graph = get_graph()
        config: RunnableConfig = {"configurable": {"thread_id": record["thread_id"]}}
        snapshot = graph.get_state(config)
        if "record_decision" not in snapshot.next:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Graph is not paused at the governance interrupt "
                    f"(next={list(snapshot.next)}). Refusing to resume."
                ),
            )

        loop = asyncio.get_running_loop()

        def _resume() -> dict:
            graph.update_state(
                config,
                {
                    "approval_status": body.decision,
                    "decided_by": body.decided_by,
                    "decision_notes": body.notes,
                },
            )
            graph.invoke(None, config=config)
            return dict(graph.get_state(config).values)

        values = await loop.run_in_executor(None, _resume)

        record.update(
            {
                "approval_status": body.decision,
                "decided_by": body.decided_by,
                "decided_at": _utcnow(),
                "phase": values.get("phase", "RESOLVED"),
                "last_updated": _utcnow(),
            }
        )

    audit = values.get("audit_entry", {})
    metrics.record_approval(run_id, body.decision, body.decided_by)
    if body.decision == "APPROVED":
        metrics.record_resolution(run_id, record.get("service_name") or "unknown")

    await _record_event(
        run_id,
        "resolved",
        {
            "decision": body.decision,
            "decided_by": body.decided_by,
            "audit_entry": audit.get("audit_entry"),
            "timestamp": _utcnow(),
        },
    )
    return {"run_id": run_id, "decision": body.decision, "audit": audit}


@app.get("/incidents/{run_id}", tags=["incidents"])
def get_incident(run_id: str):
    record = _incidents.get(run_id)
    if not record:
        raise HTTPException(404, "Incident run not found")
    return {k: v for k, v in record.items() if k not in ("playbook", "events")}


@app.get("/incidents", tags=["incidents"])
def list_incidents():
    return [
        {
            k: v
            for k, v in r.items()
            if k not in ("playbook", "events", "instana_details", "jira_results")
        }
        for r in _incidents.values()
    ]


@app.get("/incidents/{run_id}/playbook", tags=["incidents"])
def get_playbook(run_id: str):
    record = _incidents.get(run_id)
    if not record:
        raise HTTPException(404, "Incident run not found")
    return {"run_id": run_id, "playbook": record.get("playbook", "")}


@app.get("/metrics/dora", tags=["metrics"])
def dora_metrics():
    """DORA + SPACE productivity metrics from all tracked incidents."""
    data = metrics.dora_metrics()
    # Embed cost summary so a single call gives full picture
    data["llm_cost"] = cost_tracker.summary()
    return data


@app.get("/metrics/cost", tags=["metrics"])
def cost_metrics():
    """LLM token usage and estimated USD cost per run and per model."""
    return cost_tracker.summary()


@app.get("/metrics/traces", tags=["metrics"])
def otel_traces():
    """OpenTelemetry spans collected in-memory (no collector needed)."""
    return {"spans": get_finished_spans(), "total": len(get_finished_spans())}


@app.get("/eval/report", tags=["evaluation"])
def eval_report():
    """Evaluation harness summary — DeepEval metrics explanation."""
    return {
        "framework": "DeepEval",
        "generated_at": _utcnow(),
        "test_cases": 6,
        "docs": "https://docs.confident-ai.com",
        "run_command": "pytest evaluation/ -v",
        "note": "Run `pytest evaluation/ -v` to execute live evaluations with DeepEval.",
        "metrics": [
            {
                "name": "Faithfulness",
                "description": "Does the diagnosis cite ONLY facts from tool outputs?",
                "threshold": 0.8,
                "implementation": "DeepEval FaithfulnessMetric — checks each claim against retrieval context",
            },
            {
                "name": "Answer Relevancy",
                "description": "Is the diagnosis relevant to the incident ID requested?",
                "threshold": 0.8,
                "implementation": "DeepEval AnswerRelevancyMetric",
            },
            {
                "name": "No Hallucination",
                "description": "Agent must not mention JVM heap, deploy versions, or commit hashes",
                "threshold": 1.0,
                "implementation": "Regex assertions on forbidden patterns",
            },
            {
                "name": "Playbook Completeness (G-Eval)",
                "description": "All 6 mandatory sections present and actionable",
                "threshold": 0.7,
                "implementation": "DeepEval GEval with custom criteria and evaluation steps",
            },
            {
                "name": "HitL Gate Compliance",
                "description": "request_human_approval called before any production action",
                "threshold": 1.0,
                "implementation": "Structural assertion — NIST AI RMF fields present",
            },
            {
                "name": "Pattern Classifier Accuracy",
                "description": "FAIL_FAST / SATURATION / LATENCY_DEGRADATION correctly identified",
                "threshold": 1.0,
                "implementation": "Unit tests with known-good metric fixtures",
            },
        ],
        "test_scenarios": [
            {"id": "fail_fast", "pattern": "FAIL_FAST", "incident_id": "QKTtAivDTAaKvCGqvQOWpA"},
            {
                "id": "saturation",
                "pattern": "SATURATION",
                "incident_id": "synthetic-saturation-001",
            },
            {
                "id": "latency_degradation",
                "pattern": "LATENCY_DEGRADATION",
                "incident_id": "synthetic-latency-001",
            },
        ],
    }


@app.post("/eval/run", tags=["evaluation"])
async def run_eval(_: str = Depends(require_auth)):
    """Execute the evaluation suite via pytest and return streamed output as SSE."""
    import sys

    async def _stream():
        env = {**__import__("os").environ}  # inherit GROQ_API_KEY etc.
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pytest",
            "evaluation/test_agents.py",
            "-v",
            "--no-header",
            "--tb=short",
            "--no-cov",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        import time as _time

        t0 = _time.monotonic()
        yield 'event: start\ndata: {"message": "pytest started"}\n\n'
        passed = failed = 0
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            if not line:
                continue
            if " PASSED" in line:
                passed += 1
            elif " FAILED" in line or " ERROR" in line:
                failed += 1
            payload = json.dumps({"line": line})
            yield f"event: line\ndata: {payload}\n\n"
        await proc.wait()
        duration = round(_time.monotonic() - t0, 1)
        result = "passed" if proc.returncode == 0 else "failed"
        yield f"event: done\ndata: {json.dumps({'returncode': proc.returncode, 'result': result, 'passed': passed, 'failed': failed, 'duration': duration})}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/graph/definition", tags=["graph"])
def graph_definition():
    """Topology of the compiled LangGraph, read from the graph itself.

    Introspected rather than hand-written, so the diagram the dashboard renders
    cannot drift from the graph that actually runs.
    """
    return _graph_definition()


@app.get("/metrics", response_class=HTMLResponse, tags=["dashboard"])
async def metrics_dashboard():
    """Serve the metrics & observability dashboard."""
    from src.api.metrics_html import METRICS_HTML

    return HTMLResponse(content=METRICS_HTML.replace("__REPO_URL__", settings.repo_url))


@app.get("/", response_class=HTMLResponse, tags=["dashboard"])
async def dashboard():
    """Serve the live incident response dashboard."""
    from src.api.dashboard_html import DASHBOARD_HTML

    return HTMLResponse(content=DASHBOARD_HTML.replace("__REPO_URL__", settings.repo_url))


# ---------------------------------------------------------------------------
# Specification agent
# ---------------------------------------------------------------------------


class SpecRequest(BaseModel):
    description: str = Field(
        ...,
        min_length=10,
        examples=[
            "As a SRE, I want to export incident reports as PDF so I can share them offline."
        ],
    )


@app.post("/spec/generate", tags=["spec"])
async def generate_spec(req: SpecRequest, _: str = Depends(require_auth)):
    """Convert a free-form feature description into a structured implementation spec.

    Uses a multi-step LangGraph-style pipeline:
    1. Parse — extract intent, constraints, acceptance criteria
    2. Spec  — generate structured Markdown specification
    3. Tasks — break spec into atomic, estimable implementation tasks

    Requires GROQ_API_KEY (or another LLM configured in LLM_MODEL).
    Returns 503 if no LLM is available.
    """
    try:
        from src.agents.specification_agent import SpecificationAgent

        agent = SpecificationAgent()
        result = agent.generate(req.description)
        return result.to_dict()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Spec generation failed: {exc}") from exc


def main():
    uvicorn.run(
        "src.api.server:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()

"""LangGraph multi-agent graph — Autonomous Crisis Squad.

This module is the SINGLE execution path for an incident response run.
Both the REST API (`src/api/server.py`) and the MCP server (`src/mcp_server.py`)
drive this compiled graph — there is no parallel implementation.

Topology (7 nodes, linear until the governance gate)::

    START -> instana -> jira -> rag -> playbook -> teams_war_room -> hitl
                                                                      |
                                                    interrupt_after=["hitl"]
                                                                      |
                                                            record_decision -> END

Human-in-the-Loop is enforced *structurally*: `interrupt_after=["hitl"]` means the
compiled graph stops after registering the approval request and before any node
that could act on production. Resuming requires an explicit
`update_state(approval_status=...)` from the API layer.

Orchestration is deterministic: every node calls its tools directly in a fixed
order. The LLM is used at exactly one point — playbook generation — where free
text is genuinely the deliverable. This is a design choice, not a limitation: a
ReAct loop that always calls the same two tools in the same order adds latency,
cost and non-determinism without adding capability. See docs/ARCHITECTURE.md.

Run::

    from src.graph.crisis_graph import get_graph, default_state
    graph = get_graph()
    graph.invoke(default_state("QKTtAivDTAaKvCGqvQOWpA"),
                 config={"configurable": {"thread_id": "demo"}})
"""

from __future__ import annotations

import json
import operator
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.config import settings
from src.evaluation.cost_tracker import cost_tracker
from src.observability.tracing import span
from src.tools.hitl_tools import record_human_decision, request_human_approval
from src.tools.instana_tools import instana_get_blast_radius, instana_get_incident_details
from src.tools.jira_tools import jira_create_incident_ticket, jira_search_related_issues
from src.tools.teams_tools import teams_create_war_room, teams_post_update

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Shared state schema
# ---------------------------------------------------------------------------


class IncidentState(TypedDict):
    """State accumulated as the incident flows through the graph."""

    # Input
    incident_id: str
    # Append-only narrative
    messages: Annotated[list[BaseMessage], operator.add]
    # Append-only structured events consumed by the SSE stream / dashboard
    ui_events: Annotated[list[dict], operator.add]
    # Phase outputs
    instana_diagnosis: str
    instana_raw: dict
    jira_precedents: str
    jira_raw: dict
    kb_runbook: str
    kb_sources: list[str]
    playbook: str
    service_name: str
    severity: str
    war_room_channel_id: str
    approval_id: str
    approval_status: Literal["PENDING", "APPROVED", "REJECTED", "NOT_REQUESTED"]
    decided_by: str
    decision_notes: str
    audit_entry: dict
    # Control
    phase: str


def default_state(incident_id: str) -> IncidentState:
    """Return a fresh state for a new incident run."""
    return IncidentState(
        incident_id=incident_id,
        messages=[],
        ui_events=[],
        instana_diagnosis="",
        instana_raw={},
        jira_precedents="",
        jira_raw={},
        kb_runbook="",
        kb_sources=[],
        playbook="",
        service_name="",
        severity="",
        war_room_channel_id="",
        approval_id="",
        approval_status="NOT_REQUESTED",
        decided_by="",
        decision_notes="",
        audit_entry={},
        phase="TRIAGE",
    )


# Backwards-compatible alias (older callers imported the private name).
_default_state = default_state


def _event(phase: str, label: str, result: dict) -> dict:
    return {"phase": phase, "label": label, "result": result}


# ---------------------------------------------------------------------------
# LLM factory — provider-agnostic, swapped via LLM_MODEL in .env
# ---------------------------------------------------------------------------


def _strip_think(text: str) -> str:
    """Remove <think>...</think> chain-of-thought blocks from reasoning models."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def llm_available() -> bool:
    """True when a usable LLM is configured (a local Ollama needs no key)."""
    model = settings.llm_model.lower()
    if model.startswith("ollama/"):
        return True
    if model.startswith("groq/"):
        return bool(settings.groq_api_key)
    if model.startswith("anthropic/"):
        return bool(settings.anthropic_api_key)
    return bool(settings.openai_api_key)


def _llm(fast: bool = False) -> BaseChatModel:
    """Return a LangChain chat model for the configured provider.

    Routing (set ``LLM_MODEL`` in ``.env`` — no code change needed):

    ``groq/<model>``       -> ChatGroq
    ``anthropic/<model>``  -> ChatAnthropic
    ``ollama/<model>``     -> ChatOpenAI pointed at the local Ollama endpoint
    ``openai/<model>``     -> ChatOpenAI
    anything else          -> ChatOpenAI against ``LLM_BASE_URL`` (LiteLLM proxy, vLLM, ...)
    """
    full_model = settings.llm_fast_model if fast else settings.llm_model
    model_lower = full_model.lower()

    if model_lower.startswith("groq/"):
        from langchain_groq import ChatGroq

        bare = full_model[len("groq/") :]
        # reasoning_effort="none" suppresses <think> CoT on Qwen/DeepSeek via Groq
        extra: dict[str, Any] = {}
        if "qwen" in bare.lower() or "deepseek" in bare.lower():
            extra["reasoning_effort"] = "none"
        return ChatGroq(
            model=bare,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            api_key=settings.groq_api_key,  # type: ignore[arg-type]
            timeout=settings.llm_timeout_seconds,
            max_retries=1,
            **extra,
        )

    if model_lower.startswith("anthropic/"):
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=full_model[len("anthropic/") :],  # type: ignore[call-arg]
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,  # type: ignore[call-arg]
            timeout=settings.llm_timeout_seconds,
            api_key=settings.anthropic_api_key,  # type: ignore[arg-type]
        )

    from langchain_openai import ChatOpenAI

    if model_lower.startswith("ollama/"):
        return ChatOpenAI(
            model=full_model[len("ollama/") :],
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,  # type: ignore[call-arg]
            base_url=settings.ollama_base_url,
            api_key="ollama-no-key-needed",  # type: ignore[arg-type]
            timeout=settings.llm_timeout_seconds,
        )

    return ChatOpenAI(
        model=full_model.removeprefix("openai/"),
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,  # type: ignore[call-arg]
        base_url=settings.llm_base_url or None,
        api_key=settings.openai_api_key or "not-set",  # type: ignore[arg-type]
        timeout=settings.llm_timeout_seconds,
    )


# ---------------------------------------------------------------------------
# Prompts (only the playbook agent uses an LLM)
# ---------------------------------------------------------------------------

PLAYBOOK_SYSTEM = """You are the Playbook Generation Agent — specialist in structured incident remediation.

You receive a complete incident diagnosis (Instana metrics + Jira history + KB runbook).
Generate a detailed, actionable remediation playbook.

MANDATORY SECTIONS (use these exact headings, numbered, as `## N. Title`):
1. Executive Summary — 3 lines max: what, why, risk
2. Pre-execution Checklist — validations before acting
3. Remediation Steps — numbered, with exact kubectl/helm commands and expected output
4. Validation Criteria — how to confirm resolution (numeric metric thresholds, health checks)
5. Rollback Procedure — exact commands to revert if remediation fails
6. Escalation Path — who to contact if rollback also fails

GROUNDING RULES:
- Use ONLY facts present in the context you are given.
- Never invent JVM heap figures, deployment versions, commit hashes or financial impact.
- Every metric you cite must appear alongside its baseline.

FORMAT: Markdown. Be precise. No preamble, no closing remarks. Start with `# Playbook`.
An SRE under pressure will follow this step by step."""


# ---------------------------------------------------------------------------
# Node helpers
# ---------------------------------------------------------------------------


def _fmt_diagnosis(details: dict, blast: dict) -> str:
    """Build a grounded diagnosis string from tool output only.

    Deterministic on purpose: every number is printed next to its 7-day baseline,
    so the text cannot drift from the metrics the tools actually returned.
    """
    during = details.get("metrics_during_incident", {}) or {}
    base = details.get("metrics_baseline_7d_before", {}) or {}
    assessment = (details.get("diagnosis", {}) or {}).get("assessment", {}) or {}
    svc = (details.get("affected_service", {}) or {}).get("name", "unknown")

    def cmp(key: str, unit: str) -> str:
        d, b = during.get(key), base.get(key)
        if d is None:
            return "n/a"
        if b is None:
            return f"{d}{unit} (no baseline)"
        return f"{d}{unit} vs {b}{unit} baseline"

    lines = [
        f"Service: {svc}",
        f"Application: {(details.get('application', {}) or {}).get('name', 'unknown')}",
        f"Severity: {details.get('severity', 'unknown')} | State: {details.get('event_state', 'unknown')}",
        f"Problem: {details.get('problem', 'n/a')}",
        f"Detail: {details.get('detail', 'n/a')}",
        "",
        "Metrics (incident vs 7-day baseline):",
        f"  - Error rate: {cmp('error_rate_pct', '%')}",
        f"  - Latency p99: {cmp('latency_p99_ms', 'ms')}",
        f"  - Calls: {cmp('calls_per_minute', '/min')}",
        "",
        f"Failure pattern: {assessment.get('pattern', 'INDETERMINATE')}",
        f"Reasoning: {assessment.get('reasoning', 'n/a')}",
        f"Recommendation: {assessment.get('recommendation', 'n/a')}",
        "",
        f"Blast radius: {blast.get('services_anomalous', 0)} anomalous of "
        f"{blast.get('services_analyzed', 0)} services analysed.",
    ]
    anomalous = blast.get("anomalous_services") or []
    for a in anomalous[:5]:
        if isinstance(a, dict):
            lines.append(f"  - {a.get('name', a)}")
        else:
            lines.append(f"  - {a}")
    return "\n".join(lines)


def _static_playbook(service: str, pattern: str, namespace: str = "mcp-context-forge") -> str:
    """Deterministic fallback playbook used when no LLM is configured."""
    return f"""# Playbook — {service} {pattern}

## 1. Executive Summary
{service} is failing with pattern {pattern}. Metrics deviate sharply from the 7-day
baseline. Probable cause: recent configuration or credential change. Risk: HIGH.

## 2. Pre-execution Checklist
- [ ] SRE Lead present in the war room channel
- [ ] Previous stable revision identified
- [ ] Current ConfigMap backed up

## 3. Remediation Steps
```bash
kubectl rollout history deployment/{service} -n {namespace}
kubectl rollout undo deployment/{service} -n {namespace}
kubectl rollout status deployment/{service} -n {namespace} --timeout=120s
```

## 4. Validation Criteria
- Error rate below 5% within 2 minutes of rollback
- p99 latency back inside the baseline band
- `curl -sf https://{service}.internal/health` returns 200

## 5. Rollback Procedure
```bash
kubectl rollout undo deployment/{service} -n {namespace} --to-revision=0
```

## 6. Escalation Path
1. SRE Lead: #sre-oncall
2. Platform Engineering: #platform-eng
3. Service owner: #{service}-team
"""


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


def instana_node(state: IncidentState, config: RunnableConfig) -> dict:
    """Diagnosis — error rate, latency, blast radius, failure pattern."""
    incident_id = state["incident_id"]
    with span("node.instana", incident_id=incident_id):
        details = json.loads(instana_get_incident_details.invoke({"incident_id": incident_id}))
        blast = json.loads(instana_get_blast_radius.invoke({"incident_id": incident_id}))

    if details.get("status") == "ERROR":
        raise RuntimeError(f"Instana tool error: {details.get('error', 'unknown')}")

    diagnosis = _fmt_diagnosis(details, blast)
    during = details.get("metrics_during_incident", {}) or {}
    base = details.get("metrics_baseline_7d_before", {}) or {}
    assessment = (details.get("diagnosis", {}) or {}).get("assessment", {}) or {}
    service = (details.get("affected_service", {}) or {}).get("name", "unknown")
    # Instana returns fully-qualified names; the short name is the deployment name.
    short_service = service.split("-mcp-stack")[0].split(".")[0]

    return {
        "instana_diagnosis": diagnosis,
        "instana_raw": details,
        "service_name": short_service,
        "severity": details.get("severity", "UNKNOWN"),
        "messages": [AIMessage(content=f"[Instana] {diagnosis}", name="instana")],
        "ui_events": [
            _event(
                "instana",
                "Instana — diagnosis and blast radius",
                {
                    "pattern": assessment.get("pattern", "INDETERMINATE"),
                    "severity": details.get("severity"),
                    "service": short_service,
                    "error_rate": during.get("error_rate_pct"),
                    "latency_p99": during.get("latency_p99_ms"),
                    "latency_baseline": base.get("latency_p99_ms"),
                    "blast_radius": blast.get("services_anomalous"),
                    "services_analyzed": blast.get("services_analyzed"),
                },
            )
        ],
        "phase": "JIRA",
    }


def jira_node(state: IncidentState, config: RunnableConfig) -> dict:
    """Historical precedents plus the formal incident ticket."""
    service = state["service_name"] or "unknown"
    assessment = (state["instana_raw"].get("diagnosis", {}) or {}).get("assessment", {}) or {}
    pattern = assessment.get("pattern", "INDETERMINATE")
    keywords = f"{state['instana_raw'].get('problem', '')} {pattern}".strip()

    with span("node.jira", service=service):
        results = json.loads(
            jira_search_related_issues.invoke(
                {"service_name": service, "error_keywords": keywords or "error rate"}
            )
        )
        ticket = json.loads(
            jira_create_incident_ticket.invoke(
                {
                    "title": f"[{state['severity']}] {service} — {pattern} {state['incident_id'][:8]}",
                    "service_name": service,
                    "severity": "P0" if state["severity"] == "CRITICAL" else "P2",
                    "description": state["instana_diagnosis"][:1500],
                    "alert_id": state["incident_id"],
                }
            )
        )

    issues = results.get("issues") or []
    best = issues[0] if issues else {}
    summary_lines = [f"{len(issues)} precedent(s) found for {service}."]
    for i in issues[:3]:
        summary_lines.append(
            f"  - {i.get('key')}: {i.get('title', '')} "
            f"(resolved in {i.get('resolution_time_min', '?')} min)"
        )
    summary_lines.append(f"Ticket opened: {ticket.get('key')} — {ticket.get('url')}")
    precedents = "\n".join(summary_lines)

    return {
        "jira_precedents": precedents,
        "jira_raw": {"search": results, "ticket": ticket},
        "messages": [AIMessage(content=f"[Jira] {precedents}", name="jira")],
        "ui_events": [
            _event(
                "jira",
                "Jira — precedents and ticket",
                {
                    "precedents_found": results.get("total_found", len(issues)),
                    "best_precedent": best.get("key"),
                    "best_precedent_mttr": best.get("resolution_time_min"),
                    "ticket_created": ticket.get("key"),
                    "ticket_url": ticket.get("url"),
                },
            )
        ],
        "phase": "RAG",
    }


def _keyword_fallback(query: str, k: int = 3) -> tuple[str, list[str]]:
    """Keyword retrieval over the runbook directory.

    Used only when the FAISS stack is unavailable, so the demo still runs on a
    machine without sentence-transformers installed.
    """
    docs_dir = PROJECT_ROOT / settings.kb_docs_dir.lstrip("./")
    if not docs_dir.exists():
        return "", []
    terms = {t.lower() for t in re.findall(r"[a-zA-Z]{4,}", query)}
    scored: list[tuple[int, Path, str]] = []
    for md in sorted(docs_dir.glob("**/*.md")):
        text = md.read_text(encoding="utf-8")
        score = sum(text.lower().count(t) for t in terms)
        scored.append((score, md, text))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [s for s in scored[:k] if s[0] > 0] or scored[:1]
    context = "\n\n---\n\n".join(f"[Source: {p.name}]\n{t[:1200]}" for _, p, t in top)
    return context, [p.name for _, p, _ in top]


# The embedding model is fetched from HuggingFace on first use. When that host is
# unreachable — an air-gapped runner, a corporate proxy, a plain offline laptop —
# the download retries for minutes and the whole pipeline appears to hang. A demo
# that hangs is worse than one that degrades, so retrieval is time-bounded and the
# failure is remembered rather than retried on every incident.
_FAISS_TIMEOUT_SECONDS = 20.0

# Set only on a hard, permanent failure (the FAISS/embeddings packages are not
# installed). A timeout is NOT permanent: the first call may simply have caught
# the model mid-download, and the next incident should try again rather than
# being downgraded to keyword search for the life of the process.
_faiss_unavailable: str | None = None
_faiss_executor: ThreadPoolExecutor | None = None


def _get_faiss_executor() -> ThreadPoolExecutor:
    """One long-lived worker, so a timed-out download keeps making progress."""
    global _faiss_executor
    if _faiss_executor is None:
        _faiss_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="faiss")
    return _faiss_executor


def warm_retriever() -> None:
    """Load the FAISS index and embedding model ahead of the first incident.

    Called at API startup. The embedding model is fetched from HuggingFace on
    first use, which can take longer than any sensible per-request timeout, so
    doing it lazily inside a run makes the first incident look broken.
    """
    global _faiss_unavailable

    def _work() -> None:
        global _faiss_unavailable
        try:
            from src.knowledge_base.retriever import get_retriever

            get_retriever()
        except ImportError as exc:
            _faiss_unavailable = f"{type(exc).__name__}: {exc}"
        except Exception:  # noqa: BLE001 — transient; the node will retry
            pass

    _get_faiss_executor().submit(_work)


def _faiss_retrieve(query: str) -> list:
    """Run FAISS retrieval under a timeout. Raises to trigger the fallback."""
    global _faiss_unavailable

    if _faiss_unavailable is not None:
        raise RuntimeError(_faiss_unavailable)

    def _work() -> list:
        from src.knowledge_base.retriever import get_retriever

        return get_retriever().invoke(query)

    try:
        return _get_faiss_executor().submit(_work).result(timeout=_FAISS_TIMEOUT_SECONDS)
    except FuturesTimeout as exc:
        raise RuntimeError(
            f"FAISS retrieval exceeded {_FAISS_TIMEOUT_SECONDS:.0f}s — the embedding "
            "model is still downloading or HuggingFace is unreachable"
        ) from exc
    except ImportError as exc:
        _faiss_unavailable = f"{type(exc).__name__}: {exc}"
        raise


def rag_node(state: IncidentState, config: RunnableConfig) -> dict:
    """Semantic retrieval over local runbooks and postmortems (FAISS)."""
    assessment = (state["instana_raw"].get("diagnosis", {}) or {}).get("assessment", {}) or {}
    query = (
        f"{state['service_name']} {assessment.get('pattern', '')} "
        f"{state['instana_raw'].get('problem', '')} runbook rollback remediation"
    ).strip()

    backend = "faiss"
    sources: list[str] = []
    context = ""
    with span("node.rag", query=query[:120]):
        try:
            docs = _faiss_retrieve(query)
            seen: set[str] = set()
            unique = []
            for d in docs:
                if d.page_content not in seen:
                    seen.add(d.page_content)
                    unique.append(d)
            unique = unique[:6]
            context = "\n\n---\n\n".join(
                f"[Source: {Path(str(d.metadata.get('source', 'unknown'))).name}]\n{d.page_content}"
                for d in unique
            )
            sources = list(
                dict.fromkeys(Path(str(d.metadata.get("source", "unknown"))).name for d in unique)
            )
        except Exception as exc:  # noqa: BLE001 — see _faiss_retrieve for the cases
            backend = f"keyword-fallback ({type(exc).__name__})"
            context, sources = _keyword_fallback(query)

    return {
        "kb_runbook": context,
        "kb_sources": sources,
        "messages": [AIMessage(content=f"[KB] {len(sources)} document(s) retrieved", name="rag")],
        "ui_events": [
            _event(
                "rag",
                "Knowledge base — runbooks and postmortems",
                {
                    "backend": backend,
                    "docs_retrieved": len(sources),
                    "sources": sources,
                    "top_source": sources[0] if sources else None,
                    "excerpt": context[:220] + ("..." if len(context) > 220 else ""),
                },
            )
        ],
        "phase": "PLAYBOOK",
    }


def playbook_node(state: IncidentState, config: RunnableConfig) -> dict:
    """Generate the remediation playbook — the only LLM call in the graph."""
    assessment = (state["instana_raw"].get("diagnosis", {}) or {}).get("assessment", {}) or {}
    pattern = assessment.get("pattern", "INDETERMINATE")
    service = state["service_name"] or "unknown"

    source = "llm"
    playbook = ""
    if llm_available():
        prompt = (
            f"=== Instana diagnosis ===\n{state['instana_diagnosis']}\n\n"
            f"=== Jira precedents ===\n{state['jira_precedents']}\n\n"
            f"=== Knowledge base ===\n{state['kb_runbook'][:4000]}"
        )
        try:
            with span("node.playbook.llm", model=settings.llm_model):
                resp = _llm().invoke(
                    [SystemMessage(content=PLAYBOOK_SYSTEM), HumanMessage(content=prompt)]
                )
            content = resp.content
            playbook = _strip_think(content if isinstance(content, str) else str(content))
            usage = getattr(resp, "usage_metadata", None) or {}
            cost_tracker.record_call(
                model=settings.llm_model,
                prompt_tokens=int(usage.get("input_tokens", 0)),
                completion_tokens=int(usage.get("output_tokens", 0)),
                run_id=str((config.get("configurable") or {}).get("thread_id", "")),
                node="playbook",
            )
        except Exception as exc:  # noqa: BLE001 — never let the pipeline die on the LLM
            source = f"static-fallback ({type(exc).__name__})"
            playbook = _static_playbook(service, pattern)
    else:
        source = "static-fallback (no LLM configured)"
        playbook = _static_playbook(service, pattern)

    sections = [
        line.strip("# ").strip() for line in playbook.splitlines() if line.startswith("## ")
    ]
    return {
        "playbook": playbook,
        "messages": [AIMessage(content="[Playbook] generated", name="playbook")],
        "ui_events": [
            _event(
                "playbook",
                "Remediation playbook",
                {
                    "source": source,
                    "model": settings.llm_model if source == "llm" else None,
                    "sections": sections,
                    "has_kubectl": "kubectl" in playbook,
                    "lines": len(playbook.splitlines()),
                },
            )
        ],
        "phase": "WAR_ROOM",
    }


def teams_node(state: IncidentState, config: RunnableConfig) -> dict:
    """Open the war room channel and post the playbook."""
    with span("node.teams", service=state["service_name"]):
        war_room = json.loads(
            teams_create_war_room.invoke(
                {
                    "incident_id": state["incident_id"],
                    "service_name": state["service_name"] or "unknown",
                    "severity": "P0" if state["severity"] == "CRITICAL" else "P2",
                    "summary": state["instana_diagnosis"][:800],
                    "oncall_squad": "SRE Platform Engineering",
                }
            )
        )
        channel = war_room.get("channel", {}) or {}
        channel_id = channel.get("id", "")
        posted = False
        if channel_id:
            teams_post_update.invoke(
                {
                    "channel_id": channel_id,
                    "message": state["playbook"],
                    "message_type": "UPDATE",
                }
            )
            posted = True

    return {
        "war_room_channel_id": channel_id,
        "messages": [AIMessage(content=f"[Teams] war room {channel_id}", name="teams")],
        "ui_events": [
            _event(
                "teams",
                "Teams war room",
                {
                    "channel_id": channel_id,
                    "channel_name": channel.get("name"),
                    "channel_url": channel.get("url"),
                    "playbook_posted": posted,
                },
            )
        ],
        "phase": "APPROVAL",
    }


def _extract_primary_action(playbook: str, service: str) -> str:
    """Pull the first shell command out of the Remediation Steps section.

    The action presented at the gate must be the one the playbook actually
    recommends — never a hard-coded string.
    """
    match = re.search(r"##\s*3\..*?```(?:bash|sh)?\n(.*?)```", playbook, re.DOTALL)
    block = match.group(1) if match else ""
    for line in block.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "rollout history" not in line:
            return line
    return f"kubectl rollout undo deployment/{service}"


def hitl_node(state: IncidentState, config: RunnableConfig) -> dict:
    """Governance gate — registers the approval request, then the graph interrupts."""
    service = state["service_name"] or "unknown"
    action = _extract_primary_action(state["playbook"], service)
    action_type = "ROLLBACK" if "undo" in action or "rollback" in action.lower() else "REMEDIATION"
    best = ((state["jira_raw"].get("search") or {}).get("issues") or [{}])[0]

    with span("node.hitl", action=action_type):
        approval = json.loads(
            request_human_approval.invoke(
                {
                    "incident_id": state["incident_id"],
                    "action_type": action_type,
                    "action_description": action,
                    "risk_level": "HIGH" if state["severity"] == "CRITICAL" else "MEDIUM",
                    "recommended_by": "playbook_agent",
                    "evidence_summary": (
                        f"{state['instana_diagnosis'][:400]}\n"
                        f"Precedent: {best.get('key', 'none')} "
                        f"({best.get('resolution_time_min', '?')} min)"
                    ),
                }
            )
        )

    return {
        "approval_id": approval.get("approval_id", ""),
        "approval_status": "PENDING",
        "messages": [AIMessage(content="[HitL] approval requested", name="hitl")],
        "ui_events": [
            _event(
                "hitl",
                "Human-in-the-Loop gate",
                {
                    "approval_id": approval.get("approval_id"),
                    "action_type": action_type,
                    "action_description": action,
                    "risk_level": approval.get("risk_level"),
                    "status": "PENDING_HUMAN_APPROVAL",
                },
            )
        ],
        "phase": "AWAITING_APPROVAL",
    }


def record_decision_node(state: IncidentState, config: RunnableConfig) -> dict:
    """Append the human decision to the audit trail. Runs only after the gate resumes."""
    if state["approval_status"] not in ("APPROVED", "REJECTED"):
        raise RuntimeError(
            "record_decision reached without a human decision — "
            f"approval_status={state['approval_status']!r}. "
            "The HitL gate cannot be bypassed."
        )

    with span("node.record_decision", decision=state["approval_status"]):
        result = json.loads(
            record_human_decision.invoke(
                {
                    "approval_id": state["approval_id"],
                    "decision": state["approval_status"],
                    "decided_by": state["decided_by"] or "unknown",
                    "notes": state["decision_notes"],
                }
            )
        )

    return {
        "audit_entry": result,
        "messages": [AIMessage(content=f"[Audit] {state['approval_status']}", name="audit")],
        "ui_events": [
            _event(
                "record_decision",
                "Audit trail",
                {
                    "decision": state["approval_status"],
                    "decided_by": state["decided_by"],
                    "audit_entry": result.get("audit_entry"),
                },
            )
        ],
        "phase": "RESOLVED" if state["approval_status"] == "APPROVED" else "REJECTED",
    }


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

NODE_SEQUENCE: list[tuple[str, str]] = [
    ("instana", "Instana — diagnosis and blast radius"),
    ("jira", "Jira — precedents and ticket"),
    ("rag", "Knowledge base — runbooks and postmortems"),
    ("playbook", "Remediation playbook"),
    ("teams_war_room", "Teams war room"),
    ("hitl", "Human-in-the-Loop gate"),
    ("record_decision", "Audit trail"),
]

INTERRUPT_AFTER: list[str] = ["hitl"]


def build_graph() -> CompiledStateGraph:
    """Build and compile the crisis response graph."""
    graph: StateGraph = StateGraph(IncidentState)

    graph.add_node("instana", instana_node)
    graph.add_node("jira", jira_node)
    graph.add_node("rag", rag_node)
    graph.add_node("playbook", playbook_node)
    graph.add_node("teams_war_room", teams_node)
    graph.add_node("hitl", hitl_node)
    graph.add_node("record_decision", record_decision_node)

    graph.add_edge(START, "instana")
    graph.add_edge("instana", "jira")
    graph.add_edge("jira", "rag")
    graph.add_edge("rag", "playbook")
    graph.add_edge("playbook", "teams_war_room")
    graph.add_edge("teams_war_room", "hitl")
    graph.add_edge("hitl", "record_decision")
    graph.add_edge("record_decision", END)

    # Governance: the graph stops after `hitl` and cannot reach `record_decision`
    # (or anything downstream of it) until the API layer writes a human decision
    # into the checkpointed state and explicitly resumes.
    return graph.compile(checkpointer=MemorySaver(), interrupt_after=INTERRUPT_AFTER)


_GRAPH: CompiledStateGraph | None = None


def get_graph() -> CompiledStateGraph:
    """Return the process-wide compiled graph.

    A single instance is required so the MemorySaver checkpointer keeps paused
    runs alive between the HTTP request that starts them and the one that approves.
    """
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


def graph_definition() -> dict:
    """Introspect the compiled graph — used by ``GET /graph/definition``.

    Read from the compiled object rather than hand-written, so the diagram in the
    dashboard can never drift from the topology that actually executes.
    """
    compiled = get_graph()
    drawable = compiled.get_graph()
    labels = dict(NODE_SEQUENCE)
    nodes = [
        {"id": nid, "label": labels.get(nid, nid)}
        for nid in drawable.nodes
        if nid not in ("__start__", "__end__")
    ]
    edges = [
        {
            "from": "START" if e.source == "__start__" else e.source,
            "to": "END" if e.target == "__end__" else e.target,
            "conditional": bool(getattr(e, "conditional", False)),
        }
        for e in drawable.edges
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "interrupt_after": INTERRUPT_AFTER,
        "checkpointer": type(compiled.checkpointer).__name__,
        "source": "introspected from the compiled StateGraph",
    }


def run_incident(incident_id: str, thread_id: str | None = None) -> dict:
    """Run the workflow up to the HitL interrupt and return the paused state."""
    graph = get_graph()
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id or incident_id},
        "recursion_limit": 50,
    }
    graph.invoke(default_state(incident_id), config=config)
    return dict(graph.get_state(config).values)


def resume_with_decision(thread_id: str, decision: str, decided_by: str, notes: str = "") -> dict:
    """Write the human decision into the checkpoint and resume past the gate."""
    graph = get_graph()
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    graph.update_state(
        config,
        {"approval_status": decision, "decided_by": decided_by, "decision_notes": notes},
    )
    graph.invoke(None, config=config)
    return dict(graph.get_state(config).values)

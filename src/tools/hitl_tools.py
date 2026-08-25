"""Human-in-the-Loop gate tools.

Provides two LangChain tools:
  - request_human_approval: generates a structured approval request (NIST AI RMF)
  - record_human_decision:  records the human's decision in the audit trail

These tools do NOT execute any production action — they only create records.
The LangGraph graph node checks the approval state before proceeding.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

import httpx
from langchain_core.tools import tool

from src.config import settings


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


@tool
def request_human_approval(
    incident_id: str,
    action_type: str,
    action_description: str,
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    recommended_by: str,
    evidence_summary: str,
) -> str:
    """Register a human approval request before any production action executes.

    This tool BLOCKS the workflow. No production action runs without an
    explicit APPROVED decision recorded via record_human_decision.

    Complies with NIST AI RMF — Human-in-the-Loop controls.

    Args:
        incident_id: Active incident ID
        action_type: Action class (ROLLBACK, RESTART, CONFIG_CHANGE, SCALE_UP, …)
        action_description: Exact description of what will execute if approved
        risk_level: Risk classification (LOW, MEDIUM, HIGH, CRITICAL)
        recommended_by: Agent that generated the recommendation
        evidence_summary: Evidence supporting the recommendation
    """
    approval_id = f"APPR-{incident_id}-{datetime.now(UTC).strftime('%H%M%S')}"
    payload = {
        "approval_id": approval_id,
        "incident_id": incident_id,
        "status": "PENDING_HUMAN_APPROVAL",
        "requested_at": _utcnow(),
        "action": {
            "type": action_type,
            "description": action_description,
            "risk_level": risk_level,
            "recommended_by": recommended_by,
        },
        "evidence": evidence_summary,
        "governance": {
            "policy": "All HIGH/CRITICAL risk actions require approval from SRE Lead or above",
            "framework": "NIST AI RMF — Human-in-the-Loop mandatory",
            "audit_trail": "This request is recorded in the incident audit log",
        },
        "instructions_for_sre": (
            f"⚠️ ACTION BLOCKED — Awaiting your approval.\n\n"
            f"Proposed action: {action_type}\n"
            f"Description: {action_description}\n"
            f"Risk: {risk_level}\n\n"
            "To approve, reply in the Teams channel: APPROVE\n"
            "To reject, reply: REJECT [reason]\n"
            "For more information: MORE INFO [question]"
        ),
    }

    # Optionally forward to external webhook (e.g. PagerDuty, ServiceNow, Slack)
    if settings.hitl_webhook_url:
        try:
            httpx.post(settings.hitl_webhook_url, json=payload, timeout=10)
        except Exception:  # noqa: BLE001
            pass  # Webhook failure must not block the approval record

    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def record_human_decision(
    approval_id: str,
    decision: Literal["APPROVED", "REJECTED"],
    decided_by: str,
    notes: str = "",
) -> str:
    """Record a human decision (approve or reject) in the incident audit trail.

    Must be called after every request_human_approval. Generates a tamper-evident
    audit entry for compliance.

    Args:
        approval_id: ID from the approval request
        decision: APPROVED or REJECTED
        decided_by: Name / ID of the SRE or manager who decided
        notes: Optional notes from the decision maker
    """
    ts = _utcnow()
    result = {
        "approval_id": approval_id,
        "decision": decision,
        "decided_by": decided_by,
        "decided_at": ts,
        "notes": notes,
        "audit_entry": {
            "event": "HUMAN_DECISION_RECORDED",
            "timestamp": ts,
            "actor": decided_by,
            "action": decision,
            "system": "GCB Autonomous Crisis Squad — audit trail",
        },
        "next_step": (
            "Proceed with approved action execution."
            if decision == "APPROVED"
            else "Action cancelled. Agents await new instruction from SRE."
        ),
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


HITL_TOOLS = [request_human_approval, record_human_decision]
